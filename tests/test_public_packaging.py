import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.export_public_replays import _available_video_keys


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = REPO_ROOT / "dist"


class PublicPackagingTests(unittest.TestCase):
    def test_export_cli_reads_private_video_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "available-videos.json"
            path.write_text(
                json.dumps({
                    "schemaVersion": 1,
                    "videoKeys": ["cctv/available.mp4"],
                }),
                encoding="utf-8",
            )

            self.assertEqual(
                {"cctv/available.mp4"},
                _available_video_keys(path),
            )

    def test_public_data_copy_uses_explicit_allowlist(self):
        DIST_ROOT.mkdir(exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="_public_data_test_", dir=DIST_ROOT))
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(REPO_ROOT / "scripts" / "copy_public_data.ps1"),
                    "-Destination",
                    str(output),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((output / "data" / "spell_db.json").is_file())
            self.assertTrue((output / "data" / "rotation_data.json").is_file())
            self.assertFalse((output / "data" / "boss_stats.json").exists())
            self.assertFalse(
                (output / "data" / "rankings_zone46_mythic_dps_top100.csv").exists()
            )
            self.assertFalse(
                (output / "data" / "lura_trials_20260719_sync.json").exists()
            )
            self.assertFalse((output / "data" / "user_characters.json").exists())
            self.assertFalse((output / "data" / "char_race_cache.json").exists())
            self.assertFalse((output / "data" / "cache.db").exists())
            self.assertFalse((output / "data" / "cctv_r2").exists())
        finally:
            shutil.rmtree(output, ignore_errors=True)

    def test_public_build_has_a_separate_sanitized_output(self):
        build_script = (REPO_ROOT / "build.bat").read_text(encoding="utf-8")

        self.assertIn('if /I "%~1"=="--public"', build_script)
        self.assertIn('set "DIST_DIR=dist\\LogAnalyzePublic"', build_script)
        self.assertIn('if "%PUBLIC_BUILD%"=="1" goto :copy_public_runtime_files', build_script)
        self.assertIn('if exist "%DIST_DIR%\\.env" goto :public_package_leak', build_script)
        self.assertIn('if exist "%DIST_DIR%\\scripts" goto :public_package_leak', build_script)
        self.assertIn(
            'if exist "%DIST_DIR%\\data\\boss_stats.json" goto :public_package_leak',
            build_script,
        )
        self.assertIn(
            'if exist "%DIST_DIR%\\data\\rankings_zone46_*" goto :public_package_leak',
            build_script,
        )

    def test_default_build_keeps_the_existing_admin_runtime_files(self):
        build_script = (REPO_ROOT / "build.bat").read_text(encoding="utf-8")

        self.assertIn('set "DIST_DIR=dist\\LogAnalyze"', build_script)
        self.assertIn('copy ".env" "%DIST_DIR%\\.env"', build_script)
        self.assertIn(
            'copy /Y "scripts\\*.ps1" "%DIST_DIR%\\scripts\\"',
            build_script,
        )

    def test_public_data_copy_rejects_destination_outside_dist(self):
        with tempfile.TemporaryDirectory(prefix="_public_data_outside_", dir=REPO_ROOT) as temp:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(REPO_ROOT / "scripts" / "copy_public_data.ps1"),
                    "-Destination",
                    temp,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be inside", result.stdout + result.stderr)

    def test_public_config_template_contains_no_secret_fields(self):
        template = (
            REPO_ROOT / "packaging" / "public_release.env.example"
        ).read_text(encoding="utf-8")
        json_template = (
            REPO_ROOT / "packaging" / "public_replay.json.example"
        ).read_text(encoding="utf-8")

        self.assertIn("WOWANALYZER_PUBLIC_REPLAY_BASE_URL=", template)
        self.assertIn('"base_url"', json_template)
        self.assertNotIn("ACCESS_KEY", template.upper())
        self.assertNotIn("SECRET", template.upper())
        self.assertNotIn("WCL_V2_CLIENT_SECRET", template)
        self.assertNotIn("ACCESS_KEY", json_template.upper())
        self.assertNotIn("SECRET", json_template.upper())

    def test_public_config_writer_accepts_https_and_rejects_credentials(self):
        DIST_ROOT.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="_public_config_", dir=DIST_ROOT) as temp:
            output = Path(temp) / "public_replay.json"
            script = REPO_ROOT / "scripts" / "write_public_replay_config.ps1"
            valid = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Destination",
                    str(output),
                    "-BaseUrl",
                    "https://replays.example.test",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)
            self.assertIn(
                "https://replays.example.test",
                output.read_text(encoding="utf-8"),
            )

            invalid = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Destination",
                    str(output),
                    "-BaseUrl",
                    "https://user:pass@replays.example.test",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertNotEqual(0, invalid.returncode)

    def test_publisher_verifies_video_and_artifacts_before_manifest(self):
        script = (
            REPO_ROOT / "scripts" / "publish_public_replays.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn('lsjson "$Remote/cctv" --files-only', script)
        self.assertIn("& $rclone listremotes", script)
        self.assertIn("$mergedVideos", script)
        self.assertIn("& $rclone check $replaysDir", script)
        self.assertIn('"--available-video-keys", $videoAllowlistPath', script)
        self.assertIn("if ($remoteVideos.Count -eq 0)", script)
        self.assertIn(
            "Remove-Item -LiteralPath $videoAllowlistPath",
            script,
        )
        video_list = script.index('lsjson "$Remote/cctv" --files-only')
        empty_guard = script.index("if ($remoteVideos.Count -eq 0)")
        export = script.index("& $python @exportArgs")
        replay_upload = script.index(
            '& $rclone copy $replaysDir "$Remote/public/replays"'
        )
        map_upload = script.index(
            '& $rclone copyto $mergedMapPath "$Remote/_internal/public_video_map.json"'
        )
        manifest_upload = script.index(
            '& $rclone copyto $manifestPath "$Remote/public/manifest.json"'
        )
        self.assertEqual(1, script.count('lsjson "$Remote/cctv" --files-only'))
        self.assertLess(video_list, empty_guard)
        self.assertLess(empty_guard, export)
        self.assertLess(export, replay_upload)
        self.assertLess(replay_upload, map_upload)
        self.assertLess(map_upload, manifest_upload)
        self.assertIn("$manifestPublished", script)
        self.assertIn("$oldManifestPath", script)


if __name__ == "__main__":
    unittest.main()
