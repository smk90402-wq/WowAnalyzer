"""Blizzard Game Data API 로 spell_db.json 미상 ID 백필 + 권위 한글화.

전략 (per ID):
  1) /data/wow/spell/{id} → 직접 spell 이면 한글명/설명/아이콘
  2) /data/wow/talent/{id} → talent 객체. spell.id 받아서 다시 spell 조회 (체인)
  3) 둘 다 404 → 진짜 unknown 마킹 (NODE ID 등)

성공한 항목은 spell_db.json 에 덮어씀:
  - name_ko (덮어씀 — 블리자드가 권위)
  - name_en (없으면 채움)
  - icon (Blizzard 응답에 media href 만 있어서 icon 파일명 별도 조회 필요 — 일단 보류)
  - description_ko (새 필드)
  - blizzard_source (어떤 엔드포인트로 잡혔는지 추적용)

미상 (둘 다 404) 은 unknown=True 유지.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from blizzard import Blizzard, BlizzardError

DATA = Path(__file__).parent / "data"
DB = DATA / "spell_db.json"


def resolve_one(cli: Blizzard, sid: int) -> tuple[str, dict] | tuple[None, None]:
    """(source, blizzard_data) 또는 (None, None) 미상."""
    # 1) spell 직접
    d = cli.get(f"/data/wow/spell/{sid}")
    if d and d.get("name"):
        return ("spell", d)
    # 2) talent 체인
    t = cli.get(f"/data/wow/talent/{sid}")
    if t:
        spell_ref = t.get("spell")
        if isinstance(spell_ref, dict) and spell_ref.get("id"):
            inner = cli.get(f"/data/wow/spell/{spell_ref['id']}")
            if inner and inner.get("name"):
                return ("talent->spell", inner)
    return (None, None)


def main() -> None:
    db = json.loads(DB.read_text(encoding="utf-8"))
    unknown_ids = sorted([int(k) for k, v in db.items() if not v.get("name_ko")])
    print(f"미상 (name_ko 없음): {len(unknown_ids)}")

    cli = Blizzard()

    hit_spell = hit_talent = miss = 0
    for i, sid in enumerate(unknown_ids, 1):
        try:
            src, data = resolve_one(cli, sid)
        except BlizzardError as e:
            print(f"  {sid}: blizzard err {e}")
            miss += 1
            continue
        key = str(sid)
        if data:
            entry = db.get(key, {})
            entry["name_ko"] = data.get("name") or entry.get("name_ko") or ""
            # Blizzard 응답은 description 도 ko 로 옴
            desc = data.get("description") or ""
            if desc:
                entry["description_ko"] = desc
            entry["blizzard_source"] = src
            # unknown 마크 해제
            entry.pop("unknown", None)
            db[key] = entry
            if src == "spell":
                hit_spell += 1
            else:
                hit_talent += 1
        else:
            db[key] = {**db.get(key, {}), "unknown": True, "blizzard_source": "miss"}
            miss += 1

        if i % 50 == 0:
            DB.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
            print(f"  {i}/{len(unknown_ids)}  spell={hit_spell}  talent={hit_talent}  miss={miss}")
        # 100/sec 한도라 0.02s sleep 면 충분
        time.sleep(0.02)

    DB.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    print(f"\n=== 완료 ===")
    print(f"  spell 직접 hit: {hit_spell}")
    print(f"  talent→spell hit: {hit_talent}")
    print(f"  miss (NODE 등): {miss}")

    # 전체 상태
    final_kr = sum(1 for v in db.values() if v.get("name_ko"))
    print(f"\n전체 spell_db: {len(db)}, name_ko 있음: {final_kr}")


if __name__ == "__main__":
    main()
