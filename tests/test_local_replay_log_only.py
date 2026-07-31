from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app import local_replay


def _line(ts: str, payload: str) -> str:
    return f"7/19/2026 {ts}  {payload}\n"


def _position_event(
    ts: str,
    source_guid: str,
    source_name: str,
    source_flags: str,
    target_guid: str,
    target_name: str,
    advanced_guid: str,
    x: float,
    y: float,
) -> str:
    fields = [
        "SPELL_DAMAGE",
        source_guid,
        f'"{source_name}"',
        source_flags,
        "0x0",
        target_guid,
        f'"{target_name}"',
        "0x10a48" if target_guid.startswith("Creature-") else "0x511",
        "0x0",
        "12345",
        '"Test Hit"',
        "0x1",
        advanced_guid,
        "0000000000000000",
        "1000",
        "1000",
        "100",
        "0",
        "0",
        "0",
        "0",
        "100",
        "100",
        "0",
        "0",
        "0",
        str(x),
        str(y),
        "0",
        "1.5",
        "90",
        "500000",
    ]
    return _line(ts, ",".join(fields))


class LogOnlyReplayTests(unittest.TestCase):
    def test_lura_review_focus_builds_four_replay_checkpoints(self) -> None:
        player_a = "Player-1-A"
        player_b = "Player-1-B"
        boss = "Vehicle-0-BOSS"
        raw = [
            (47.0, "SPELL_CAST_START", 1285708, "암울한 교향곡", boss, "르우라", "", ""),
            (50.5, "SPELL_DAMAGE", 1249584, "불화", boss, "르우라", player_b, "Bravo-Realm"),
            (58.6, "SPELL_DAMAGE", 1282469, "암흑의 준항성", boss, "르우라", player_a, "Alpha-Realm"),
            (184.0, "SPELL_CAST_START", 1255743, "개기 월식", boss, "르우라", "", ""),
            (190.0, "SPELL_AURA_APPLIED", 1285510, "별빛파열", boss, "르우라", player_a, "Alpha-Realm"),
            (225.0, "SPELL_CAST_START", 1282043, "암흑샘 속으로", boss, "르우라", "", ""),
            (231.0, "SPELL_CAST_SUCCESS", 1282043, "암흑샘 속으로", boss, "르우라", "", ""),
            (238.0, "SPELL_CAST_START", 1284528, "활력 주입", boss, "르우라", "", ""),
            (248.6, "SPELL_AURA_APPLIED", 1281184, "임계점", boss, "르우라", player_a, "Alpha-Realm"),
            (252.6, "SPELL_DAMAGE", 1281178, "임계점", boss, "르우라", player_a, "Alpha-Realm"),
            (252.7, "SPELL_DAMAGE", 1281178, "임계점", boss, "르우라", player_b, "Bravo-Realm"),
            (258.0, "SPELL_CAST_START", 1282412, "핵 채취", boss, "르우라", "", ""),
            (322.0, "SPELL_CAST_START", 1281123, "어둠의 용해", boss, "르우라", "", ""),
            (330.0, "SPELL_CAST_SUCCESS", 1281123, "어둠의 용해", boss, "르우라", "", ""),
        ]
        aura_updates = [
            (190.0, "SPELL_AURA_APPLIED", 1285510, player_a, boss, 0),
            (195.0, "SPELL_AURA_REMOVED", 1285510, player_a, boss, 0),
        ]
        casts = {
            player_a: [(193.0, "여명의 수정"), (241.0, "여명의 수정"),
                       (250.0, "여명의 수정")],
            player_b: [(242.0, "여명의 수정"), (251.0, "여명의 수정")],
        }
        samples = {
            player_a: [(252.5, 0.0, 0.0, None, 100),
                       (326.0, 0.0, 0.0, None, 100),
                       (329.4, 0.0, 0.0, None, 100),
                       (331.4, 0.0, 0.0, None, 100)],
            player_b: [(252.5, 4.0, 0.0, None, 100),
                       (326.0, 4.0, 0.0, None, 100),
                       (329.4, 4.0, 0.0, None, 100),
                       (331.4, 20.0, 0.0, None, 100)],
        }
        focus = local_replay._lura_review_focus(
            raw, aura_updates, casts, samples,
            {player_a: "Alpha-Realm", player_b: "Bravo-Realm"},
            {player_a: "p1", player_b: "p2"}, 340.0)

        items = {item["key"]: item for item in focus["items"]}
        self.assertEqual(4, len(items))
        p1 = items["p1_rune_quasar"]["windows"][0]
        self.assertEqual(["Alpha-Realm"], p1["target_names"])
        self.assertEqual(1, p1["observed"]["rune_mismatch_players"])
        intermission = items["intermission_crystal"]["windows"][0]
        self.assertEqual(1, intermission["observed"]["simultaneous_operations"])
        p2 = items["p2_crystal_spread"]["windows"][0]
        self.assertEqual(1, p2["observed"]["formation"]["near_pairs_5_5y"])
        self.assertEqual(0, p2["observed"]["formation"]["near_pairs_3y"])
        self.assertEqual(1, len(items["p3_knockback_spread"]["windows"]))
        self.assertEqual(["p1", "p2", "p3"], [
            space["key"] for space in focus["spaces"]
        ])
        self.assertEqual(231.0, focus["spaces"][1]["start_t"])
        self.assertEqual(330.0, focus["spaces"][2]["start_t"])

    def test_all_log_encounters_are_replayable_without_cctv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            log_path = tmp / "WoWCombatLog-071926_120000.txt"
            player = "Player-1-00000001"
            boss = "Creature-0-0-0-0-99999-00000001"
            log_path.write_text(
                _line("12:00:00.0000", "COMBAT_LOG_VERSION,22,ADVANCED_LOG_ENABLED,1")
                + _line("12:00:01.0000", 'ENCOUNTER_START,9001,"Test Boss",16,2,42')
                + _position_event(
                    "12:00:01.1000", player, "Tester-Realm", "0x511",
                    boss, "Test Boss", player, 10.0, 20.0)
                + _position_event(
                    "12:00:01.2000", boss, "Test Boss", "0x10a48",
                    player, "Tester-Realm", boss, 15.0, 25.0)
                + _line("12:02:01.0000", 'ENCOUNTER_END,9001,"Test Boss",16,2,1,120000')
                + _line("12:02:04.0000", 'ENCOUNTER_START,9001,"Test Boss",16,2,42')
                + _position_event(
                    "12:02:04.1000", player, "Tester-Realm", "0x511",
                    boss, "Test Boss", player, 30.0, 40.0)
                + _position_event(
                    "12:02:04.2000", boss, "Test Boss", "0x10a48",
                    player, "Tester-Realm", boss, 35.0, 45.0)
                + _line("12:04:04.0000", 'ENCOUNTER_END,9001,"Test Boss",16,2,0,120000'),
                encoding="utf-8",
            )
            duplicate_path = tmp / "Copy-WoWCombatLog-071926_120000.txt"
            duplicate_path.write_bytes(log_path.read_bytes())

            with (
                patch.object(
                    local_replay,
                    "_standalone_log_paths",
                    return_value=[log_path, duplicate_path],
                ),
                patch.object(local_replay, "_load_captures", return_value=[]),
                patch("app.cctv_sync.available", return_value=False),
                patch.object(local_replay, "latest_log_path", return_value=log_path),
                patch.object(local_replay, "wow_log_dir", return_value=tmp),
                patch.object(local_replay, "cctv_dir", return_value=tmp),
                patch.object(
                    local_replay,
                    "_lura_sync_index",
                    return_value=local_replay._empty_lura_sync_index(),
                ),
            ):
                listing = local_replay.list_replays()
                self.assertEqual(2, len(listing["rows"]))
                self.assertEqual(2, listing["sources"]["log_only"])
                self.assertTrue(all(row["log_only"] for row in listing["rows"]))
                self.assertEqual({True, False}, {row["result"] for row in listing["rows"]})

                replay_id = next(
                    row["id"] for row in listing["rows"] if row["result"] is True)
                detail = local_replay.replay_detail(replay_id)
                self.assertFalse(detail["video"]["available"])
                self.assertEqual(str(log_path), detail["sources"]["log_file"])
                self.assertEqual([], detail["positions"])

                with patch.object(
                    local_replay,
                    "_stream_frames_window",
                    wraps=local_replay._stream_frames_window,
                ) as stream_frames:
                    frames = local_replay.replay_frames(replay_id)
                    terrain = local_replay.replay_terrain_request(replay_id)
                    self.assertEqual(1, stream_frames.call_count)
                self.assertGreaterEqual(len(frames["frames"]), 1)
                self.assertEqual(
                    {"Tester-Realm", "Test Boss"},
                    {unit["name"] for unit in frames["meta"]["units"]},
                )
                self.assertEqual(0, frames["meta"]["video_offset_s"])
                self.assertEqual(1, frames["counts"]["damage"])

                self.assertEqual(42, terrain["instance_id"])
                self.assertEqual((10.0, 10.0, 20.0, 20.0), terrain["bbox"])

    def test_replay_list_uses_lura_p2_and_other_boss_duration_rules(self) -> None:
        captures = [
            {
                "id": "lura-no-p2",
                "encounter_id": 3183,
                "encounter": "한밤의 도래",
                "duration": 300.0,
                "lura_p2_state": "not_reached",
                "start_local": "2026-07-19 12:05:00",
            },
            {
                "id": "lura-p2",
                "encounter_id": 3183,
                "encounter": "한밤의 도래",
                "duration": 100.0,
                "lura_p2_state": "reached",
                "start_local": "2026-07-19 12:04:00",
            },
            {
                "id": "lura-unknown",
                "encounter_id": 3183,
                "encounter": "한밤의 도래",
                "duration": 10.0,
                "start_local": "2026-07-19 12:03:00",
            },
            {
                "id": "lura-unknown-long",
                "encounter_id": 3183,
                "encounter": "한밤의 도래",
                "duration": 300.0,
                "start_local": "2026-07-19 12:02:30",
            },
            {
                "id": "other-short",
                "encounter_id": 9001,
                "encounter": "Test Boss",
                "duration": 119.999,
                "start_local": "2026-07-19 12:02:00",
            },
            {
                "id": "other-boundary",
                "encounter_id": 9001,
                "encounter": "Test Boss",
                "duration": 120.0,
                "start_local": "2026-07-19 12:01:00",
            },
        ]

        def load_all_captures(cctv_dir_arg=None, limit=80):
            self.assertIsNone(limit)
            return captures

        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            with (
                patch.object(
                    local_replay,
                    "_load_captures",
                    side_effect=load_all_captures,
                ),
                patch.object(local_replay, "_standalone_log_paths", return_value=[]),
                patch.object(
                    local_replay,
                    "_load_log_replay_caps",
                    return_value=[],
                ) as load_log_caps,
                patch.object(local_replay, "latest_log_path", return_value=None),
                patch.object(local_replay, "wow_log_dir", return_value=tmp),
                patch.object(local_replay, "cctv_dir", return_value=tmp),
                patch.object(
                    local_replay,
                    "_lura_sync_index",
                    return_value=local_replay._empty_lura_sync_index(),
                ),
                patch("app.cctv_sync.ensure_mirror", return_value=tmp),
                patch("app.cctv_sync.sync_status", return_value={}),
            ):
                listing = local_replay.list_replays()
                limited = local_replay.list_replays(limit=2)
                all_rows = local_replay.list_replays(limit=None)

        self.assertEqual(3, load_log_caps.call_count)
        self.assertTrue(all(
            item.kwargs == {"limit": None, "paths": []}
            for item in load_log_caps.call_args_list
        ))
        self.assertEqual(
            {"lura-p2", "lura-unknown-long", "other-boundary"},
            {row["id"] for row in listing["rows"]},
        )
        self.assertEqual(
            ["lura-p2", "lura-unknown-long"],
            [row["id"] for row in limited["rows"]],
        )
        self.assertEqual(
            ["lura-p2", "lura-unknown-long", "other-boundary"],
            [row["id"] for row in all_rows["rows"]],
        )

    def test_replay_list_uses_archived_lura_log_phase(self) -> None:
        started = datetime(2026, 7, 19, 12, 0, 0)
        capture = {
            "id": "lura-archived-no-p2",
            "encounter_id": 3183,
            "encounter": "한밤의 도래",
            "duration": 300.0,
            "start_local": "2026-07-19 12:00:00",
            "_start_dt": started,
        }
        archived_encounter = {
            "encounter_id": 3183,
            "lura_p2_state": "not_reached",
            "_start_dt": started,
        }
        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            with (
                patch.object(local_replay, "_load_captures", return_value=[capture]),
                patch.object(local_replay, "_standalone_log_paths", return_value=[]),
                patch.object(local_replay, "_load_log_replay_caps", return_value=[]),
                patch.object(local_replay, "latest_log_path", return_value=None),
                patch.object(local_replay, "wow_log_dir", return_value=tmp),
                patch.object(local_replay, "cctv_dir", return_value=tmp),
                patch.object(
                    local_replay,
                    "_find_frames_encounter",
                    return_value=(tmp / "Archive-WoWCombatLog.txt", archived_encounter),
                ) as find_archived,
                patch.object(
                    local_replay,
                    "_lura_sync_index",
                    return_value=local_replay._empty_lura_sync_index(),
                ),
                patch("app.cctv_sync.ensure_mirror", return_value=tmp),
                patch("app.cctv_sync.sync_status", return_value={}),
            ):
                listing = local_replay.list_replays()

        find_archived.assert_called_once_with(capture)
        self.assertEqual([], listing["rows"])

    def test_lura_p2_requires_success_or_p2_only_spell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            log_path = Path(tmp_raw) / "WoWCombatLog-071926_150000.txt"
            log_path.write_text(
                _line("15:00:00.0000", 'ENCOUNTER_START,3183,"한밤의 도래",16,20,2913')
                + _line(
                    "15:03:45.0000",
                    'SPELL_CAST_START,Vehicle-0-BOSS,"르우라",0x10a48,0x0,'
                    '0000000000000000,nil,0x0,0x0,1282043,"암흑샘 속으로",0x6a',
                )
                + _line("15:05:00.0000", 'ENCOUNTER_END,3183,"한밤의 도래",16,20,0,300000')
                + _line("15:06:00.0000", 'ENCOUNTER_START,3183,"한밤의 도래",16,20,2913')
                + _line(
                    "15:09:51.0000",
                    'SPELL_CAST_SUCCESS,Vehicle-0-BOSS,"르우라",0x10a48,0x0,'
                    '0000000000000000,nil,0x0,0x0,1282043,"암흑샘 속으로",0x6a',
                )
                + _line("15:11:00.0000", 'ENCOUNTER_END,3183,"한밤의 도래",16,20,0,300000')
                + _line("15:12:00.0000", 'ENCOUNTER_START,3183,"한밤의 도래",16,20,2913')
                + _line(
                    "15:15:52.0000",
                    'SPELL_CAST_START,Vehicle-0-BOSS,"르우라",0x10a48,0x0,'
                    '0000000000000000,nil,0x0,0x0,1284528,"활력 주입",0x6a',
                )
                + _line("15:17:00.0000", 'ENCOUNTER_END,3183,"한밤의 도래",16,20,0,300000'),
                encoding="utf-8",
            )

            encounters = local_replay._encounter_offsets(log_path)

        self.assertEqual(
            ["not_reached", "reached", "reached"],
            [enc["lura_p2_state"] for enc in encounters],
        )
        self.assertNotIn("lura_p2_evidence", encounters[0])
        self.assertEqual(1282043, encounters[1]["lura_p2_evidence"]["spell_id"])
        self.assertEqual(1284528, encounters[2]["lura_p2_evidence"]["spell_id"])

    def test_lura_geometry_overrides_and_crystal_holds(self) -> None:
        from app import replay_mechanics
        crit = replay_mechanics.mechanic_profile(1281184, "임계점", 3183, 16).get("geometry") or {}
        self.assertEqual("circle", crit.get("shape"))
        self.assertEqual(5.5, crit.get("radius"))
        self.assertEqual("target", crit.get("anchor"))
        for sid in (1285510, 1279512):
            star = replay_mechanics.mechanic_profile(sid, "별빛파열", 3183, 16).get("geometry") or {}
            self.assertEqual("circle", star.get("shape"), f"sid={sid}")
            self.assertEqual(5.0, star.get("radius"), f"sid={sid}")
            self.assertEqual("estimated", star.get("confidence"), f"sid={sid}")

        holds = local_replay._lura_crystal_holds(
            [(10.0, "SPELL_AURA_APPLIED", 1253031, "Player-1-A", "Player-1-A", 0),
             (25.5, "SPELL_AURA_REMOVED", 1253031, "Player-1-A", "Player-1-A", 0),
             (30.0, "SPELL_AURA_APPLIED", 1253031, "Player-1-B", "Player-1-B", 0),
             (12.0, "SPELL_AURA_APPLIED", 999999, "Player-1-A", "Player-1-A", 0)],
            {"Player-1-A": "p1", "Player-1-B": "p2"}, 40.0)
        self.assertEqual([{"u": "p1", "s": 10.0, "e": 25.5},
                          {"u": "p2", "s": 30.0, "e": 40.0}], holds)

    def test_lura_wipe_chain_separates_root_cause_from_first_death(self) -> None:
        boss = "Creature-0-BOSS"
        g = lambda i: f"Player-1-{i:02d}"  # noqa: E731
        gid = {g(i): f"p{i}" for i in range(1, 21)}
        names = {f"p{i}": f"멤버{i}-아즈샤라-KR" for i in range(1, 21)}
        deaths = [(355.0 + i * 0.1, g(i)) for i in range(1, 15)]   # 14명 연쇄 사망
        aura = (
            [(353.2, "SPELL_AURA_APPLIED", 1249609, g(i), boss, 0)
             for i in (3, 8, 11, 12, 17, 18)]
            + [(354.9, "SPELL_AURA_APPLIED", 1249584, g(12), boss, 0),
               (354.9, "SPELL_AURA_APPLIED", 1249584, g(18), boss, 0),
               (354.5, "SPELL_AURA_APPLIED_DOSE", 1263514, g(1), boss, 4)]
        )
        crystal = [{"u": "p2", "s": 333.0, "e": 355.1}]   # 보유 중 사망(355.2)
        realm = [{"u": f"p{i}", "s": 353.2, "e": 362.0} for i in (3, 8, 11, 12, 17, 18)]
        chain = local_replay._lura_wipe_chain(
            deaths, aura, crystal, realm, gid, names, 362.0)
        self.assertIsNotNone(chain)
        kinds = [s["kind"] for s in chain["steps"]]
        self.assertIn("root", kinds)
        self.assertIn("crystal", kinds)
        root = next(s for s in chain["steps"] if s["kind"] == "root")
        self.assertIn("멤버12", root["text"])
        self.assertIn("멤버18", root["text"])
        self.assertIn("멤버2", chain["warning"])       # 수정특임 = 표면 원인
        self.assertIn("멤버12", chain["warning"])      # 실제 원인 = 문양 실패조
        first = next(s for s in chain["steps"] if s["kind"] == "death")
        self.assertIn("한밤 4중첩", first["text"])

    def test_unit_debuff_segments(self) -> None:
        boss = "Creature-0-0-0-0-99999-1"
        ups = [
            (5.0, "SPELL_AURA_APPLIED", 111, "Player-1-A", boss, 0),
            (8.0, "SPELL_AURA_APPLIED_DOSE", 111, "Player-1-A", boss, 2),
            (9.0, "SPELL_AURA_REFRESH", 111, "Player-1-A", boss, 0),   # 갱신 — 분절 없음
            (11.0, "SPELL_AURA_REMOVED", 111, "Player-1-A", boss, 0),
            (3.0, "SPELL_AURA_APPLIED", 222, "Player-1-A", "Player-1-B", 0),  # 플레이어 소스 제외
            (20.0, "SPELL_AURA_APPLIED", 111, "Player-1-B", boss, 0),  # 미해제 → duration 마감
        ]
        segs = local_replay._unit_debuff_segments(
            ups, {"Player-1-A": "p1", "Player-1-B": "p2"}, 30.0)
        self.assertEqual({"p1": [[5.0, 8.0, 111, 1], [8.0, 11.0, 111, 2]],
                          "p2": [[20.0, 30.0, 111, 1]]}, segs)

    def test_world_marker_windows_from_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            log_path = tmp / "WoWCombatLog-071926_140000.txt"
            log_path.write_text(
                # 풀 시작 전 설치 2개(하나는 풀 전에 제거) + 다른 존 1개 + 풀 중 설치/제거
                _line("13:59:00.0000", "WORLD_MARKER_PLACED,42,3,100.5,-200.25")
                + _line("13:59:10.0000", "WORLD_MARKER_PLACED,42,5,110.0,-210.0")
                + _line("13:59:20.0000", "WORLD_MARKER_REMOVED,5")
                + _line("13:59:30.0000", "WORLD_MARKER_PLACED,99,4,50.0,-50.0")
                + _line("14:00:00.0000", 'ENCOUNTER_START,9001,"Test Boss",16,2,42')
                + _line("14:00:05.0000", "WORLD_MARKER_PLACED,42,0,120.0,-220.0")
                + _line("14:00:10.0000", "WORLD_MARKER_REMOVED,3")
                + _line("14:00:30.0000", 'ENCOUNTER_END,9001,"Test Boss",16,2,1,30000'),
                encoding="utf-8",
            )
            events = local_replay._world_marker_events(log_path)
            self.assertEqual(6, len(events))
            enc = local_replay._encounter_offsets(log_path)[0]
            wins = local_replay._world_marker_windows(
                log_path, enc["_start_dt"], 30.0, 42)
            self.assertEqual([
                {"i": 3, "x": 100.5, "y": -200.25, "s": 0.0, "e": 10.0},
                {"i": 0, "x": 120.0, "y": -220.0, "s": 5.0, "e": 30.0},
            ], wins)

    def test_frames_cache_survives_live_log_growth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            log_path = tmp / "WoWCombatLog-071926_130000.txt"
            player = "Player-1-00000001"
            boss = "Creature-0-0-0-0-99999-00000001"
            log_path.write_text(
                _line("13:00:01.0000", 'ENCOUNTER_START,9001,"Test Boss",16,2,42')
                + _position_event(
                    "13:00:01.1000", player, "Tester-Realm", "0x511",
                    boss, "Test Boss", player, 10.0, 20.0)
                + _position_event(
                    "13:00:01.2000", boss, "Test Boss", "0x10a48",
                    player, "Tester-Realm", boss, 15.0, 25.0)
                + _line("13:02:01.0000", 'ENCOUNTER_END,9001,"Test Boss",16,2,1,120000'),
                encoding="utf-8",
            )
            with (
                patch.object(
                    local_replay,
                    "_standalone_log_paths",
                    return_value=[log_path],
                ),
                patch.object(local_replay, "_load_captures", return_value=[]),
                patch("app.cctv_sync.available", return_value=False),
                patch.object(local_replay, "latest_log_path", return_value=log_path),
                patch.object(local_replay, "wow_log_dir", return_value=tmp),
                patch.object(local_replay, "cctv_dir", return_value=tmp),
                patch.object(
                    local_replay,
                    "_lura_sync_index",
                    return_value=local_replay._empty_lura_sync_index(),
                ),
            ):
                listing = local_replay.list_replays()
                replay_id = listing["rows"][0]["id"]
                local_replay._frames_cache.clear()
                with patch.object(
                    local_replay,
                    "_stream_frames_window",
                    wraps=local_replay._stream_frames_window,
                ) as stream_frames:
                    local_replay.replay_frames(replay_id)
                    # 활성 로그 성장 시뮬레이션 — 완료된 전투 구간은 불변이라 캐시 유지
                    with log_path.open("a", encoding="utf-8") as fh:
                        fh.write(_line("13:02:05.0000", "SPELL_CAST_SUCCESS,junk"))
                    local_replay.replay_frames(replay_id)
                    self.assertEqual(1, stream_frames.call_count)

    def test_wcl_sync_enriches_local_replay_and_hides_analysis_only_pull(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            log_path = tmp / "WoWCombatLog-071926_120000.txt"
            sync_path = tmp / "lura_trials_20260719_sync.json"
            player = "Player-1-00000001"
            boss = "Creature-0-0-0-0-99999-00000001"
            log_path.write_text(
                _line("12:00:00.1000", 'ENCOUNTER_START,3183,"한밤의 도래",16,20,2913')
                + _line("12:00:00.1400", 'ENCOUNTER_END,3183,"한밤의 도래",16,20,0,40')
                + _line("12:00:01.0000", 'ENCOUNTER_START,3183,"한밤의 도래",16,20,2913')
                + _position_event(
                    "12:00:01.1000", player, "Tester-Realm", "0x511",
                    boss, "한밤의 도래", player, 10.0, 20.0)
                + _position_event(
                    "12:00:01.2000", boss, "한밤의 도래", "0x10a48",
                    player, "Tester-Realm", boss, 15.0, 25.0)
                + _line("12:00:03.0000", 'ENCOUNTER_END,3183,"한밤의 도래",16,20,0,2000'),
                encoding="utf-8",
            )
            encounters = local_replay._encounter_offsets(log_path)
            artifact_id = local_replay._log_replay_id(log_path, encounters[0])
            replay_id = local_replay._log_replay_id(log_path, encounters[1])
            common = {
                "kill": False,
                "deaths": 20,
                "unique_dead_players": 20,
                "repeat_deaths": 0,
                "early_deaths": 0,
                "first_death": {
                    "t": 1.5, "player": "Tester", "cause": "Dissonance",
                    "seconds_before_end": 0.5,
                },
                "death_clusters": [{
                    "start_t": 1.5, "end_t": 1.9, "events": 20,
                    "unique_players": 20,
                    "causes": [{"name": "Dissonance", "deaths": 15}],
                }],
                "final_wipe_causes": [{"name": "Dissonance", "deaths": 15}],
                "terminate": {"begun": 36, "interrupted": 36, "completed": 0},
                "bloodlust_casts": 0,
                "item_level": 291.9,
                "raid_wall_dps": 2_000_000,
                "raid_wall_hps": 950_000,
            }
            sync_path.write_text(json.dumps({
                "report": {
                    "code": "CPA42mqBHXMyca86",
                    "url": "https://ko.warcraftlogs.com/reports/CPA42mqBHXMyca86",
                },
                "session": {
                    "pulls": 2, "kills": 0, "best_fight_id": 11,
                    "best_boss_remaining_pct": 41.6, "bloodlust_casts": 0,
                },
                "death_patterns": {"early_cutoff_seconds_before_end": 8},
                "local": {"instant_artifacts": [{"replay_id": artifact_id}]},
                "pulls": [
                    {
                        **common,
                        "pull": 1, "fight_id": 11,
                        "wcl_url": "https://ko.warcraftlogs.com/reports/CPA42mqBHXMyca86#fight=11",
                        "start_kst": "2026-07-19T12:00:01.000+09:00",
                        "duration_s": 1.95, "boss_remaining_pct": 41.6,
                        "last_phase": 3, "source": "local+wcl",
                        "local_replay_id": replay_id, "duration_delta_ms": 50,
                    },
                    {
                        **common,
                        "pull": 2, "fight_id": 26,
                        "wcl_url": "https://ko.warcraftlogs.com/reports/CPA42mqBHXMyca86#fight=26",
                        "start_kst": "2026-07-19T12:05:00.000+09:00",
                        "duration_s": 120.0, "boss_remaining_pct": 49.47,
                        "last_phase": 2, "source": "wcl-only",
                        "local_replay_id": None, "duration_delta_ms": None,
                    },
                ],
            }, ensure_ascii=False), encoding="utf-8")

            local_replay._lura_sync_cached.cache_clear()
            try:
                with (
                    patch.object(local_replay, "_lura_sync_path", return_value=sync_path),
                    patch.object(local_replay, "_standalone_log_paths", return_value=[log_path]),
                    patch.object(local_replay, "_load_captures", return_value=[]),
                patch("app.cctv_sync.available", return_value=False),
                    patch.object(local_replay, "latest_log_path", return_value=log_path),
                    patch.object(local_replay, "wow_log_dir", return_value=tmp),
                    patch.object(local_replay, "cctv_dir", return_value=tmp),
                ):
                    listing = local_replay.list_replays()
                    self.assertEqual(1, len(listing["rows"]))
                    self.assertFalse(any(
                        row.get("analysis_only") for row in listing["rows"]
                    ))
                    self.assertEqual(1, listing["sources"]["artifacts_hidden"])
                    self.assertEqual(1, listing["sources"]["analysis_replay"])
                    self.assertEqual(1, listing["sources"]["wcl_only"])
                    self.assertEqual(1, listing["sources"]["coordinates_hidden"])
                    self.assertEqual(2, listing["sources"]["wcl_session"]["pulls"])

                    local_row = next(
                        row for row in listing["rows"] if not row.get("analysis_only"))
                    self.assertEqual(2.0, local_row["duration"])
                    self.assertEqual(41.6, local_row["boss_percent"])
                    self.assertEqual(11, local_row["analysis"]["fight_id"])
                    self.assertEqual("P3", local_row["analysis"]["phase"])
                    self.assertTrue(local_row["capabilities"]["frames"])

                    wcl_id = "wcl-CPA42mqBHXMyca86-26"
                    detail = local_replay.replay_detail(wcl_id)
                    self.assertTrue(detail["analysis_only"])
                    self.assertFalse(detail["video"]["available"])
                    frames = local_replay.replay_frames(wcl_id)
                    self.assertEqual([], frames["frames"])
                    self.assertEqual("wcl_only", frames["meta"]["unavailable_reason"])
                    self.assertEqual(
                        {"no_positions"},
                        {item["status"] for item in frames["review_focus"]["items"]},
                    )
                    with self.assertRaises(local_replay.ReplayError):
                        local_replay.replay_terrain_request(wcl_id)
            finally:
                local_replay._lura_sync_cached.cache_clear()


if __name__ == "__main__":
    unittest.main()
