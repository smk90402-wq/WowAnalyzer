from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import cctv_sync, local_replay


class CctvSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        cctv_sync.invalidate()
        cctv_sync._last_error = ""
        cctv_sync._last_success_at = ""

    def test_available_honors_rclone_config_override_and_r2_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            conf = Path(tmp_raw) / "portable-rclone.conf"
            conf.write_text("[other]\ntype = local\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"RCLONE_CONFIG": str(conf)}, clear=False),
                patch.object(cctv_sync, "_rclone", return_value="rclone.exe"),
            ):
                self.assertFalse(cctv_sync.available())
                conf.write_text("[r2]\ntype = s3\n", encoding="utf-8")
                self.assertTrue(cctv_sync.available())

    def test_rclone_fallback_accepts_new_winget_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            root = Path(tmp_raw)
            exe = (
                root
                / "Microsoft"
                / "WinGet"
                / "Packages"
                / "Rclone.Rclone_Test"
                / "rclone-v9.9.9-windows-amd64"
                / "rclone.exe"
            )
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": str(root)}, clear=False),
                patch("shutil.which", return_value=None),
            ):
                self.assertEqual(str(exe), cctv_sync._rclone())

    def test_failed_json_copy_does_not_start_ttl_or_log_thread(self) -> None:
        cctv_sync._last_sync = 0.0
        with (
            patch.object(cctv_sync, "available", return_value=True),
            patch.object(cctv_sync, "_copy", return_value=False) as copy,
            patch("app.cctv_sync.time.monotonic", return_value=1000.0),
            patch("app.cctv_sync.threading.Thread") as thread,
        ):
            mirror = cctv_sync.ensure_mirror()

        self.assertEqual(cctv_sync.MIRROR / "cctv", mirror)
        self.assertEqual(0.0, cctv_sync._last_sync)
        copy.assert_called_once()
        thread.assert_not_called()

    def test_cached_mirror_is_listed_without_rclone_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            root = Path(tmp_raw)
            local_root = root / "local"
            mirror_root = root / "mirror"
            local_root.mkdir()
            mirror_root.mkdir()
            cached = {
                "id": "cached-remote",
                "file": "cached.json",
                "encounter_id": 9001,
                "encounter": "Cached Boss",
                "duration": 180.0,
                "start_local": "2026-07-23 01:00:00",
            }

            def load_captures(path=None, limit=80):
                return [cached] if path == mirror_root else []

            with (
                patch.object(
                    local_replay,
                    "_load_captures",
                    side_effect=load_captures,
                ),
                patch.object(local_replay, "_standalone_log_paths", return_value=[]),
                patch.object(local_replay, "_load_log_replay_caps", return_value=[]),
                patch.object(local_replay, "latest_log_path", return_value=None),
                patch.object(local_replay, "wow_log_dir", return_value=root),
                patch.object(local_replay, "cctv_dir", return_value=local_root),
                patch.object(
                    local_replay,
                    "_lura_sync_index",
                    return_value=local_replay._empty_lura_sync_index(),
                ),
                patch.object(cctv_sync, "available", return_value=False),
                patch.object(cctv_sync, "ensure_mirror", return_value=mirror_root),
                patch.object(
                    cctv_sync,
                    "sync_status",
                    return_value={
                        "available": False,
                        "mirror_captures": 1,
                    },
                ),
            ):
                listing = local_replay.list_replays()

        self.assertEqual(["cached-remote"], [
            row["id"] for row in listing["rows"]
        ])
        self.assertEqual(1, listing["sources"]["private_remote"]["mirror_captures"])


if __name__ == "__main__":
    unittest.main()
