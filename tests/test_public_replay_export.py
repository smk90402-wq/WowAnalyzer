from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import call, patch

from app import local_replay
from app.public_replay_export import (
    PublicReplayExportError,
    export_public_replays,
)


SOURCE_ID = "private-replay-id"
PLAYER_GUID = "Player-3687-0ABCDEF0"
PLAYER_NAME = "Alpha-Azshara"
SECOND_PLAYER_GUID = "Player-3687-0FEDCBA0"
SECOND_PLAYER_NAME = "Alpha-Draenor"


def _listing() -> dict:
    return {
        "sources": {
            "log_file": r"C:\Program Files (x86)\World of Warcraft\Logs\WoWCombatLog.txt",
            "cctv_dir": r"E:\cctv",
        },
        "rows": [{
            "id": SOURCE_ID,
            "file": r"C:\Users\Owner\Desktop\capture.json",
            "encounter_id": 3183,
            "encounter": "르우라",
            "difficulty": "신화",
            "difficulty_id": 16,
            "duration": 301,
            "result": False,
            "player": PLAYER_NAME,
            "player_guid": PLAYER_GUID,
            "start": 1784422800000,
            "start_local": "2026-07-19 10:00:00",
            "video_exists": True,
            "video_remote": False,
            "video_size_mb": 1500.0,
            "log_match": {
                "encounter_id": 3183,
                "start_line": 123,
                "end_line": 999,
            },
            "analysis": {
                "source": "local+wcl",
                "report_code": "PrivateReport",
                "report_url": "https://www.warcraftlogs.com/reports/PrivateReport",
                "first_death": {"name": PLAYER_NAME},
            },
        }],
    }


def _detail() -> dict:
    row = dict(_listing()["rows"][0])
    return {
        "capture": row,
        "encounter": {"encounter_id": 3183, "encounter": "르우라"},
        "duration": 301.0,
        "events": [{
            "t": 12.5,
            "event": "SPELL_DAMAGE",
            "source": "르우라",
            "target": PLAYER_NAME,
            "spell": "별빛파열",
        }],
        "positions": [{
            "t": 12.5,
            "guid": PLAYER_GUID,
            "name": PLAYER_NAME,
            "x": 100.0,
            "y": 200.0,
        }],
        "actors": [
            {
                "guid": PLAYER_GUID,
                "name": PLAYER_NAME,
                "realm": "Azshara",
                "spec_id": 253,
            },
            {
                "guid": "Creature-0-0-0-0-3183-0000000001",
                "name": "르우라",
            },
        ],
        "counts": {"damage": 1},
        "sources": {
            "log_file": r"C:\World of Warcraft\Logs\WoWCombatLog.txt",
            "json_file": r"E:\cctv\capture.json",
            "video_file": r"E:\cctv\capture.mp4",
        },
        "video": {
            "available": True,
            "url": "https://secret.example.invalid/presigned?token=secret",
            "remote": True,
        },
    }


def _frames() -> dict:
    return {
        "meta": {
            "encounter": "르우라",
            "encounter_id": 3183,
            "difficulty_id": 16,
            "duration_s": 301.0,
            "units": [
                {
                    "id": "p1",
                    "name": PLAYER_NAME,
                    "kind": "player",
                    "cls": "HUNTER",
                },
                {"id": "b1", "name": "르우라", "kind": "boss", "cls": ""},
            ],
            "deaths": [{"t": 20.0, "id": "p1"}],
        },
        "frames": [{"t": 0.0, "p": {"p1": [100.0, 200.0, 1.0, 100]}}],
        "boss_events": [{
            "t": 12.5,
            "target": "p1",
            "target_name": PLAYER_NAME,
            "spell": "별빛파열",
        }],
        "player_events": [],
        "review_focus": {
            "player_guid": PLAYER_GUID,
            "label": f"{PLAYER_NAME} 확인",
        },
        "counts": {"positions": 1},
    }


class PublicReplayExportTests(unittest.TestCase):
    def test_incomplete_capture_does_not_consume_successful_row_limit(self) -> None:
        detail_orphan_id = "detail-orphan-replay-id"
        frames_orphan_id = "frames-orphan-replay-id"
        detail_orphan_row = dict(_listing()["rows"][0], id=detail_orphan_id)
        frames_orphan_row = dict(_listing()["rows"][0], id=frames_orphan_id)
        valid_row = dict(_listing()["rows"][0])
        candidates = [detail_orphan_row, frames_orphan_row, valid_row]

        def detail(source_id: str) -> dict:
            if source_id == detail_orphan_id:
                raise local_replay.ReplayError("replay detail unavailable")
            return _detail()

        def frames(source_id: str) -> dict:
            if source_id == frames_orphan_id:
                raise local_replay.ReplayError("log encounter not found")
            return _frames()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "public"
            with (
                patch.object(
                    local_replay,
                    "list_replays",
                    return_value={"sources": {}, "rows": candidates},
                ) as list_replays,
                patch.object(
                    local_replay,
                    "replay_detail",
                    side_effect=detail,
                ) as replay_detail,
                patch.object(
                    local_replay,
                    "replay_frames",
                    side_effect=frames,
                ) as replay_frames,
            ):
                result = export_public_replays(
                    output,
                    limit=1,
                    include_terrain=False,
                )

            manifest = json.loads((output / "manifest.json").read_text("utf-8"))

        list_replays.assert_called_once_with(limit=None)
        self.assertEqual(
            [call(detail_orphan_id), call(frames_orphan_id), call(SOURCE_ID)],
            replay_detail.call_args_list,
        )
        self.assertEqual(
            [call(frames_orphan_id), call(SOURCE_ID)],
            replay_frames.call_args_list,
        )
        self.assertEqual(1, result.replays)
        self.assertEqual(1, manifest["stats"]["replays"])
        self.assertEqual(1, len(manifest["rows"]))

    def test_default_video_resolver_replay_error_skips_candidate(self) -> None:
        orphan_id = "video-orphan-replay-id"
        candidates = [
            dict(_listing()["rows"][0], id=orphan_id),
            dict(_listing()["rows"][0]),
        ]

        def resolve_video(source_id: str, _row: dict) -> str:
            if source_id == orphan_id:
                raise local_replay.ReplayError("capture not found")
            return "cctv/valid-video.mp4"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "public"
            private_map = root / "private" / "video_map.json"
            with (
                patch.object(
                    local_replay,
                    "list_replays",
                    return_value={"sources": {}, "rows": candidates},
                ),
                patch.object(local_replay, "replay_detail", return_value=_detail()),
                patch.object(local_replay, "replay_frames", return_value=_frames()),
                patch(
                    "app.public_replay_export._default_video_object_key",
                    side_effect=resolve_video,
                ) as default_resolver,
            ):
                result = export_public_replays(
                    output,
                    private_video_map=private_map,
                    limit=1,
                    include_terrain=False,
                )

            manifest = json.loads((output / "manifest.json").read_text("utf-8"))
            video_map = json.loads(private_map.read_text("utf-8"))

        self.assertEqual(
            [call(orphan_id, candidates[0]), call(SOURCE_ID, candidates[1])],
            default_resolver.call_args_list,
        )
        self.assertEqual(1, result.replays)
        self.assertEqual(1, manifest["stats"]["replays"])
        self.assertEqual(1, len(video_map["videos"]))

    def test_video_allowlist_skips_missing_before_frames_and_fills_limit(self) -> None:
        missing_id = "missing-video-replay-id"
        candidates = [
            dict(_listing()["rows"][0], id=missing_id),
            dict(_listing()["rows"][0]),
        ]

        def resolve_video(source_id: str, _row: dict) -> str:
            return (
                "cctv/missing-video.mp4"
                if source_id == missing_id else "cctv/available-video.mp4"
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "public"
            private_map = root / "private" / "video_map.json"
            with (
                patch.object(
                    local_replay,
                    "list_replays",
                    return_value={"sources": {}, "rows": candidates},
                ),
                patch.object(
                    local_replay,
                    "replay_detail",
                    return_value=_detail(),
                ) as replay_detail,
                patch.object(
                    local_replay,
                    "replay_frames",
                    return_value=_frames(),
                ) as replay_frames,
                patch(
                    "app.public_replay_export._default_video_object_key",
                    side_effect=resolve_video,
                ) as default_resolver,
            ):
                result = export_public_replays(
                    output,
                    private_video_map=private_map,
                    limit=1,
                    include_terrain=False,
                    available_video_keys={"cctv/available-video.mp4"},
                )

            manifest = json.loads((output / "manifest.json").read_text("utf-8"))
            video_map = json.loads(private_map.read_text("utf-8"))

        self.assertEqual(
            [call(missing_id, candidates[0]), call(SOURCE_ID, candidates[1])],
            default_resolver.call_args_list,
        )
        replay_detail.assert_called_once_with(SOURCE_ID)
        replay_frames.assert_called_once_with(SOURCE_ID)
        self.assertEqual(1, result.replays)
        self.assertEqual(1, manifest["stats"]["replays"])
        self.assertEqual(
            ["cctv/available-video.mp4"],
            list(video_map["videos"].values()),
        )

    def test_empty_video_allowlist_preserves_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "public"
            output.mkdir()
            (output / "manifest.json").write_text('{"old":true}\n', "utf-8")
            with patch.object(local_replay, "list_replays") as list_replays:
                with self.assertRaisesRegex(
                    PublicReplayExportError,
                    "allowlist is empty",
                ):
                    export_public_replays(
                        output,
                        private_video_map=root / "private" / "video_map.json",
                        available_video_keys=set(),
                    )

            self.assertEqual(
                {"old": True},
                json.loads((output / "manifest.json").read_text("utf-8")),
            )
            list_replays.assert_not_called()

    def test_same_name_on_different_realms_keeps_distinct_player_aliases(self) -> None:
        listing = _listing()
        detail = _detail()
        frames = _frames()
        detail["actors"].insert(1, {
            "guid": SECOND_PLAYER_GUID,
            "name": SECOND_PLAYER_NAME,
            "realm": "Draenor",
            "spec_id": 253,
        })
        detail["positions"].append({
            "t": 12.5,
            "guid": SECOND_PLAYER_GUID,
            "name": SECOND_PLAYER_NAME,
            "x": 105.0,
            "y": 205.0,
        })
        detail["events"].extend([
            {
                "t": 13.0,
                "event": "SPELL_DAMAGE",
                "source": "르우라",
                "target": SECOND_PLAYER_NAME,
                "spell": "별빛파열",
            },
            {
                "t": 13.1,
                "event": "NOTE",
                "source": "",
                "target": "",
                "spell": "Alpha 확인",
            },
        ])
        frames["meta"]["units"].insert(1, {
            "id": "p2",
            "name": SECOND_PLAYER_NAME,
            "kind": "player",
            "cls": "HUNTER",
        })
        frames["frames"][0]["p"]["p2"] = [105.0, 205.0, 1.0, 100]
        frames["boss_events"].append({
            "t": 13.0,
            "target": "p2",
            "target_name": SECOND_PLAYER_NAME,
            "spell": "별빛파열",
        })
        frames["review_focus"]["realm_less_label"] = "Alpha 확인"

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "public"
            with (
                patch.object(local_replay, "list_replays", return_value=listing),
                patch.object(local_replay, "replay_detail", return_value=detail),
                patch.object(local_replay, "replay_frames", return_value=frames),
            ):
                export_public_replays(output, include_terrain=False)

            manifest = json.loads((output / "manifest.json").read_text("utf-8"))
            public_id = manifest["rows"][0]["id"]
            exported_detail = json.loads(
                (output / "replays" / public_id / "detail.json").read_text("utf-8")
            )
            exported_frames = json.loads(
                (output / "replays" / public_id / "frames.json").read_text("utf-8")
            )

        player_actors = [
            actor for actor in exported_detail["actors"]
            if actor["guid"].startswith("p")
        ]
        self.assertEqual(
            [("p1", "Player 1"), ("p2", "Player 2")],
            [(actor["guid"], actor["name"]) for actor in player_actors],
        )
        player_units = [
            unit for unit in exported_frames["meta"]["units"]
            if unit["kind"] == "player"
        ]
        self.assertEqual(
            [("p1", "Player 1"), ("p2", "Player 2")],
            [(unit["id"], unit["name"]) for unit in player_units],
        )
        self.assertEqual("Player 2", exported_detail["events"][1]["target"])
        self.assertEqual(
            "Player 확인",
            exported_frames["review_focus"]["realm_less_label"],
        )
        public_text = json.dumps(
            {"detail": exported_detail, "frames": exported_frames},
            ensure_ascii=False,
        )
        for forbidden in ("Alpha", "Azshara", "Draenor", SECOND_PLAYER_GUID):
            self.assertNotIn(forbidden, public_text)

    def test_exports_sanitized_manifest_payloads_and_private_video_map(self) -> None:
        frames_payload = _frames()
        frames_payload["boss_mechanics"] = [{
            "key": "spell:123",
            "spell_id": 123,
            "icon": "ability_warlock_improvedsoulleech",
            "wowhead_url": "https://www.wowhead.com/spell=123",
            "fallback_source_url": "https://example.invalid/mechanic",
        }]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "public"
            private_map = root / "private" / "video_map.json"
            with (
                patch.object(local_replay, "list_replays", return_value=_listing()),
                patch.object(local_replay, "replay_detail", return_value=_detail()),
                patch.object(
                    local_replay,
                    "replay_frames",
                    return_value=frames_payload,
                ),
            ):
                result = export_public_replays(
                    output,
                    private_video_map=private_map,
                    generated_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
                    video_key_resolver=lambda _id, _row: "cctv/raw-video.mp4",
                    terrain_loader=lambda _id: {
                        "grid_w": 1,
                        "grid_h": 1,
                        "world_rect": {
                            "minX": 0,
                            "minY": 0,
                            "maxX": 1,
                            "maxY": 1,
                        },
                        "heights": [12.5],
                    },
                )

            manifest = json.loads((output / "manifest.json").read_text("utf-8"))
            self.assertEqual(1, manifest["schema_version"])
            self.assertEqual("2026-07-31T00:00:00Z", manifest["generated_at"])
            self.assertEqual({"replays": 1, "terrain": 1, "videos": 1}, manifest["stats"])
            self.assertEqual(1, result.replays)
            row = manifest["rows"][0]
            public_id = row["id"]
            self.assertRegex(public_id, r"^[a-f0-9]{24}$")
            self.assertEqual(
                {
                    "detail": f"replays/{public_id}/detail.json",
                    "frames": f"replays/{public_id}/frames.json",
                    "terrain": f"replays/{public_id}/terrain.json",
                    "video": f"videos/{public_id}",
                },
                row["public_artifacts"],
            )
            self.assertEqual("Player 1", row["player"])
            self.assertNotIn("player_guid", row)
            self.assertNotIn("file", row)

            detail = json.loads(
                (output / "replays" / public_id / "detail.json").read_text("utf-8")
            )
            frames = json.loads(
                (output / "replays" / public_id / "frames.json").read_text("utf-8")
            )
            terrain = json.loads(
                (output / "replays" / public_id / "terrain.json").read_text("utf-8")
            )
            self.assertEqual("p1", detail["actors"][0]["guid"])
            self.assertEqual("Player 1", detail["actors"][0]["name"])
            self.assertNotIn("realm", detail["actors"][0])
            self.assertNotIn("sources", detail)
            self.assertEqual(
                {"available": True, "remote": True, "url": ""},
                detail["video"],
            )
            self.assertEqual("Player 1", frames["meta"]["units"][0]["name"])
            self.assertEqual("르우라", frames["meta"]["units"][1]["name"])
            mechanic = frames["boss_mechanics"][0]
            self.assertEqual(
                "ability_warlock_improvedsoulleech",
                mechanic["icon"],
            )
            self.assertNotIn("wowhead_url", mechanic)
            self.assertNotIn("fallback_source_url", mechanic)
            self.assertEqual(1, terrain["schema_version"])
            self.assertEqual(
                {
                    "schemaVersion": 1,
                    "videos": {public_id: "cctv/raw-video.mp4"},
                },
                json.loads(private_map.read_text("utf-8")),
            )

            public_text = "\n".join(
                path.read_text("utf-8") for path in output.rglob("*.json")
            )
            for forbidden in (
                SOURCE_ID,
                PLAYER_GUID,
                "Alpha",
                "Azshara",
                "PrivateReport",
                "raw-video.mp4",
                "C:\\",
                "E:\\",
                "https://",
                "WoWCombatLog",
                "rclone",
                "r2:",
            ):
                self.assertNotIn(forbidden, public_text)

    def test_optional_terrain_failure_keeps_replay_and_sets_null_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "public"
            with (
                patch.object(local_replay, "list_replays", return_value=_listing()),
                patch.object(local_replay, "replay_detail", return_value=_detail()),
                patch.object(local_replay, "replay_frames", return_value=_frames()),
            ):
                result = export_public_replays(
                    output,
                    video_key_resolver=lambda _id, _row: None,
                    terrain_loader=lambda _id: (_ for _ in ()).throw(
                        RuntimeError("terrain unavailable")
                    ),
                )
            manifest = json.loads((output / "manifest.json").read_text("utf-8"))
            self.assertIsNone(manifest["rows"][0]["public_artifacts"]["terrain"])
            self.assertIsNone(manifest["rows"][0]["public_artifacts"]["video"])
            self.assertEqual(0, result.terrain)

    def test_failed_export_preserves_previous_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "public"
            output.mkdir()
            (output / "manifest.json").write_text('{"old":true}\n', "utf-8")
            with (
                patch.object(local_replay, "list_replays", return_value=_listing()),
                patch.object(
                    local_replay,
                    "replay_detail",
                    side_effect=RuntimeError("broken replay"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "broken replay"):
                    export_public_replays(output)
            self.assertEqual(
                {"old": True},
                json.loads((output / "manifest.json").read_text("utf-8")),
            )
            self.assertEqual([], list(root.glob(".public.staging-*")))
            self.assertEqual([], list(root.glob(".public.backup-*")))

    def test_rejects_private_map_under_public_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "public"
            with self.assertRaisesRegex(
                PublicReplayExportError,
                "outside the public output",
            ):
                export_public_replays(
                    output,
                    private_video_map=output / "video_map.json",
                )
            self.assertFalse(output.exists())

    def test_unsafe_video_key_does_not_replace_previous_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "public"
            output.mkdir()
            (output / "manifest.json").write_text('{"old":true}\n', "utf-8")
            with (
                patch.object(local_replay, "list_replays", return_value=_listing()),
                patch.object(local_replay, "replay_detail", return_value=_detail()),
                patch.object(local_replay, "replay_frames", return_value=_frames()),
            ):
                with self.assertRaisesRegex(
                    PublicReplayExportError,
                    "unsafe video object key",
                ):
                    export_public_replays(
                        output,
                        private_video_map=Path(tmp) / "private-video-map.json",
                        video_key_resolver=lambda _id, _row: "../secret.mp4",
                    )
            self.assertEqual(
                {"old": True},
                json.loads((output / "manifest.json").read_text("utf-8")),
            )


if __name__ == "__main__":
    unittest.main()
