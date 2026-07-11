# -*- coding: utf-8 -*-
"""Hunter/Survival + Shaman/Elemental 특성 트리 fetch → data/talent_trees.json 에 병합.

fetch_talent_trees.py 의 compact_node 를 그대로 재사용 (구조 동일 보장).
기존 키는 건드리지 않고 두 키만 추가/갱신.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from blizzard import Blizzard
from fetch_talent_trees import compact_node

DATA = Path(__file__).parent / "data"
OUT = DATA / "talent_trees.json"

SPECS = [
    ("Hunter/Survival",  774, 255),  # 생존 사냥꾼 특성 분기 채굴용 (2026-07-11)
    ("Shaman/Elemental", 786, 262),  # 정기 주술사 특성 분기 채굴용 (2026-07-11)
]


def main() -> None:
    result = json.load(open(OUT, encoding="utf-8"))
    cli = Blizzard()
    for key, class_tree_id, spec_id in SPECS:
        print(f"=== {key} (class_tree={class_tree_id}, spec={spec_id}) ===")
        d = cli.get(f"/data/wow/talent-tree/{class_tree_id}/playable-specialization/{spec_id}")
        if not d:
            print("  failed")
            continue
        class_nodes = [compact_node(n) for n in (d.get("class_talent_nodes") or [])]
        spec_nodes = [compact_node(n) for n in (d.get("spec_talent_nodes") or [])]
        hero_trees = {}
        for ht in (d.get("hero_talent_trees") or []):
            ht_name = ht.get("name") or f"hero_{ht.get('id')}"
            hero_trees[ht_name] = {
                "id": ht.get("id"),
                "nodes": [compact_node(n) for n in (ht.get("hero_talent_nodes") or [])],
            }
        result[key] = {
            "class_tree_id": class_tree_id,
            "spec_id": spec_id,
            "class": class_nodes,
            "spec": spec_nodes,
            "hero": hero_trees,
        }
        print(f"  class:{len(class_nodes)}  spec:{len(spec_nodes)}  hero:{list(hero_trees)}")
        time.sleep(0.3)
    OUT.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
