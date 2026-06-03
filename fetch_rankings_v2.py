"""V2 GraphQL 로 zone 46 신화 rankings 재패치 — 스펙별 필터.

V1 의 "전체 ranking 받아서 클라이언트에서 스펙별 버킷팅" 방식은 V2 에서도
가능하지만 비효율 (페이지 80장 긁어도 비주류 스펙은 100명 못 채움).

V2 는 className+specName 필터 지원 → (보스, 클래스, 스펙) 별로 직접 top100
요청. 콜 수 ↓, 데이터 정확도 ↑.

호환성:
  - V2 응답의 class/spec 은 CamelCase ("DemonHunter", "BeastMastery")
  - 기존 enrich/GUI 는 V1 의 space 분리 ("Demon Hunter", "Beast Mastery")
  - 출력 CSV 에는 **V1 양식으로 normalize 해서 저장** → 기존 파이프라인 호환

출력: data/rankings_zone46_mythic_dps_top100.csv (V1 과 동일 스키마)
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from wcl_v2 import WCLV2, WCLV2Error

ZONE_ID = 46
DEFAULT_DIFFICULTY = 5  # 5=Mythic, 4=Heroic, 3=Normal
DIFF_LABEL = {3: "normal", 4: "heroic", 5: "mythic"}
METRIC = "dps"  # rdps 는 V2 도 현재 internal error
TOP_N = 100
MAX_PAGES_PER_SPEC = 3  # 100명 채우려면 보통 1~2페이지면 충분 (스펙별 필터링)

OUT_DIR = Path(__file__).parent / "data"
OUT_DIR.mkdir(exist_ok=True)

# 13 클래스 × DPS 전문화. V2 의 CamelCase 이름.
# (cls_v2, spec_v2, cls_v1, spec_v1)
TARGETS: list[tuple[str, str, str, str]] = [
    ("DeathKnight", "Frost",         "Death Knight", "Frost"),
    ("DeathKnight", "Unholy",        "Death Knight", "Unholy"),
    ("DemonHunter", "Devourer",      "Demon Hunter", "Devourer"),
    ("DemonHunter", "Havoc",         "Demon Hunter", "Havoc"),
    ("Druid",       "Balance",       "Druid",        "Balance"),
    ("Druid",       "Feral",         "Druid",        "Feral"),
    ("Evoker",      "Augmentation",  "Evoker",       "Augmentation"),
    ("Evoker",      "Devastation",   "Evoker",       "Devastation"),
    ("Hunter",      "BeastMastery",  "Hunter",       "Beast Mastery"),
    ("Hunter",      "Marksmanship",  "Hunter",       "Marksmanship"),
    ("Hunter",      "Survival",      "Hunter",       "Survival"),
    ("Mage",        "Arcane",        "Mage",         "Arcane"),
    ("Mage",        "Fire",          "Mage",         "Fire"),
    ("Mage",        "Frost",         "Mage",         "Frost"),
    ("Monk",        "Windwalker",    "Monk",         "Windwalker"),
    ("Paladin",     "Retribution",   "Paladin",      "Retribution"),
    ("Priest",      "Shadow",        "Priest",       "Shadow"),
    ("Rogue",       "Assassination", "Rogue",        "Assassination"),
    ("Rogue",       "Outlaw",        "Rogue",        "Outlaw"),
    ("Rogue",       "Subtlety",      "Rogue",        "Subtlety"),
    ("Shaman",      "Elemental",     "Shaman",       "Elemental"),
    ("Shaman",      "Enhancement",   "Shaman",       "Enhancement"),
    ("Warlock",     "Affliction",    "Warlock",      "Affliction"),
    ("Warlock",     "Demonology",    "Warlock",      "Demonology"),
    ("Warlock",     "Destruction",   "Warlock",      "Destruction"),
    ("Warrior",     "Arms",          "Warrior",      "Arms"),
    ("Warrior",     "Fury",          "Warrior",      "Fury"),
]


QUERY_ZONE = """
query($id: Int!) {
  worldData {
    zone(id: $id) {
      id name
      encounters { id name }
      partitions { id name default }
    }
  }
}
"""

# partition 명시 — 패치(12.0.5=2) 경계 고정. 안 주면 default(=최신) 사용.
QUERY_RANKS = """
query($encounterId: Int!, $page: Int!, $cls: String!, $spec: String!,
      $diff: Int!, $partition: Int!) {
  worldData {
    encounter(id: $encounterId) {
      characterRankings(
        metric: dps
        difficulty: $diff
        className: $cls
        specName: $spec
        page: $page
        partition: $partition
      )
    }
  }
}
"""


def fetch_spec_for_boss(cli: WCLV2, encounter_id: int, cls_v2: str,
                        spec_v2: str, difficulty: int,
                        partition: int) -> list[dict]:
    """한 보스 × 한 스펙의 top-N rankings."""
    out: list[dict] = []
    for page in range(1, MAX_PAGES_PER_SPEC + 1):
        try:
            data = cli.query(QUERY_RANKS, {
                "encounterId": encounter_id,
                "page": page,
                "cls": cls_v2,
                "spec": spec_v2,
                "diff": difficulty,
                "partition": partition,
            })
        except WCLV2Error as e:
            print(f"      page {page} 실패: {str(e)[:120]}")
            break
        wrap = (((data or {}).get("worldData") or {}).get("encounter") or {})
        obj = wrap.get("characterRankings") or {}
        ranks = obj.get("rankings") or []
        out.extend(ranks)
        if len(out) >= TOP_N or not obj.get("hasMorePages"):
            break
        time.sleep(0.1)
    return out[:TOP_N]


def main(difficulty: int = DEFAULT_DIFFICULTY) -> None:
    diff_label = DIFF_LABEL.get(difficulty, f"diff{difficulty}")
    OUT = OUT_DIR / f"rankings_zone{ZONE_ID}_{diff_label}_dps_top{TOP_N}.csv"
    print(f"=== difficulty={difficulty} ({diff_label}) → {OUT.name} ===")
    try:
        cli = WCLV2()
    except WCLV2Error as e:
        sys.exit(f"V2 client 초기화 실패: {e}")

    zone = cli.query(QUERY_ZONE, {"id": ZONE_ID})["worldData"]["zone"]
    encounters = zone["encounters"]
    # 최신 패치 partition 자동 선택 (default=True 인 것). 패치 늘어도 알아서 최신.
    parts = zone.get("partitions") or []
    default_part = next((p for p in parts if p.get("default")), None)
    partition = default_part["id"] if default_part else 1
    part_name = default_part["name"] if default_part else "?"
    print(f"Zone: {zone['name']} ({len(encounters)} encounters) "
          f"· partition={partition} ({part_name})")

    rate = cli.points_left()
    rate_start_pts = rate.get("pointsSpentThisHour") if rate else None
    if rate:
        print(f"V2 rate start: {rate['pointsSpentThisHour']:.1f}/{rate['limitPerHour']}")

    total_rows = 0
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "encounter_id", "encounter_name", "class", "spec", "rank",
            "character", "guild", "server", "region",
            "dps", "item_level", "duration_ms",
            "report_id", "fight_id", "start_time",
        ])

        for enc in encounters:
            print(f"\n  {enc['name']} (id={enc['id']})")
            for cls_v2, spec_v2, cls_v1, spec_v1 in TARGETS:
                ranks = fetch_spec_for_boss(cli, enc["id"], cls_v2, spec_v2,
                                            difficulty, partition)
                if not ranks:
                    continue
                for i, r in enumerate(ranks, 1):
                    srv = r.get("server") or {}
                    if isinstance(srv, dict):
                        server_name = srv.get("name") or ""
                        reg = srv.get("region")
                        region_name = (reg.get("name") if isinstance(reg, dict)
                                       else str(reg) if reg else "")
                    else:
                        server_name = ""
                        region_name = ""
                    guild = r.get("guild") or {}
                    guild_name = guild.get("name") if isinstance(guild, dict) else ""
                    report = r.get("report") or {}
                    report_id = (report.get("code") if isinstance(report, dict)
                                 else None)
                    fight_id = (report.get("fightID") if isinstance(report, dict)
                                else None)
                    start_time = (report.get("startTime") if isinstance(report, dict)
                                  else None)

                    w.writerow([
                        enc["id"], enc["name"], cls_v1, spec_v1, i,
                        r.get("name"),
                        guild_name,
                        server_name,
                        region_name,
                        r.get("amount") or r.get("total"),
                        r.get("bracketData"),  # itemLevel 자리
                        r.get("duration"),
                        report_id, fight_id, start_time,
                    ])
                total_rows += len(ranks)
                if len(ranks) < TOP_N:
                    print(f"    {cls_v1}/{spec_v1}: {len(ranks)}")
            f.flush()

    print(f"\nDone. {total_rows} rows -> {OUT}")
    rate = cli.points_left()
    rate_end_pts = rate.get("pointsSpentThisHour") if rate else None
    if rate:
        print(f"V2 rate end: {rate['pointsSpentThisHour']:.1f}/{rate['limitPerHour']}")

    # PC 간 sync 용 history 한 줄 기록 (data/update_log.json)
    try:
        from update_log import record
        api_pts = (round(rate_end_pts - rate_start_pts, 1)
                   if rate_start_pts is not None and rate_end_pts is not None
                   else None)
        record(
            action="fetch_rankings_v2",
            params={"difficulty": difficulty, "label": diff_label,
                    "zone": ZONE_ID, "top_n": TOP_N, "partition": partition},
            result={"rows": total_rows, "api_pts": api_pts},
            files=[f"data/{OUT.name}"],
        )
    except Exception as e:
        print(f"[update_log] skip: {e}")


if __name__ == "__main__":
    # CLI: python fetch_rankings_v2.py [difficulty]  (4=Heroic, 5=Mythic)
    diff_arg = DEFAULT_DIFFICULTY
    if len(sys.argv) > 1:
        try:
            diff_arg = int(sys.argv[1])
        except ValueError:
            sys.exit(f"bad difficulty: {sys.argv[1]} (use 3/4/5)")
    main(difficulty=diff_arg)
