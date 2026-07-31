from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import requests

from app import public_replay_client


REMOTE_ID = "0123456789abcdef01234567"
SAME_ID = "abcdefabcdefabcdefabcdef"
BASE_A = "https://replays.example.test"
BASE_B = "https://replays-b.example.test"


class _Response:
    def __init__(
        self,
        value: dict | None = None,
        status: int = 200,
        *,
        url: str = "",
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> None:
        self.status_code = status
        self.content = (
            content
            if content is not None
            else json.dumps(value or {}, ensure_ascii=False).encode("utf-8")
        )
        self.url = url
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class PublicReplayClientTests(unittest.TestCase):
    def setUp(self) -> None:
        public_replay_client.invalidate()

    def tearDown(self) -> None:
        public_replay_client.invalidate()

    def _env(self, cache_dir: Path, base_url: str = BASE_A) -> dict[str, str]:
        return {
            public_replay_client.BASE_URL_ENV: base_url,
            public_replay_client.CACHE_DIR_ENV: str(cache_dir),
        }

    def _manifest(self) -> dict:
        return {
            "schema_version": 1,
            "generated_at": "2026-07-31T00:00:00Z",
            "rows": [
                {
                    "id": REMOTE_ID,
                    "encounter": "공개 보스",
                    "encounter_id": 9001,
                    "duration": 180.0,
                    "start_local": "2026-07-31 01:00:00",
                    "capabilities": {"analysis": True},
                    "public_artifacts": {
                        "detail": f"replays/{REMOTE_ID}/detail.json",
                        "frames": f"replays/{REMOTE_ID}/frames.json",
                        "terrain": "",
                        "video": f"videos/{REMOTE_ID}",
                    },
                },
                {
                    "id": SAME_ID,
                    "encounter": "원격 중복",
                    "duration": 200.0,
                    "start_local": "2026-07-30 01:00:00",
                    "public_artifacts": {
                        "detail": f"replays/{SAME_ID}/detail.json",
                        "frames": f"replays/{SAME_ID}/frames.json",
                        "terrain": "",
                        "video": "",
                    },
                },
            ],
            "stats": {"replays": 2, "videos": 1, "terrain": 0},
        }

    def _detail(self) -> dict:
        return {
            "schema_version": 1,
            "capture": {"id": REMOTE_ID},
            "sources": {"log_file": r"C:\private\WoWCombatLog.txt"},
            "video": {"available": False, "url": ""},
        }

    def test_merge_adds_public_rows_and_keeps_local_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            cache_dir = Path(tmp_raw)
            with (
                patch.dict(os.environ, self._env(cache_dir), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    return_value=_Response(self._manifest()),
                ),
            ):
                listing = public_replay_client.merge_listing({
                    "sources": {"log_only": 0},
                    "rows": [{
                        "id": SAME_ID,
                        "encounter": "로컬 우선",
                        "start_local": "2026-07-30 01:00:00",
                    }],
                })

        rows = {row["id"]: row for row in listing["rows"]}
        self.assertEqual({SAME_ID, REMOTE_ID}, set(rows))
        self.assertEqual("로컬 우선", rows[SAME_ID]["encounter"])
        self.assertTrue(rows[REMOTE_ID]["public_remote"])
        self.assertTrue(rows[REMOTE_ID]["video_remote"])
        self.assertTrue(rows[REMOTE_ID]["capabilities"]["frames"])
        self.assertFalse(rows[REMOTE_ID]["capabilities"]["terrain"])
        self.assertEqual(1, listing["sources"]["public_replays"])
        self.assertEqual("remote", listing["sources"]["public_remote"]["source"])

    def test_manifest_uses_only_matching_endpoint_disk_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            cache_dir = Path(tmp_raw)
            env_a = self._env(cache_dir, BASE_A)
            with (
                patch.dict(os.environ, env_a, clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    return_value=_Response(self._manifest()),
                ),
            ):
                self.assertEqual(2, len(public_replay_client.rows(force=True)))

            public_replay_client.invalidate()
            with (
                patch.dict(os.environ, env_a, clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=requests.ConnectionError("offline"),
                ),
            ):
                cached_rows = public_replay_client.rows(force=True)
                cached_state = public_replay_client.status()

            public_replay_client.invalidate()
            with (
                patch.dict(os.environ, self._env(cache_dir, BASE_B), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=requests.ConnectionError("offline"),
                ),
            ):
                switched_rows = public_replay_client.rows(force=True)
                switched_state = public_replay_client.status()

        self.assertEqual(2, len(cached_rows))
        self.assertTrue(cached_state["available"])
        self.assertTrue(cached_state["stale"])
        self.assertEqual("cache", cached_state["source"])
        self.assertEqual([], switched_rows)
        self.assertFalse(switched_state["available"])

    def test_detail_cache_is_scoped_and_rewrites_video_to_local_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            cache_dir = Path(tmp_raw)
            env = self._env(cache_dir)
            responses = [_Response(self._manifest()), _Response(self._detail())]
            with (
                patch.dict(os.environ, env, clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=responses,
                ),
            ):
                out = public_replay_client.detail(REMOTE_ID)

            with (
                patch.dict(os.environ, env, clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=requests.ConnectionError("offline"),
                ),
            ):
                cached = public_replay_client.detail(REMOTE_ID)

        self.assertEqual({"public_remote": True}, out["sources"])
        self.assertTrue(out["video"]["available"])
        self.assertEqual(
            f"/api/local-replay/video-remote/{REMOTE_ID}",
            out["video"]["url"],
        )
        self.assertEqual(out, cached)

    def test_removed_manifest_replay_never_returns_old_artifact_cache(self) -> None:
        removed_manifest = {
            "schema_version": 1,
            "generated_at": "2026-07-31T01:00:00Z",
            "rows": [],
            "stats": {"replays": 0, "videos": 0, "terrain": 0},
        }
        with tempfile.TemporaryDirectory() as tmp_raw:
            env = self._env(Path(tmp_raw))
            with (
                patch.dict(os.environ, env, clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=[_Response(self._manifest()), _Response(self._detail())],
                ),
            ):
                public_replay_client.detail(REMOTE_ID)

            with (
                patch.dict(os.environ, env, clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    return_value=_Response(removed_manifest),
                ),
            ):
                self.assertEqual([], public_replay_client.rows(force=True))

            with (
                patch.dict(os.environ, env, clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=AssertionError("artifact network request must not run"),
                ),
            ):
                with self.assertRaises(public_replay_client.PublicReplayError):
                    public_replay_client.detail(REMOTE_ID)

    def test_base_url_switch_rejects_memory_and_artifact_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            cache_dir = Path(tmp_raw)
            with (
                patch.dict(os.environ, self._env(cache_dir, BASE_A), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=[_Response(self._manifest()), _Response(self._detail())],
                ),
            ):
                public_replay_client.detail(REMOTE_ID)

            # invalidate를 호출하지 않아도 scope 불일치로 A의 memory/artifact를 쓰지 않는다.
            with (
                patch.dict(os.environ, self._env(cache_dir, BASE_B), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=[
                        _Response(self._manifest()),
                        requests.ConnectionError("B offline"),
                    ],
                ) as get,
            ):
                with self.assertRaises(public_replay_client.PublicReplayError):
                    public_replay_client.detail(REMOTE_ID)

        self.assertEqual(2, get.call_count)
        self.assertTrue(get.call_args_list[0].args[0].startswith(BASE_B))
        self.assertTrue(get.call_args_list[1].args[0].startswith(BASE_B))

    def test_manifest_malformed_values_are_reported_without_list_exception(self) -> None:
        cases: list[tuple[str, Callable[[dict], None]]] = [
            ("schema", lambda value: value.update(schema_version="bad")),
            ("rows", lambda value: value.update(rows={})),
            ("stats", lambda value: value.update(stats=[])),
            ("row", lambda value: value["rows"].__setitem__(0, [])),
            (
                "id",
                lambda value: value["rows"][0].update(id="remote-1"),
            ),
            (
                "capabilities",
                lambda value: value["rows"][0].update(capabilities=[]),
            ),
            (
                "artifact",
                lambda value: value["rows"][0]["public_artifacts"].update(
                    detail=f"replays/{REMOTE_ID}/other.json"
                ),
            ),
        ]
        for name, mutate in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp_raw:
                public_replay_client.invalidate()
                malformed = copy.deepcopy(self._manifest())
                mutate(malformed)
                with (
                    patch.dict(
                        os.environ,
                        self._env(Path(tmp_raw)),
                        clear=False,
                    ),
                    patch(
                        "app.public_replay_client.requests.get",
                        return_value=_Response(malformed),
                    ),
                ):
                    listing = public_replay_client.merge_listing(
                        {"sources": {}, "rows": []},
                        force=True,
                    )
                    state = public_replay_client.status()
                self.assertEqual([], listing["rows"])
                self.assertFalse(state["available"])
                self.assertTrue(state["error"])

    def test_manifest_rejects_parent_path_and_exact_contract_mismatch(self) -> None:
        manifest = self._manifest()
        manifest["rows"][0]["public_artifacts"]["detail"] = "../logs/raw.txt"
        with tempfile.TemporaryDirectory() as tmp_raw:
            with (
                patch.dict(os.environ, self._env(Path(tmp_raw)), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    return_value=_Response(manifest),
                ),
            ):
                self.assertEqual([], public_replay_client.rows(force=True))
                state = public_replay_client.status()

        self.assertFalse(state["available"])
        self.assertIn("안전하지 않음", state["error"])

    def test_cross_origin_redirect_is_rejected_before_following(self) -> None:
        manifest_url = f"{BASE_A}/manifest.json"
        redirect = _Response(
            status=302,
            url=manifest_url,
            headers={"Location": "https://attacker.example/manifest.json"},
        )
        with tempfile.TemporaryDirectory() as tmp_raw:
            with (
                patch.dict(os.environ, self._env(Path(tmp_raw)), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    return_value=redirect,
                ) as get,
            ):
                self.assertEqual([], public_replay_client.rows(force=True))
                state = public_replay_client.status()

        self.assertEqual(1, get.call_count)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertIn("redirect origin", state["error"])

    def test_final_response_url_must_keep_requested_origin(self) -> None:
        response = _Response(
            self._manifest(),
            url="https://attacker.example/manifest.json",
        )
        with tempfile.TemporaryDirectory() as tmp_raw:
            with (
                patch.dict(os.environ, self._env(Path(tmp_raw)), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    return_value=response,
                ),
            ):
                self.assertEqual([], public_replay_client.rows(force=True))
                state = public_replay_client.status()

        self.assertIn("다른 origin", state["error"])

    def test_same_origin_relative_redirect_is_allowed(self) -> None:
        manifest_url = f"{BASE_A}/manifest.json"
        with tempfile.TemporaryDirectory() as tmp_raw:
            with (
                patch.dict(os.environ, self._env(Path(tmp_raw)), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=[
                        _Response(
                            status=302,
                            url=manifest_url,
                            headers={"Location": "/v1/manifest.json"},
                        ),
                        _Response(
                            self._manifest(),
                            url=f"{BASE_A}/v1/manifest.json",
                        ),
                    ],
                ) as get,
            ):
                self.assertEqual(2, len(public_replay_client.rows(force=True)))

        self.assertEqual(2, get.call_count)
        self.assertTrue(all(
            item.kwargs["allow_redirects"] is False
            for item in get.call_args_list
        ))

    def test_artifact_cross_origin_redirect_is_not_followed_or_cached(self) -> None:
        artifact_url = f"{BASE_A}/replays/{REMOTE_ID}/detail.json"
        with tempfile.TemporaryDirectory() as tmp_raw:
            with (
                patch.dict(os.environ, self._env(Path(tmp_raw)), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=[
                        _Response(self._manifest()),
                        _Response(
                            status=302,
                            url=artifact_url,
                            headers={
                                "Location": "http://127.0.0.1:8080/private.json"
                            },
                        ),
                    ],
                ) as get,
            ):
                with self.assertRaises(public_replay_client.PublicReplayError):
                    public_replay_client.detail(REMOTE_ID)

        self.assertEqual(2, get.call_count)

    def test_malformed_detail_is_public_replay_error(self) -> None:
        malformed = self._detail()
        malformed["sources"] = ["not", "an", "object"]
        with tempfile.TemporaryDirectory() as tmp_raw:
            with (
                patch.dict(os.environ, self._env(Path(tmp_raw)), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=[_Response(self._manifest()), _Response(malformed)],
                ),
            ):
                with self.assertRaises(public_replay_client.PublicReplayError):
                    public_replay_client.detail(REMOTE_ID)

    def test_public_id_and_artifact_paths_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            with (
                patch.dict(os.environ, self._env(Path(tmp_raw)), clear=False),
                patch(
                    "app.public_replay_client.requests.get",
                    side_effect=AssertionError("invalid ID must not hit network"),
                ),
            ):
                self.assertFalse(public_replay_client.has_replay("remote-1"))
                with self.assertRaises(public_replay_client.PublicReplayError):
                    public_replay_client.detail("remote-1")

    def test_plain_http_is_only_allowed_for_loopback(self) -> None:
        with patch.dict(
            os.environ,
            {public_replay_client.BASE_URL_ENV: "http://example.test"},
            clear=False,
        ):
            self.assertFalse(public_replay_client.configured())
        with patch.dict(
            os.environ,
            {public_replay_client.BASE_URL_ENV: "http://127.0.0.1:8787"},
            clear=False,
        ):
            self.assertTrue(public_replay_client.configured())


if __name__ == "__main__":
    unittest.main()
