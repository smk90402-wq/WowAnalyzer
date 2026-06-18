"""Blizzard API + Wowhead fallback 으로 아이템/스펠 한글 + 아이콘 enrichment.

수집:
  - v2_cache_player_fight.json: gear → item IDs (gear + gems) + enchant spell IDs
  - v2_cache_events.json: 전투 시작 5초 이내 apply* buff 스펠 IDs
  - v2_cache_damage.json: damage spell IDs
  - talent_trees.json: talent option spell IDs (트리 노드 아이콘)

출력:
  - data/item_db.json  (신규)         : {iid: {name_ko, icon, ilvl, quality}}
  - data/spell_db.json (augmented)    : 빠진 spell 들 채움

흐름 (per spell ID):
  1) Blizzard /data/wow/spell/{id} + /data/wow/talent/{id} chain
  2) miss 면 Wowhead /tooltip/spell/{id}?locale=1 (한글)
  3) 둘 다 miss 면 unknown 마킹

병렬: ThreadPoolExecutor(16). Blizzard 100/sec, Wowhead 200ms 간격 — 보통 1분 안.
"""
from __future__ import annotations
import json, sys, time
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests
from blizzard import Blizzard

DATA = Path(__file__).parent / "data"
PFIGHT = DATA / "v2_cache_player_fight.json"
EVENTS = DATA / "v2_cache_events.json"
DAMAGE = DATA / "v2_cache_damage.json"
META = DATA / "v2_cache_report_meta.json"
TREES = DATA / "talent_trees.json"
SPELL_DB = DATA / "spell_db.json"
ITEM_DB = DATA / "item_db.json"

WOWHEAD_TOOLTIP = "https://nether.wowhead.com/tooltip/spell/{id}?locale=1"
WOWHEAD_ENCHANT_PAGE = "https://www.wowhead.com/ko/enchantment={id}"
WOWHEAD_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# enchant 페이지 스크래핑용
import re
_RE_PAGE_TITLE = re.compile(r"<title>([^<]+)</title>")
_RE_OG_IMAGE = re.compile(r'<meta property="og:image" content="[^"]*?/([A-Za-z0-9_\-]+\.(jpg|png))"', re.IGNORECASE)


def wowhead_fallback(sid: int) -> dict:
    """Wowhead 한글 tooltip fallback. {name_ko, icon, description_ko} or miss."""
    try:
        r = requests.get(WOWHEAD_TOOLTIP.format(id=sid), timeout=8, headers=WOWHEAD_HEADERS)
        if r.status_code != 200:
            return {"miss": True}
        d = r.json()
        name = (d.get("name") or "").strip()
        if not name:
            return {"miss": True}
        icon_raw = (d.get("icon") or "").strip()
        icon = icon_raw if icon_raw.endswith(".jpg") else (icon_raw + ".jpg" if icon_raw else "")
        return {
            "name_ko": name,
            "icon": icon.lower(),
            "description_ko": d.get("tooltip") or "",
            "src": "wowhead",
        }
    except Exception:
        return {"miss": True}


def wowhead_enchant_scrape(eid: int) -> dict:
    """Wowhead 웹 페이지에서 enchant 한글 이름 + 아이콘 추출.

    URL: https://www.wowhead.com/ko/enchantment={id}
    Title 형식: "강한 해독제 - 마법부여 - 와우 데이터베이스" 또는
               "아이템 강화: <이름> - 마법부여 - 와우 데이터베이스"
    """
    try:
        r = requests.get(WOWHEAD_ENCHANT_PAGE.format(id=eid), timeout=10, headers=WOWHEAD_HEADERS)
        if r.status_code != 200:
            return {"miss": True}
        html = r.text
        m = _RE_PAGE_TITLE.search(html)
        title = (m.group(1) if m else "").strip()
        # 분리: "<name> - 마법부여 - 와우..." 또는 "아이템 강화: <name> - ..."
        name = ""
        if title and "와우" in title:  # Wowhead 페이지 확실
            # "와우헤드" / "와우 데이터베이스" 부분 자르고 앞부분 추출
            head = title.split(" - 와우")[0].strip()
            # "아이템 강화:" prefix 있으면 제거
            for prefix in ("아이템 강화:", "Enchantment:", "Item Enhancement:"):
                if head.startswith(prefix):
                    head = head[len(prefix):].strip()
                    break
            # 끝의 " - 마법부여" 등 제거
            head = head.split(" - ")[0].strip()
            name = head
        if not name or len(name) > 100:
            return {"miss": True}
        # 아이콘: og:image 메타에서 추출
        m_icon = _RE_OG_IMAGE.search(html)
        icon = m_icon.group(1).lower() if m_icon else ""
        return {
            "name_ko": name,
            "icon": icon,
            "src": "wowhead_enchant_scrape",
        }
    except Exception:
        return {"miss": True}


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


def _item_needs_refresh(entry: dict | None) -> bool:
    if not isinstance(entry, dict) or entry.get("miss"):
        return True
    return not (entry.get("name_ko") and entry.get("icon") and entry.get("quality"))


def fetch_spell(cli: Blizzard, sid: int) -> dict:
    """spell id → {name_ko, icon, description_ko, src}.

    1) Blizzard /spell/{id}
    2) Blizzard /talent/{id} → spell chain
    3) Wowhead /tooltip/spell/{id}?locale=1 fallback
    """
    d = cli.get(f"/data/wow/spell/{sid}")
    if not d or not d.get("name"):
        t = cli.get(f"/data/wow/talent/{sid}")
        if t and isinstance(t.get("spell"), dict) and t["spell"].get("id"):
            inner_sid = t["spell"]["id"]
            d = cli.get(f"/data/wow/spell/{inner_sid}")
    if d and d.get("name"):
        name = (d.get("name") or "").strip()
        desc = (d.get("description") or "").strip()
        real_sid = d.get("id") or sid
        media = cli.get(f"/data/wow/media/spell/{real_sid}")
        icon = _icon_filename(media)
        return {"name_ko": name, "icon": icon, "description_ko": desc, "src": "blizzard"}
    # Wowhead nether tooltip fallback
    nether = wowhead_fallback(sid)
    if not nether.get("miss"):
        return nether
    # Wowhead enchant page scraping (마부 ID 가 spell ID 와 다른 체계인 경우)
    return wowhead_enchant_scrape(sid)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items-only", action="store_true",
                        help="refresh item_db only; skip spell_db enrichment")
    args = parser.parse_args()

    pf = json.loads(PFIGHT.read_text(encoding="utf-8"))
    spell_db = json.loads(SPELL_DB.read_text(encoding="utf-8")) if SPELL_DB.exists() else {}
    item_db = json.loads(ITEM_DB.read_text(encoding="utf-8")) if ITEM_DB.exists() else {}
    try:
        damage = json.loads(DAMAGE.read_text(encoding="utf-8"))
    except Exception:
        damage = {}

    # ID 수집
    item_ids: set[int] = set()
    item_seen: dict[int, dict] = {}
    ench_ids: set[int] = set()

    def remember_item(iid, *, name: str = "", ilvl=None, slot=None, bonus=None) -> None:
        if not isinstance(iid, int) or iid <= 0:
            return
        item_ids.add(iid)
        seen = item_seen.setdefault(iid, {"seen_slots": set(), "seen_bonus_ids": set()})
        if name and not seen.get("name_wcl"):
            seen["name_wcl"] = str(name).strip()
        if isinstance(ilvl, (int, float)):
            seen["max_seen_ilvl"] = max(int(ilvl), int(seen.get("max_seen_ilvl") or 0))
        if isinstance(slot, int):
            seen["seen_slots"].add(slot)
        if isinstance(bonus, list):
            for bid in bonus:
                if isinstance(bid, int):
                    seen["seen_bonus_ids"].add(bid)

    for v in pf.values():
        if not isinstance(v, dict):
            continue
        for g in v.get("gear", []) or []:
            if not isinstance(g, dict):
                continue
            if isinstance(g.get("id"), int):
                remember_item(
                    g["id"],
                    name=g.get("name") or "",
                    ilvl=g.get("ilvl"),
                    slot=g.get("slot"),
                    bonus=g.get("bonus") or [],
                )
            if isinstance(g.get("ench"), int):
                ench_ids.add(g["ench"])
            for x in g.get("gems") or []:
                if isinstance(x, int):
                    remember_item(x)

    dmg_spell_ids: set[int] = set()
    for entries in damage.values():
        if not isinstance(entries, list):
            continue
        for e in entries:
            if isinstance(e, dict) and isinstance(e.get("guid"), int):
                dmg_spell_ids.add(e["guid"])

    # 전체 fight 의 buff + cast IDs (timeline 호버 툴팁 데이터)
    # 이전 버전은 5초 이내 apply 만 → 후반 procs 누락. 모두 수집.
    buff_ids: set[int] = set()
    cast_ids: set[int] = set()
    try:
        events = json.loads(EVENTS.read_text(encoding="utf-8"))
        for key, ev in events.items():
            if not isinstance(ev, dict):
                continue
            for e in ev.get("buffs") or []:
                if not isinstance(e, list) or len(e) < 2:
                    continue
                try:
                    sp = int(e[1])
                    if sp > 0:
                        buff_ids.add(sp)
                except (TypeError, ValueError):
                    continue
            for e in ev.get("casts") or []:
                if not isinstance(e, list) or len(e) < 2:
                    continue
                try:
                    sp = int(e[1])
                    if sp > 0:
                        cast_ids.add(sp)
                except (TypeError, ValueError):
                    continue
    except Exception as ex:
        print(f"  events scan err: {ex}")

    # pre-pull buffs (음식/영약/오일 등) 추가 수집
    try:
        prepull_path = DATA / "v2_cache_prepull_buffs.json"
        if prepull_path.exists():
            prepull = json.loads(prepull_path.read_text(encoding="utf-8"))
            for entries in prepull.values():
                if not isinstance(entries, list):
                    continue
                for e in entries:
                    if isinstance(e, dict) and isinstance(e.get("spell_id"), int):
                        buff_ids.add(e["spell_id"])
            print(f"  v2_cache_prepull_buffs.json scanned ({len(prepull)} entries)")
    except Exception as ex:
        print(f"  prepull scan err: {ex}")

    # talent_trees.json 노드들의 spell_id (트리 아이콘용)
    talent_spell_ids: set[int] = set()
    try:
        trees = json.loads(TREES.read_text(encoding="utf-8"))
        for spec_data in trees.values():
            if not isinstance(spec_data, dict):
                continue
            node_lists = [spec_data.get("class") or [], spec_data.get("spec") or []]
            for hd in (spec_data.get("hero") or {}).values():
                node_lists.append(hd.get("nodes") or [])
            for nl in node_lists:
                for n in nl:
                    for opt in n.get("options") or []:
                        sid = opt.get("spell_id")
                        if isinstance(sid, int):
                            talent_spell_ids.add(sid)
    except Exception as ex:
        print(f"  talent tree scan err: {ex}")

    spell_ids = ench_ids | dmg_spell_ids | buff_ids | cast_ids | talent_spell_ids
    print(f"  enchant={len(ench_ids)} damage={len(dmg_spell_ids)} "
          f"buff(all)={len(buff_ids)} cast(all)={len(cast_ids)} "
          f"talent_opts={len(talent_spell_ids)}")

    # 빠진 거만
    item_seen_changed = False
    for iid, seen in item_seen.items():
        key = str(iid)
        entry = item_db.get(key)
        if not isinstance(entry, dict):
            entry = {}
        before = dict(entry)
        name_wcl = (seen.get("name_wcl") or "").strip()
        if name_wcl and not entry.get("name_wcl"):
            entry["name_wcl"] = name_wcl
        max_seen = seen.get("max_seen_ilvl")
        if isinstance(max_seen, int) and max_seen > int(entry.get("max_seen_ilvl") or 0):
            entry["max_seen_ilvl"] = max_seen
        slots = sorted(seen.get("seen_slots") or [])
        if slots and entry.get("seen_slots") != slots:
            entry["seen_slots"] = slots
        bonus_ids = sorted(seen.get("seen_bonus_ids") or [])
        if bonus_ids and entry.get("seen_bonus_ids") != bonus_ids:
            entry["seen_bonus_ids"] = bonus_ids
        if entry != before:
            item_db[key] = entry
            item_seen_changed = True

    missing_items = sorted(i for i in item_ids if _item_needs_refresh(item_db.get(str(i))))
    missing_spells = sorted(
        s for s in spell_ids
        if str(s) not in spell_db or not spell_db[str(s)].get("name_ko") or spell_db[str(s)].get("miss")
    )
    if args.items_only:
        missing_spells = []

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
                existing = item_db.get(str(iid), {})
                if isinstance(existing, dict):
                    existing.update(entry)
                    item_db[str(iid)] = existing
                else:
                    item_db[str(iid)] = entry
                if done % 100 == 0:
                    print(f"  {done}/{len(missing_items)}  ok={ok}  miss={miss}")
        print(f"  완료 ({time.time()-t0:.1f}s) — ok={ok} miss={miss}")
        ITEM_DB.write_text(json.dumps(item_db, ensure_ascii=False), encoding="utf-8")
    elif item_seen_changed:
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

    try:
        from update_log import record
        record(
            action="enrich_kr",
            params={"missing_items": len(missing_items),
                    "missing_spells": len(missing_spells)},
            result={"item_db": len(item_db), "spell_db": len(spell_db)},
            files=["data/item_db.json", "data/spell_db.json"],
        )
    except Exception as e:
        print(f"[update_log] skip: {e}")


if __name__ == "__main__":
    main()
