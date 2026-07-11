# -*- coding: utf-8 -*-
"""전사 가이드/트레이너가 참조하는 스펠을 spell_db.json 에 보강 (Blizzard ko_KR).

수집 대상 = 특성 트리(Warrior/Fury·Arms 전체) + proc_sources_{fury,arms} 버프
+ 실측 확정 캐스트/버프 ID. 이미 있는 항목은 건너뜀.
아이콘은 media/spell 엔드포인트에서 파일명만 추출 (기존 spell_db 포맷: 'xxx.jpg').
"""
from __future__ import annotations
import json, re, sys, time
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

sys.path.insert(0, str(Path(__file__).parent))
from blizzard import Blizzard

DB = Path("data/spell_db.json")

# 실측 확정 ID (2026-07-11 채굴 노트) — 트리에 없는 캐스트/버프 변형 포함
EXTRA_IDS = [
    1719, 184367, 446035, 385059, 5308, 280735, 281000, 163201,
    23881, 335096, 85288, 335097, 190411, 6343, 435222, 435615,
    107574, 52437, 184362, 206315, 12294, 7384, 167105, 1269383,
    1269391, 1292058, 1464, 845, 772, 436358, 228920, 260708,
    429636, 152278, 386633, 199854, 316440, 458689, 12950, 100,
    437118, 46924, 227847, 262161,
]


def tree_ids() -> set[int]:
    t = json.load(open("data/talent_trees.json", encoding="utf-8"))
    out: set[int] = set()
    for spec in ("Warrior/Fury", "Warrior/Arms"):
        w = t[spec]
        sections = [w["class"], w["spec"]] + [h["nodes"] for h in w["hero"].values()]
        for nodes in sections:
            for node in nodes:
                for o in node.get("options", []):
                    if o.get("spell_id"):
                        out.add(int(o["spell_id"]))
    return out


def proc_ids() -> set[int]:
    out: set[int] = set()
    for f in ("data/proc_sources_fury.json", "data/proc_sources_arms.json"):
        try:
            s = json.dumps(json.load(open(f, encoding="utf-8")))
            out.update(int(m) for m in re.findall(r'"(?:spell_id|buff_id|id)":\s*(\d{2,8})', s))
        except Exception:
            pass
    return out


def main():
    db = json.load(open(DB, encoding="utf-8"))
    want = sorted(tree_ids() | proc_ids() | set(EXTRA_IDS))
    missing = [sid for sid in want if str(sid) not in db]
    print(f"대상 {len(want)}개 중 spell_db 미보유 {len(missing)}개")
    cli = Blizzard()
    added = failed = 0
    for sid in missing:
        d = cli.get(f"/data/wow/spell/{sid}")
        if not d or not d.get("name"):
            failed += 1
            continue
        icon = ""
        m = cli.get(f"/data/wow/media/spell/{sid}")
        if m:
            for a in m.get("assets", []):
                if a.get("key") == "icon":
                    icon = a["value"].rsplit("/", 1)[-1]   # ....../ability_xxx.jpg
                    break
        db[str(sid)] = {
            "name_ko": d["name"],
            "icon": icon,
            "description_ko": d.get("description") or "",
            "src": "blizzard",
        }
        added += 1
        if added % 25 == 0:
            print(f"  …{added}개 수집")
        time.sleep(0.05)
    json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"완료: 추가 {added}, 실패(404 등) {failed} → spell_db {len(db)}개")


if __name__ == "__main__":
    main()
