"""Synchronize the 2026-07-19 Mythic L'ura pulls with Warcraft Logs.

Outputs the sidecar data consumed by the replay UI.  The local combat log is
authoritative for replay IDs; WCL supplies progress, phases, deaths, and the
pulls recorded after the local file ended.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.local_replay import _encounter_offsets, _log_replay_id
from wcl_v2 import WCLV2


ROOT = Path(__file__).parent
DATA = ROOT / "data"
REPORT_CODE = "CPA42mqBHXMyca86"
ENCOUNTER_ID = 3183
DIFFICULTY = 5
TARGET_DATE = "2026-07-19"
LOCAL_LOG = Path(
    r"C:\Program Files (x86)\World of Warcraft\_retail_\Logs\WoWCombatLog-071926_205807.txt"
)
OUT_JSON = DATA / "lura_trials_20260719_sync.json"
OUT_CSV = DATA / "lura_trials_20260719_pulls.csv"
KST = timezone(timedelta(hours=9))
EARLY_DEATH_CUTOFF_MS = 8_000
DEATH_CLUSTER_GAP_S = 2.1

BLOODLUST_IDS = (
    2825, 32182, 80353, 264667, 272678, 390386, 466904,
    178207, 230935, 256740, 309658, 444257,
)

Q_REPORT = """
query($code: String!) {
  reportData {
    report(code: $code) {
      title startTime endTime
      owner { name }
      zone { name }
      fights(killType: Encounters) {
        id startTime endTime encounterID difficulty kill name
        bossPercentage lastPhase friendlyPlayers
      }
      masterData(translate: true) {
        actors(type: "Player") { id name type subType }
      }
    }
  }
}
"""

Q_DEATHS = """
query($code: String!, $start: Float!, $end: Float!) {
  reportData {
    report(code: $code) {
      events(
        dataType: Deaths
        startTime: $start
        endTime: $end
        hostilityType: Friendlies
      ) { data nextPageTimestamp }
      masterData(translate: true) {
        abilities { gameID name }
        actors(type: "Player") { id name }
      }
    }
  }
}
"""


def _table_alias_query(fights: list[dict[str, Any]], data_type: str) -> str:
    fields = []
    for fight in fights:
        fields.append(
            f"f{fight['id']}:table(dataType:{data_type},"
            f"startTime:{float(fight['startTime']):.3f},"
            f"endTime:{float(fight['endTime']):.3f})"
        )
    return (
        "query($code:String!){reportData{report(code:$code){"
        + " ".join(fields)
        + "}}}"
    )


def _bloodlust_query(start: float, end: float) -> str:
    fields = []
    for spell_id in BLOODLUST_IDS:
        fields.append(
            f"s{spell_id}:events(dataType:Casts,startTime:{start:.3f},"
            f"endTime:{end:.3f},abilityID:{spell_id},"
            "hostilityType:Friendlies){data nextPageTimestamp}"
        )
    return (
        "query($code:String!){reportData{report(code:$code){"
        + " ".join(fields)
        + "}}}"
    )


def _walk_interrupt_rows(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "spellsBegun" in value:
            out.append(value)
        for child in value.values():
            out.extend(_walk_interrupt_rows(child))
    elif isinstance(value, list):
        for child in value:
            out.extend(_walk_interrupt_rows(child))
    return out


def _death_clusters(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group consecutive deaths into compact collapse windows for replay UI."""
    groups: list[list[dict[str, Any]]] = []
    for event in events:
        if not groups or event["t"] - groups[-1][-1]["t"] > DEATH_CLUSTER_GAP_S:
            groups.append([event])
        else:
            groups[-1].append(event)

    out = []
    for group in groups:
        causes = Counter(str(event.get("cause") or "") for event in group)
        players = {int(event.get("target_id") or 0) for event in group}
        out.append({
            "start_t": group[0]["t"],
            "end_t": group[-1]["t"],
            "events": len(group),
            "unique_players": len(players - {0}),
            "causes": [
                {"name": name, "deaths": count}
                for name, count in causes.most_common()
                if name
            ],
        })
    return out


def _compact_summary(table: dict[str, Any], duration_s: float) -> dict[str, Any]:
    data = table.get("data") if isinstance(table, dict) else {}
    data = data if isinstance(data, dict) else {}
    damage = data.get("damageDone") or []
    healing = data.get("healingDone") or []
    raid_damage = sum(float(row.get("total") or 0) for row in damage)
    raid_healing = sum(float(row.get("total") or 0) for row in healing)
    players = [row for row in damage if row.get("type") != "Pet"]
    top = sorted(
        (
            {
                "name": row.get("name") or "",
                "wall_dps": round(float(row.get("total") or 0) / duration_s, 1),
            }
            for row in players
        ),
        key=lambda row: row["wall_dps"],
        reverse=True,
    )[:3]
    roster = []
    for row in data.get("composition") or []:
        specs = row.get("specs") or []
        roster.append({
            "id": row.get("id"),
            "name": row.get("name") or "",
            "class": row.get("type") or "",
            "spec": (specs[0].get("spec") if specs else "") or "",
            "role": (specs[0].get("role") if specs else "") or "",
        })
    return {
        "item_level": round(float(data.get("itemLevel") or 0), 2),
        "raid_damage": round(raid_damage),
        "raid_wall_dps": round(raid_damage / duration_s, 1),
        "raid_healing": round(raid_healing),
        "raid_wall_hps": round(raid_healing / duration_s, 1),
        "top_wall_dps": top,
        "roster": roster,
    }


def _local_attempts() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    attempts = []
    artifacts = []
    for ordinal, encounter in enumerate(_encounter_offsets(LOCAL_LOG), 1):
        row = {
            "ordinal": ordinal,
            "start": encounter["_start_dt"],
            "duration_s": round(float(encounter.get("duration_s") or 0), 3),
            "replay_id": _log_replay_id(LOCAL_LOG, encounter),
        }
        (artifacts if row["duration_s"] < 1 else attempts).append(row)
    return attempts, artifacts


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if not LOCAL_LOG.exists():
        raise SystemExit(f"local log not found: {LOCAL_LOG}")

    cli = WCLV2()
    report = cli.query(Q_REPORT, {"code": REPORT_CODE})["reportData"]["report"]
    report_start_ms = float(report["startTime"])
    fights = [
        fight for fight in report.get("fights") or []
        if fight.get("encounterID") == ENCOUNTER_ID
        and fight.get("difficulty") == DIFFICULTY
        and datetime.fromtimestamp(
            (report_start_ms + float(fight["startTime"])) / 1000, KST
        ).date().isoformat() == TARGET_DATE
    ]
    fights.sort(key=lambda row: row["startTime"])
    if not fights:
        raise SystemExit("no Mythic L'ura fights in report")

    local_attempts, local_artifacts = _local_attempts()

    deaths_payload = cli.query(Q_DEATHS, {
        "code": REPORT_CODE,
        "start": float(fights[0]["startTime"]),
        "end": float(fights[-1]["endTime"]),
    })["reportData"]["report"]
    if (deaths_payload.get("events") or {}).get("nextPageTimestamp"):
        raise RuntimeError("death events unexpectedly paginated")
    master = deaths_payload.get("masterData") or {}
    actor_names = {
        int(row["id"]): str(row["name"])
        for row in master.get("actors") or []
        if isinstance(row.get("id"), int) and row.get("name")
    }
    ability_names = {
        int(row["gameID"]): str(row["name"])
        for row in master.get("abilities") or []
        if isinstance(row.get("gameID"), int) and row.get("name")
    }
    deaths_by_fight: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in (deaths_payload.get("events") or {}).get("data") or []:
        fight_id = event.get("fight")
        if isinstance(fight_id, int):
            deaths_by_fight[fight_id].append(event)

    summary_payload = cli.query(
        _table_alias_query(fights, "Summary"), {"code": REPORT_CODE}
    )["reportData"]["report"]
    interrupt_payload = cli.query(
        _table_alias_query(fights, "Interrupts"), {"code": REPORT_CODE}
    )["reportData"]["report"]
    bloodlust_payload = cli.query(
        _bloodlust_query(float(fights[0]["startTime"]), float(fights[-1]["endTime"])),
        {"code": REPORT_CODE},
    )["reportData"]["report"]

    bloodlust_events = []
    for spell_id in BLOODLUST_IDS:
        for event in (bloodlust_payload.get(f"s{spell_id}") or {}).get("data") or []:
            bloodlust_events.append({
                "spell_id": spell_id,
                "fight_id": event.get("fight"),
                "timestamp": event.get("timestamp"),
                "source_id": event.get("sourceID"),
            })

    early_causes: Counter[str] = Counter()
    first_causes: Counter[str] = Counter()
    early_players: Counter[str] = Counter()
    pulls = []
    used_local: set[int] = set()

    for pull_number, fight in enumerate(fights, 1):
        fight_id = int(fight["id"])
        duration_s = round(
            (float(fight["endTime"]) - float(fight["startTime"])) / 1000, 3
        )
        start_kst = datetime.fromtimestamp(
            (report_start_ms + float(fight["startTime"])) / 1000, KST
        )
        local = None
        for candidate in local_attempts:
            if candidate["ordinal"] in used_local:
                continue
            start_delta = abs(
                (candidate["start"] - start_kst.replace(tzinfo=None)).total_seconds()
            )
            duration_delta = abs(candidate["duration_s"] - duration_s)
            if start_delta <= 0.2 and duration_delta <= 0.2:
                local = candidate
                used_local.add(candidate["ordinal"])
                break

        events = sorted(
            deaths_by_fight.get(fight_id, []), key=lambda row: row.get("timestamp") or 0
        )
        death_details = []
        for event in events:
            target_id = int(event.get("targetID") or 0)
            ability_id = int(event.get("killingAbilityGameID") or 0)
            death_details.append({
                "t": round(
                    (float(event["timestamp"]) - float(fight["startTime"])) / 1000,
                    3,
                ),
                "target_id": target_id,
                "player": actor_names.get(target_id, str(target_id)),
                "ability_id": ability_id,
                "cause": ability_names.get(ability_id, str(ability_id)),
            })
        early = [
            row for row in events
            if float(fight["endTime"]) - float(row.get("timestamp") or 0)
            > EARLY_DEATH_CUTOFF_MS
        ]
        for event in early:
            cause = ability_names.get(
                int(event.get("killingAbilityGameID") or 0),
                str(event.get("killingAbilityGameID") or 0),
            )
            player = actor_names.get(
                int(event.get("targetID") or 0), str(event.get("targetID") or 0)
            )
            early_causes[cause] += 1
            early_players[player] += 1

        first_death = None
        if events:
            event = events[0]
            cause = ability_names.get(
                int(event.get("killingAbilityGameID") or 0),
                str(event.get("killingAbilityGameID") or 0),
            )
            first_causes[cause] += 1
            first_death = {
                "t": round((float(event["timestamp"]) - float(fight["startTime"])) / 1000, 2),
                "player": actor_names.get(
                    int(event.get("targetID") or 0), str(event.get("targetID") or 0)
                ),
                "cause": cause,
                "seconds_before_end": round(
                    (float(fight["endTime"]) - float(event["timestamp"])) / 1000, 2
                ),
            }

        final_causes: Counter[str] = Counter()
        for event in events:
            if float(fight["endTime"]) - float(event.get("timestamp") or 0) <= EARLY_DEATH_CUTOFF_MS:
                final_causes[ability_names.get(
                    int(event.get("killingAbilityGameID") or 0),
                    str(event.get("killingAbilityGameID") or 0),
                )] += 1

        interrupt_table = interrupt_payload.get(f"f{fight_id}") or {}
        interrupt_rows = _walk_interrupt_rows(interrupt_table)
        terminate = next(
            (row for row in interrupt_rows if row.get("name") == "Terminate"), {}
        )
        summary = _compact_summary(
            summary_payload.get(f"f{fight_id}") or {}, duration_s
        )
        pulls.append({
            "pull": pull_number,
            "fight_id": fight_id,
            "wcl_url": (
                f"https://ko.warcraftlogs.com/reports/{REPORT_CODE}#fight={fight_id}"
            ),
            "start_kst": start_kst.isoformat(timespec="milliseconds"),
            "duration_s": duration_s,
            "boss_remaining_pct": round(float(fight.get("bossPercentage") or 0), 2),
            "last_phase": int(fight.get("lastPhase") or 0),
            "kill": bool(fight.get("kill")),
            "local_ordinal": local["ordinal"] if local else None,
            "local_replay_id": local["replay_id"] if local else None,
            "duration_delta_ms": (
                round((local["duration_s"] - duration_s) * 1000) if local else None
            ),
            "source": "local+wcl" if local else "wcl-only",
            "deaths": len(events),
            "unique_dead_players": len({
                int(event.get("targetID") or 0) for event in events
            } - {0}),
            "repeat_deaths": max(0, len(events) - len({
                int(event.get("targetID") or 0) for event in events
            } - {0})),
            "early_deaths": len(early),
            "first_death": first_death,
            "death_events": death_details,
            "death_clusters": _death_clusters(death_details),
            "final_wipe_causes": [
                {"name": name, "deaths": count}
                for name, count in final_causes.most_common(3)
            ],
            "terminate": {
                "begun": int(terminate.get("spellsBegun") or 0),
                "interrupted": int(terminate.get("spellsInterrupted") or 0),
                "completed": int(terminate.get("spellsCompleted") or 0),
            },
            "bloodlust_casts": sum(
                event.get("fight_id") == fight_id for event in bloodlust_events
            ),
            **summary,
        })

    boss_values = [row["boss_remaining_pct"] for row in pulls]
    duration_values = [row["duration_s"] for row in pulls]
    phase_counts = Counter(row["last_phase"] for row in pulls)
    out = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "date": TARGET_DATE,
        "report": {
            "code": REPORT_CODE,
            "url": f"https://ko.warcraftlogs.com/reports/{REPORT_CODE}",
            "title": report.get("title") or "",
            "owner": (report.get("owner") or {}).get("name") or "",
            "zone": (report.get("zone") or {}).get("name") or "",
            "start_kst": datetime.fromtimestamp(report_start_ms / 1000, KST).isoformat(
                timespec="milliseconds"
            ),
            "report_end_kst": datetime.fromtimestamp(
                float(report["endTime"]) / 1000, KST
            ).isoformat(timespec="milliseconds"),
            "scope_end_kst": datetime.fromtimestamp(
                (report_start_ms + float(fights[-1]["endTime"])) / 1000, KST
            ).isoformat(timespec="milliseconds"),
        },
        "local": {
            "path": str(LOCAL_LOG),
            "encounters": len(local_attempts) + len(local_artifacts),
            "valid_attempts": len(local_attempts),
            "instant_artifacts": [
                {
                    "ordinal": row["ordinal"],
                    "start": row["start"].isoformat(timespec="milliseconds"),
                    "duration_s": row["duration_s"],
                    "replay_id": row["replay_id"],
                }
                for row in local_artifacts
            ],
        },
        "sync": {
            "wcl_fights": len(fights),
            "matched_local_replays": sum(row["source"] == "local+wcl" for row in pulls),
            "wcl_only_fights": [
                row["fight_id"] for row in pulls if row["source"] == "wcl-only"
            ],
            "unmatched_local_ordinals": [
                row["ordinal"] for row in local_attempts
                if row["ordinal"] not in used_local
            ],
        },
        "session": {
            "pulls": len(pulls),
            "kills": sum(row["kill"] for row in pulls),
            "best_fight_id": min(pulls, key=lambda row: row["boss_remaining_pct"])["fight_id"],
            "best_boss_remaining_pct": min(boss_values),
            "median_boss_remaining_pct": round(statistics.median(boss_values), 2),
            "mean_boss_remaining_pct": round(statistics.mean(boss_values), 2),
            "median_duration_s": round(statistics.median(duration_values), 3),
            "mean_duration_s": round(statistics.mean(duration_values), 3),
            "phase_counts": {f"P{phase}": count for phase, count in sorted(phase_counts.items())},
            "boss_at_or_below_50_pct": sum(value <= 50 for value in boss_values),
            "boss_at_or_below_45_pct": sum(value <= 45 for value in boss_values),
            "boss_at_or_below_40_pct": sum(value <= 40 for value in boss_values),
            "bloodlust_casts": len(bloodlust_events),
        },
        "death_patterns": {
            "early_cutoff_seconds_before_end": EARLY_DEATH_CUTOFF_MS / 1000,
            "early_causes": [
                {"name": name, "deaths": count}
                for name, count in early_causes.most_common()
            ],
            "first_death_causes": [
                {"name": name, "pulls": count}
                for name, count in first_causes.most_common()
            ],
            "early_death_players": [
                {"name": name, "deaths": count}
                for name, count in early_players.most_common()
            ],
        },
        "bloodlust_events": bloodlust_events,
        "pulls": pulls,
    }

    DATA.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fields = [
        "pull", "fight_id", "start_kst", "duration_s", "boss_remaining_pct",
        "last_phase", "source", "local_ordinal", "local_replay_id",
        "duration_delta_ms", "deaths", "early_deaths", "first_death_s",
        "first_death_player", "first_death_cause", "first_death_before_end_s",
        "wipe_cause", "terminate_begun", "terminate_interrupted",
        "terminate_completed", "raid_wall_dps", "raid_wall_hps", "item_level",
        "wcl_url",
    ]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in pulls:
            first = row.get("first_death") or {}
            wipe = row.get("final_wipe_causes") or []
            writer.writerow({
                "pull": row["pull"],
                "fight_id": row["fight_id"],
                "start_kst": row["start_kst"],
                "duration_s": row["duration_s"],
                "boss_remaining_pct": row["boss_remaining_pct"],
                "last_phase": row["last_phase"],
                "source": row["source"],
                "local_ordinal": row["local_ordinal"],
                "local_replay_id": row["local_replay_id"],
                "duration_delta_ms": row["duration_delta_ms"],
                "deaths": row["deaths"],
                "early_deaths": row["early_deaths"],
                "first_death_s": first.get("t"),
                "first_death_player": first.get("player"),
                "first_death_cause": first.get("cause"),
                "first_death_before_end_s": first.get("seconds_before_end"),
                "wipe_cause": wipe[0]["name"] if wipe else "",
                "terminate_begun": row["terminate"]["begun"],
                "terminate_interrupted": row["terminate"]["interrupted"],
                "terminate_completed": row["terminate"]["completed"],
                "raid_wall_dps": row["raid_wall_dps"],
                "raid_wall_hps": row["raid_wall_hps"],
                "item_level": row["item_level"],
                "wcl_url": row["wcl_url"],
            })

    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_CSV}")
    print(
        f"sync: WCL={len(fights)} local={len(local_attempts)} "
        f"matched={out['sync']['matched_local_replays']} "
        f"WCL-only={out['sync']['wcl_only_fights']}"
    )


if __name__ == "__main__":
    main()
