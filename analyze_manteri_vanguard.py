"""Build the evidence set for Manteri's Mythic Lightblinded Vanguard review."""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from wcl_v2 import WCLV2
from wcl_v2_data import Q_DAMAGE_TABLE, V2Data


ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = DATA / "manteri_vanguard_99_analysis.json"
ENCOUNTER_ID = 3180
DIFFICULTY = 5

SAMPLES = [
    {
        "key": "manteri",
        "label": "만터리",
        "code": "vx2ymA7WbXnY4f3Z",
        "fight_id": 25,
        "character": "만터리",
        "comparison": "본인 최신 신화 킬",
    },
    {
        "key": "same_raid",
        "label": "민규집영역표시",
        "code": "vx2ymA7WbXnY4f3Z",
        "fight_id": 25,
        "character": "민규집영역표시",
        "comparison": "같은 공대·같은 전투·동일 아이템 레벨",
    },
    {
        "key": "nopi_99",
        "label": "爬山",
        "code": "vY7mH1NRZh4WBDJw",
        "fight_id": 2,
        "character": "爬山",
        "comparison": "유사 전투 길이 무마주 99권 표본",
    },
]

CORE_SPELLS = {
    34026: "살상 명령",
    217200: "날카로운 사격",
    193455: "코브라 사격",
    1264359: "마구잡이 난타",
    19574: "야수의 격노",
    359844: "야생의 부름",
    383781: "알게타르 수수께끼",
}
UTILITY_SPELLS = {
    781: "철수",
    5384: "죽은 척하기",
    109304: "활기",
    186257: "치타의 상",
    186265: "거북의 상",
    264735: "적자생존",
    1234768: "실버문 생명력 물약",
}
POTION_IDS = {1236616, 1236994, 1236998, 1238443, 431932, 453035}
TRINKET_SLOTS = {12, 13}

Q_REPORT_RANKINGS = """
query($code: String!, $fightIDs: [Int]!) {
  reportData { report(code: $code) { rankings(fightIDs: $fightIDs) } }
}
"""

Q_RESOURCE_EVENTS = """
query($code: String!, $start: Float!, $end: Float!, $sid: Int!) {
  reportData {
    report(code: $code) {
      events(
        dataType: Resources
        startTime: $start
        endTime: $end
        sourceID: $sid
      ) { data nextPageTimestamp }
    }
  }
}
"""

Q_DEATH_EVENTS = """
query($code: String!, $start: Float!, $end: Float!) {
  reportData {
    report(code: $code) {
      events(
        dataType: Deaths
        startTime: $start
        endTime: $end
      ) { data }
      masterData { abilities { gameID name } }
    }
  }
}
"""

Q_ZONE = """
query($id: Int!) {
  worldData { zone(id: $id) { partitions { id name default } } }
}
"""

Q_TOP_RANKINGS = """
query($encounterId: Int!, $page: Int!, $partition: Int!) {
  worldData {
    encounter(id: $encounterId) {
      characterRankings(
        metric: dps
        difficulty: 5
        className: "Hunter"
        specName: "BeastMastery"
        page: $page
        partition: $partition
      )
    }
  }
}
"""


def median(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 3) if values else None


def seconds(timestamp: int | float, start: int | float) -> float:
    return round((timestamp - start) / 1000, 3)


def dedupe_times(values: list[float], tolerance: float = 0.5) -> list[float]:
    out: list[float] = []
    for value in sorted(values):
        if not out or value - out[-1] > tolerance:
            out.append(value)
    return out


def spell_names() -> dict[int, str]:
    raw = json.loads((DATA / "spell_db.json").read_text(encoding="utf-8"))
    names = {
        int(spell_id): str(row.get("name_ko") or row.get("name_en") or spell_id)
        for spell_id, row in raw.items()
        if isinstance(row, dict)
    }
    names.update(CORE_SPELLS)
    return names


def talent_names() -> dict[int, str]:
    raw = json.loads((DATA / "talent_trees.json").read_text(encoding="utf-8"))
    tree = raw.get("Hunter/Beast Mastery") or {}
    names: dict[int, str] = {}

    def add_nodes(nodes) -> None:
        for node in nodes or []:
            for option in node.get("options") or []:
                talent_id = option.get("talent_id")
                name = option.get("name")
                if isinstance(talent_id, int) and name:
                    names[talent_id] = str(name)

    add_nodes(tree.get("class"))
    add_nodes(tree.get("spec"))
    for hero in (tree.get("hero") or {}).values():
        add_nodes(hero.get("nodes"))
    return names


def node_names() -> dict[int, str]:
    raw = json.loads((DATA / "talent_trees.json").read_text(encoding="utf-8"))
    tree = raw.get("Hunter/Beast Mastery") or {}
    names: dict[int, str] = {}

    def add_nodes(nodes) -> None:
        for node in nodes or []:
            node_id = node.get("id")
            option_names = [
                str(option["name"])
                for option in node.get("options") or []
                if option.get("name")
            ]
            if isinstance(node_id, int) and option_names:
                names[node_id] = " / ".join(option_names)

    add_nodes(tree.get("class"))
    add_nodes(tree.get("spec"))
    for hero in (tree.get("hero") or {}).values():
        add_nodes(hero.get("nodes"))
    return names


def report_character_rank(cli: WCLV2, code: str, fight_id: int,
                          character: str) -> dict:
    data = cli.query(Q_REPORT_RANKINGS, {
        "code": code,
        "fightIDs": [fight_id],
    })
    rankings = (((data.get("reportData") or {}).get("report") or {})
                .get("rankings") or {})
    fights = rankings.get("data") or []
    fight = next((row for row in fights if row.get("fightID") == fight_id), {})
    roles = fight.get("roles") or {}
    for role in roles.values():
        for row in role.get("characters") or []:
            if row.get("name") == character:
                return {
                    "dps": round(float(row.get("amount") or 0), 3),
                    "rank_percent": row.get("rankPercent"),
                    "bracket_percent": row.get("bracketPercent"),
                    "world_rank": row.get("rank"),
                    "best_rank": row.get("best"),
                    "total_parses": row.get("totalParses"),
                    "item_level": row.get("bracketData"),
                    "fight_deaths": fight.get("deaths"),
                }
    return {}


def current_rankings(cli: WCLV2) -> dict:
    zone = cli.query(Q_ZONE, {"id": 46})["worldData"]["zone"]
    parts = zone.get("partitions") or []
    default = next((row for row in parts if row.get("default")), None)
    partition = int((default or {"id": 3})["id"])
    data = cli.query(Q_TOP_RANKINGS, {
        "encounterId": ENCOUNTER_ID,
        "page": 1,
        "partition": partition,
    })
    obj = (((data.get("worldData") or {}).get("encounter") or {})
           .get("characterRankings") or {})
    rows = obj.get("rankings") or []
    compact = []
    for rank, row in enumerate(rows, 1):
        report = row.get("report") or {}
        compact.append({
            "rank": rank,
            "character": row.get("name"),
            "dps": round(float(row.get("amount") or row.get("total") or 0), 3),
            "item_level": row.get("bracketData"),
            "duration_s": round(float(row.get("duration") or 0) / 1000, 3),
            "report_code": report.get("code"),
            "fight_id": report.get("fightID"),
        })
    return {
        "partition": partition,
        "partition_name": (default or {}).get("name"),
        "top_100": compact,
    }


def damage_summary(cli: WCLV2, sample: dict, source_id: int,
                   start: float, end: float) -> dict:
    data = cli.query(Q_DAMAGE_TABLE, {
        "code": sample["code"],
        "start": float(start),
        "end": float(end),
        "sid": int(source_id),
    })
    table = (((data.get("reportData") or {}).get("report") or {})
             .get("table") or {})
    inner = table.get("data", table) if isinstance(table, dict) else {}
    entries = inner.get("entries") or []
    targets: defaultdict[str, int] = defaultdict(int)
    spells = []
    for entry in entries:
        total = int(entry.get("total") or 0)
        for target in entry.get("targets") or []:
            targets[str(target.get("name") or "?")] += int(target.get("total") or 0)
        hits = int(entry.get("hitCount") or 0) + int(entry.get("tickCount") or 0)
        crits = int(entry.get("critHitCount") or 0) + int(entry.get("critTickCount") or 0)
        spells.append({
            "id": entry.get("guid"),
            "name": entry.get("name") or "?",
            "total": total,
            "uses": entry.get("uses"),
            "hits": hits,
            "crits": crits,
            "crit_pct": round(100 * crits / hits, 1) if hits else None,
            "targets": {
                str(target.get("name") or "?"): int(target.get("total") or 0)
                for target in entry.get("targets") or []
            },
        })
    spells.sort(key=lambda row: row["total"], reverse=True)
    return {
        "total": sum(row["total"] for row in spells),
        "targets": dict(sorted(targets.items(), key=lambda item: -item[1])),
        "spells": spells,
    }


def resource_summary(cli: WCLV2, sample: dict, source_id: int,
                     start: float, end: float) -> dict:
    data = cli.query(Q_RESOURCE_EVENTS, {
        "code": sample["code"],
        "start": float(start),
        "end": float(end),
        "sid": int(source_id),
    })
    events = ((((data.get("reportData") or {}).get("report") or {})
               .get("events") or {}).get("data") or [])
    focus = [
        row for row in events
        if row.get("resourceChangeType") == 2 and row.get("targetID") == source_id
    ]
    generated = sum(max(0, int(row.get("resourceChange") or 0)) for row in focus)
    wasted = sum(max(0, int(row.get("waste") or 0)) for row in focus)
    by_spell: defaultdict[int, dict[str, int]] = defaultdict(
        lambda: {"generated": 0, "wasted": 0, "events": 0})
    for row in focus:
        spell_id = int(row.get("abilityGameID") or 0)
        by_spell[spell_id]["generated"] += max(0, int(row.get("resourceChange") or 0))
        by_spell[spell_id]["wasted"] += max(0, int(row.get("waste") or 0))
        by_spell[spell_id]["events"] += 1
    return {
        "generated": generated,
        "wasted": wasted,
        "waste_pct": round(100 * wasted / generated, 1) if generated else None,
        "by_spell": dict(by_spell),
    }


def death_summary(cli: WCLV2, sample: dict, source_id: int,
                  start: float, end: float) -> list[dict]:
    data = cli.query(Q_DEATH_EVENTS, {
        "code": sample["code"],
        "start": float(start),
        "end": float(end),
    })
    report = ((data.get("reportData") or {}).get("report") or {})
    abilities = {
        int(row.get("gameID") or 0): str(row.get("name") or row.get("gameID"))
        for row in ((report.get("masterData") or {}).get("abilities") or [])
    }
    events = ((report.get("events") or {}).get("data") or [])
    out = []
    for row in events:
        if int(row.get("targetID") or 0) != source_id:
            continue
        ability_id = int(row.get("killingAbilityGameID") or 0)
        out.append({
            "time_s": seconds(row.get("timestamp") or start, start),
            "ability_id": ability_id,
            "ability": abilities.get(ability_id, str(ability_id)),
        })
    return out


def event_summary(events: dict, start: float, end: float,
                  names: dict[int, str]) -> dict:
    duration_s = (end - start) / 1000
    casts = sorted(
        (int(row[0]), int(row[1]))
        for row in events.get("casts") or []
        if len(row) >= 3 and row[2] == "cast"
    )
    counts = Counter(spell_id for _, spell_id in casts)
    times = {
        spell_id: [seconds(ts, start) for ts, sid in casts if sid == spell_id]
        for spell_id in set(CORE_SPELLS) | set(UTILITY_SPELLS) | POTION_IDS
    }
    cast_timestamps = [timestamp for timestamp, _ in casts]
    points = [int(start)] + cast_timestamps + [int(end)]
    long_gap_windows = [
        {
            "start_s": seconds(left, start),
            "end_s": seconds(right, start),
            "length_s": round((right - left) / 1000, 3),
        }
        for left, right in zip(points, points[1:])
        if (right - left) / 1000 >= 3
    ]
    bw = times[19574]
    kill_command = times[34026]
    wild_thrash = times[1264359]
    bw_gaps = [round(b - a, 3) for a, b in zip(bw, bw[1:])]
    wt_gaps = [round(b - a, 3) for a, b in zip(wild_thrash, wild_thrash[1:])]
    kc_after_bw = sum(
        1 for cast_time in bw
        if any(0 <= kc_time - cast_time <= 1.6 for kc_time in kill_command)
    )
    bw_near_wt = sum(
        1 for cast_time in bw
        if any(abs(wt_time - cast_time) <= 3 for wt_time in wild_thrash)
    )
    potion_from_casts = [
        seconds(ts, start) for ts, spell_id in casts if spell_id in POTION_IDS
    ]
    potion_from_buffs = [
        seconds(row[0], start)
        for row in events.get("buffs") or []
        if len(row) >= 3 and int(row[1]) in POTION_IDS and row[2] == "applybuff"
    ]
    core = {}
    for spell_id, label in CORE_SPELLS.items():
        core[label] = {
            "id": spell_id,
            "count": counts.get(spell_id, 0),
            "per_min": round(counts.get(spell_id, 0) / (duration_s / 60), 2),
            "times_s": times.get(spell_id) or [],
        }
    utility = {
        label: {
            "id": spell_id,
            "count": counts.get(spell_id, 0),
            "times_s": times.get(spell_id) or [],
        }
        for spell_id, label in UTILITY_SPELLS.items()
    }
    all_counts = [
        {
            "id": spell_id,
            "name": names.get(spell_id, str(spell_id)),
            "count": count,
        }
        for spell_id, count in counts.most_common()
    ]
    return {
        "total_casts": len(casts),
        "casts_per_min": round(len(casts) / (duration_s / 60), 2),
        "downtime_3s_total": round(
            sum(row["length_s"] for row in long_gap_windows), 3),
        "downtime_3s_count": len(long_gap_windows),
        "downtime_3s_gaps": [row["length_s"] for row in long_gap_windows],
        "downtime_3s_windows": long_gap_windows,
        "core": core,
        "utility": utility,
        "all_counts": all_counts,
        "bw_gap_median": median(bw_gaps),
        "bw_gap_max": max(bw_gaps, default=None),
        "bw_kc_within_1_6s": kc_after_bw,
        "bw_near_wild_thrash_within_3s": bw_near_wt,
        "wild_thrash_gap_median": median(wt_gaps),
        "wild_thrash_gap_max": max(wt_gaps, default=None),
        "wild_thrash_gaps_over_10s": sum(gap > 10 for gap in wt_gaps),
        "potion_times_s": dedupe_times(potion_from_casts + potion_from_buffs),
    }


def analyze_sample(v2: V2Data, cli: WCLV2, sample: dict,
                   names: dict[int, str]) -> dict:
    meta = v2.report_meta(sample["code"]) or {}
    fight = next(
        row for row in meta.get("fights") or []
        if row.get("id") == sample["fight_id"]
    )
    start = float(fight["startTime"])
    end = float(fight["endTime"])
    player = v2.player_fight(
        sample["code"], sample["fight_id"], sample["character"]
    ) or {}
    source_id = int(player["sourceID"])
    events = v2.events_for(
        sample["code"], sample["fight_id"], sample["character"]
    ) or {"casts": [], "buffs": []}
    external_pi = v2.external_pi_buffs(
        sample["code"], sample["fight_id"], sample["character"]
    ) or []
    deaths = death_summary(cli, sample, source_id, start, end)
    rank = report_character_rank(
        cli, sample["code"], sample["fight_id"], sample["character"]
    )
    trinkets = [
        {"id": row.get("id"), "name": row.get("name"), "ilvl": row.get("ilvl")}
        for row in player.get("gear") or []
        if row.get("slot") in TRINKET_SLOTS
    ]
    return {
        **sample,
        "url": (f"https://www.warcraftlogs.com/reports/{sample['code']}"
                f"#fight={sample['fight_id']}&type=damage-done"),
        "duration_s": round((end - start) / 1000, 3),
        "rank": rank,
        "stats": player.get("stats") or {},
        "trinkets": trinkets,
        "talents": player.get("talents") or [],
        "talent_points": player.get("talent_points") or {},
        "nodes": player.get("nodes") or [],
        "external_pi_events": len(external_pi),
        "deaths": deaths,
        "events": event_summary(events, start, end, names),
        "resources": resource_summary(cli, sample, source_id, start, end),
        "damage": damage_summary(cli, sample, source_id, start, end),
    }


def talent_differences(samples: dict[str, dict], names: dict[int, str]) -> dict:
    own = set(samples["manteri"]["talents"])
    out = {}
    for key in ("same_raid", "nopi_99"):
        other = set(samples[key]["talents"])
        out[key] = {
            "manteri_only": [names.get(talent_id, str(talent_id)) for talent_id in sorted(own - other)],
            "other_only": [names.get(talent_id, str(talent_id)) for talent_id in sorted(other - own)],
        }
    return out


def node_differences(samples: dict[str, dict], names: dict[int, str]) -> dict:
    own = set(samples["manteri"]["nodes"])
    out = {}
    for key in ("same_raid", "nopi_99"):
        other = set(samples[key]["nodes"])
        out[key] = {
            "manteri_only": [
                names.get(node_id, str(node_id)) for node_id in sorted(own - other)
            ],
            "other_only": [
                names.get(node_id, str(node_id)) for node_id in sorted(other - own)
            ],
        }
    return out


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cli = WCLV2()
    v2 = V2Data(DATA / "_tmp_vanguard")
    names = spell_names()
    talent_map = talent_names()
    node_map = node_names()
    samples: dict[str, dict] = {}
    for sample in SAMPLES:
        print(f"fetch {sample['label']}...", flush=True)
        samples[sample["key"]] = analyze_sample(v2, cli, sample, names)
    out = {
        "meta": {
            "encounter_id": ENCOUNTER_ID,
            "encounter": "Lightblinded Vanguard",
            "character": "만터리-아즈샤라",
            "difficulty": "Mythic",
            "generated": "2026-07-17",
        },
        "current_rankings": current_rankings(cli),
        "samples": samples,
        "talent_differences": talent_differences(samples, talent_map),
        "node_differences": node_differences(samples, node_map),
        "rate": cli.points_left(),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {OUT}")
    for row in samples.values():
        rank = row["rank"]
        core = row["events"]["core"]
        print(
            f"{row['label']}: {rank.get('dps', 0):,.0f} DPS / "
            f"{rank.get('rank_percent')}점 / {row['duration_s']}s / "
            f"KC {core['살상 명령']['count']} / WT {core['마구잡이 난타']['count']} / "
            f"BW {core['야수의 격노']['count']} / focus waste "
            f"{row['resources']['waste_pct']}%",
            flush=True,
        )


if __name__ == "__main__":
    main()
