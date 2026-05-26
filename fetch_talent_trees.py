"""Blizzard talent-tree 데이터 5스펙 fetch — 트리 구조 (좌표, 연결, 한글 스펠).

각 스펙:
  - class_talent_nodes  (직업 트리)
  - spec_talent_nodes   (전문화 트리)
  - hero_talent_trees   (영웅 트리들, 각각 hero_talent_nodes)
각 노드:
  - id, display_row, display_col, raw_position_x/y
  - node_type {id, type}: CHOICE / ACTIVE / PASSIVE
  - unlocks: [node_id, ...]  → 연결선
  - ranks: [{rank, tooltip{spell, talent}, choice_of_tooltips}]
    각 spell: {id, name, description, cast_time, ...}, talent: {id, name}

출력: data/talent_trees.json
  {
    "Warrior/Arms": {
      "class_id": 71,
      "spec_id": 71,
      "class_tree_id": ...,
      "class": [...],   # 노드 리스트
      "spec":  [...],
      "hero":  {"hero_name1": {nodes:[...], media:"..."}, ...},
    },
    ...
  }
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from blizzard import Blizzard

DATA = Path(__file__).parent / "data"
OUT = DATA / "talent_trees.json"

# (display key, class tree ID, spec ID) — Blizzard 의 specID
SPECS = [
    ("Warlock/Demonology",     720, 266),   # Warlock 흑마법사 tree=720, Demo spec=266
    ("Druid/Balance",          793, 102),   # Druid tree=793, Balance spec=102
    ("Hunter/Beast Mastery",   774, 253),
    ("Warrior/Arms",           850, 71),
    ("Warrior/Fury",           850, 72),
    # Monk 추가 (인사이더 등 사용자 캐릭) — Brewmaster 268 / Windwalker 269 / Mistweaver 270.
    # class tree id 는 Blizzard talent-tree/index 확인 결과 1000 (Monk 수도사).
    ("Monk/Brewmaster",        1000, 268),
    ("Monk/Windwalker",        1000, 269),
    ("Monk/Mistweaver",        1000, 270),
]


def _extract_option(d: dict) -> dict | None:
    """tooltip 또는 choice_of_tooltips 의 원소 1개 → option dict.

    Blizzard 응답 실제 구조:
      {
        "talent":        {"id": X, "name": "..."},
        "spell_tooltip": {"spell": {"id": Y, "name": "..."}, "description": "...", "cast_time": "..."}
      }
    """
    if not isinstance(d, dict):
        return None
    talent = d.get("talent") or {}
    st = d.get("spell_tooltip") or {}
    spell = st.get("spell") or {}
    talent_id = talent.get("id")
    spell_id = spell.get("id")
    if talent_id is None and spell_id is None:
        return None
    return {
        "talent_id": talent_id,
        "spell_id": spell_id,
        "name": spell.get("name") or talent.get("name") or "",
        "desc": st.get("description") or "",
        "cast": st.get("cast_time") or "",
    }


def compact_node(n: dict) -> dict:
    """노드 하나에서 필요한 필드만 추출."""
    out = {
        "id": n.get("id"),
        "type": (n.get("node_type") or {}).get("type"),
        "row": n.get("display_row"),
        "col": n.get("display_col"),
        "x": n.get("raw_position_x"),
        "y": n.get("raw_position_y"),
        "unlocks": list(n.get("unlocks") or []),
        "max_rank": 1,
        "options": [],  # [{talent_id, spell_id, name, desc, cast}]
    }
    ranks = n.get("ranks") or []
    if ranks:
        out["max_rank"] = max((r.get("rank") or 1) for r in ranks)
        # 마지막 rank 의 tooltip 사용 (가장 최종 효과)
        last = ranks[-1]
        tt = last.get("tooltip")
        if isinstance(tt, dict):
            opt = _extract_option(tt)
            if opt:
                out["options"].append(opt)
        # CHOICE 노드 — 여러 선택지
        chs = last.get("choice_of_tooltips")
        if isinstance(chs, list):
            for c in chs:
                opt = _extract_option(c)
                if opt:
                    out["options"].append(opt)
    return out


def main() -> None:
    cli = Blizzard()
    result: dict = {}

    for key, class_tree_id, spec_id in SPECS:
        print(f"\n=== {key} (class_tree={class_tree_id}, spec={spec_id}) ===")
        d = cli.get(f"/data/wow/talent-tree/{class_tree_id}/playable-specialization/{spec_id}")
        if not d:
            print(f"  failed")
            continue

        class_nodes = [compact_node(n) for n in (d.get("class_talent_nodes") or [])]
        spec_nodes = [compact_node(n) for n in (d.get("spec_talent_nodes") or [])]
        hero_trees: dict = {}
        for ht in (d.get("hero_talent_trees") or []):
            ht_name = ht.get("name") or f"hero_{ht.get('id')}"
            ht_nodes = [compact_node(n) for n in (ht.get("hero_talent_nodes") or [])]
            hero_trees[ht_name] = {
                "id": ht.get("id"),
                "nodes": ht_nodes,
            }
        result[key] = {
            "class_tree_id": class_tree_id,
            "spec_id": spec_id,
            "class": class_nodes,
            "spec": spec_nodes,
            "hero": hero_trees,
        }
        print(f"  class:{len(class_nodes)}  spec:{len(spec_nodes)}  hero:{len(hero_trees)}")
        for hn, hd in hero_trees.items():
            print(f"    hero '{hn}': {len(hd['nodes'])} nodes")
        time.sleep(0.3)

    OUT.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"\nsaved {OUT}")

    try:
        from update_log import record
        record(
            action="fetch_talent_trees",
            params={"specs_requested": len(SPECS)},
            result={"specs_built": len(result)},
            files=["data/talent_trees.json"],
        )
    except Exception as e:
        print(f"[update_log] skip: {e}")


if __name__ == "__main__":
    main()
