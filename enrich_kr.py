"""Blizzard API 로 아이템/스펠 한글 + 아이콘 enrichment.

수집:
  - v2_cache_player_fight.json 의 gear → item IDs (gear + gems) + enchant spell IDs
  - v2_cache_damage.json 의 damage spell IDs

출력:
  - data/item_db.json  (신규)         : {iid: {name_ko, icon, ilvl, quality}}
  - data/spell_db.json (augmented)    : 빠진 enchant + damage spell 채움

병렬: ThreadPoolExecutor(16). Blizzard 100/sec 한도 안 — 1000 IDs × 2 calls ≈ 20초.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from blizzard import Blizzard

DATA = Path(__file__).parent / "data"
PFIGHT = DATA / "v2_cache_player_fight.json"
DAMAGE = DATA / "v2_cache_damage.json"
SPELL_DB = DATA / "spell_db.json"
ITEM_DB = DATA / "item_db.json"


def _icon_filename(media: dict | None) -> str:
    """Blizzard media response → icon 파일명 (e.g. 'inv_xxx.jpg')."""
    if not media:
        return ""
    assets = media.get("assets") or []
    if not isinstance(assets, list):
        return ""
    for a in assets:
        if isinstance(a, dict) and a.get("key") == "icon":
            url = a.get("value", "") or ""
            if url:
                name = url.rsplit("/", 1)[-1].lower()
                # Wowhead 는 .jpg 통일, 가끔 Blizzard 가 그냥 이름만 줌
                if not name.endswith((".jpg", ".png", ".gif")):
                    name += ".jpg"
                return name
    return ""


def fetch_item(cli: Blizzard, iid: int) -> dict:
    """item id → {name_ko, icon, ilvl, quality}. 실패 시 빈 entry."""
    d = cli.get(f"/data/wow/item/{iid}")
    if not d:
        return {"name_ko": "", "icon": "", "ilvl": None, "quality": "", "miss": True}
    name = (d.get("name") or "").strip()
    ilvl = d.get("level")
    quality = (d.get("quality") or {}).get("type") or ""
    media = cli.get(f"/data/wow/media/item/{iid}")
    icon = _icon_filename(media)
    return {"name_ko": name, "icon": icon, "ilvl": ilvl, "quality": quality}


def fetch_spell(cli: Blizzard, sid: int) -> dict:
    """spell id → {name_ko, icon, description_ko}. talent → spell chain 도 시도."""
    d = cli.get(f"/data/wow/spell/{sid}")
    if not d or not d.get("name"):
        # talent → spell chain
        t = cli.get(f"/data/wow/talent/{sid}")
        if t and isinstance(t.get("spell"), dict) and t["spell"].get("id"):
            inner_sid = t["spell"]["id"]
            d = cli.get(f"/data/wow/spell/{inner_sid}")
    if not d or not d.get("name"):
        return {"name_ko": "", "icon": "", "description_ko": "", "miss": True}
    name = (d.get("name") or "").strip()
    desc = (d.get("description") or "").strip()
    real_sid = d.get("id") or sid
    media = cli.get(f"/data/wow/media/spell/{real_sid}")
    icon = _icon_filename(media)
    return {"name_ko": name, "icon": icon, "description_ko": desc}


def main() -> None:
    pf = json.loads(PFIGHT.read_text(encoding="utf-8"))
    spell_db = json.loads(SPELL_DB.read_text(encoding="utf-8")) if SPELL_DB.exists() else {}
    item_db = json.loads(ITEM_DB.read_text(encoding="utf-8")) if ITEM_DB.exists() else {}
    try:
        damage = json.loads(DAMAGE.read_text(encoding="utf-8"))
    except Exception:
        damage = {}

    # ID 수집
    item_ids: set[int] = set()
    ench_ids: set[int] = set()
    for v in pf.values():
        if not isinstance(v, dict):
            continue
        for g in v.get("gear", []) or []:
            if not isinstance(g, dict):
                continue
            if isinstance(g.get("id"), int):
                item_ids.add(g["id"])
            if isinstance(g.get("ench"), int):
                ench_ids.add(g["ench"])
            for x in g.get("gems") or []:
                if isinstance(x, int):
                    item_ids.add(x)

    dmg_spell_ids: set[int] = set()
    for entries in damage.values():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("guid"), int):
                dmg_spell_ids.add(e["guid"])

    spell_ids = ench_ids | dmg_spell_ids

    # 빠진 거만
    missing_items = sorted(i for i in item_ids if str(i) not in item_db or item_db[str(i)].get("miss"))
    missing_spells = sorted(
        s for s in spell_ids
        if str(s) not in spell_db or not spell_db[str(s)].get("name_ko") or spell_db[str(s)].get("miss")
    )

    print(f"items: {len(item_ids)} unique, {len(missing_items)} 페치 필요")
    print(f"spells (enchant+damage): {len(spell_ids)} unique, {len(missing_spells)} 페치 필요")

    cli = Blizzard()
    cli._ensure_token()

    # ── 아이템 병렬 페치 ────────────────────────────────────────────────────
    if missing_items:
        print(f"\n=== items ({len(missing_items)}) 페치 ===")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=16) as ex:
            futures = {ex.submit(fetch_item, cli, iid): iid for iid in missing_items}
            done = ok = miss = 0
            for fut in as_completed(futures):
                iid = futures[fut]
                done += 1
                try:
                    entry = fut.result()
                except Exception as e:
                    entry = {"name_ko": "", "icon": "", "miss": True, "err": str(e)}
                if entry.get("name_ko"):
                    ok += 1
                else:
                    miss += 1
                item_db[str(iid)] = entry
                if done % 100 == 0:
                    print(f"  {done}/{len(missing_items)}  ok={ok}  miss={miss}")
        print(f"  완료 ({time.time()-t0:.1f}s) — ok={ok} miss={miss}")
        ITEM_DB.write_text(json.dumps(item_db, ensure_ascii=False), encoding="utf-8")

    # ── 스펠 병렬 페치 ──────────────────────────────────────────────────────
    if missing_spells:
        print(f"\n=== spells ({len(missing_spells)}) 페치 ===")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=16) as ex:
            futures = {ex.submit(fetch_spell, cli, sid): sid for sid in missing_spells}
            done = ok = miss = 0
            for fut in as_completed(futures):
                sid = futures[fut]
                done += 1
                try:
                    entry = fut.result()
                except Exception as e:
                    entry = {"name_ko": "", "icon": "", "miss": True, "err": str(e)}
                if entry.get("name_ko"):
                    ok += 1
                else:
                    miss += 1
                # 기존 entry merge
                existing = spell_db.get(str(sid), {})
                existing.update({k: v for k, v in entry.items() if v or k == "miss"})
                # icon 은 기존에 있으면 유지 (Blizzard miss 시 WoWhead 거 보존)
                if not existing.get("icon") and entry.get("icon"):
                    existing["icon"] = entry["icon"]
                spell_db[str(sid)] = existing
                if done % 50 == 0:
                    print(f"  {done}/{len(missing_spells)}  ok={ok}  miss={miss}")
        print(f"  완료 ({time.time()-t0:.1f}s) — ok={ok} miss={miss}")
        SPELL_DB.write_text(json.dumps(spell_db, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== 최종 ===")
    print(f"  item_db.json: {len(item_db)} entries")
    print(f"  spell_db.json: {len(spell_db)} entries")


if __name__ == "__main__":
    main()
