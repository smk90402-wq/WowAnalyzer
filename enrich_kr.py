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
WOWHEAD_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


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
    # Wowhead fallback
    return wowhead_fallback(sid)


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

    # 전투 시작 5초 이내 apply* buff IDs (음식/오일 제외한 in-combat buff)
    buff_ids: set[int] = set()
    try:
        events = json.loads(EVENTS.read_text(encoding="utf-8"))
        meta = json.loads(META.read_text(encoding="utf-8"))
        # rid → {fid: startTime} index
        start_idx = {}
        for rid, m in meta.items():
            if not isinstance(m, dict):
                continue
            for f in m.get("fights", []) or []:
                if isinstance(f.get("id"), int) and isinstance(f.get("startTime"), (int, float)):
                    start_idx[(rid, int(f["id"]))] = int(f["startTime"])
        for key, ev in events.items():
            if not isinstance(ev, dict):
                continue
            parts = key.split(":")
            if len(parts) != 3:
                continue
            try:
                rid, fid = parts[0], int(parts[1])
            except (TypeError, ValueError):
                continue
            start = start_idx.get((rid, fid))
            if start is None:
                continue
            for e in ev.get("buffs") or []:
                if not isinstance(e, list) or len(e) < 3:
                    continue
                try:
                    ts = int(e[0]); sp = int(e[1])
                except (TypeError, ValueError):
                    continue
                if (e[2] or "").startswith("apply") and start <= ts <= start + 5000:
                    buff_ids.add(sp)
    except Exception as ex:
        print(f"  events scan err: {ex}")

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

    spell_ids = ench_ids | dmg_spell_ids | buff_ids | talent_spell_ids
    print(f"  enchant={len(ench_ids)} damage={len(dmg_spell_ids)} "
          f"buff(in-combat)={len(buff_ids)} talent_opts={len(talent_spell_ids)}")

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
