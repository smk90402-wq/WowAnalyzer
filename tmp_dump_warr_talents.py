"""전사 특성 트리 공식 한글명 덤프 (가이드 번역 검증용)."""
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

t = json.load(open("data/talent_trees.json", encoding="utf-8"))
out = []
for spec in ("Warrior/Fury", "Warrior/Arms"):
    w = t[spec]
    out.append(f"== {spec} ==")
    for section in ("class", "spec"):
        out.append(f"-- {section} tree --")
        for node in w[section]:
            for o in node.get("options", []):
                out.append(f"{o['spell_id']}\t{o['name']}\t(node {node['id']}, row {node.get('row')})")
    for hname, htree in w["hero"].items():
        out.append(f"-- hero: {hname} --")
        for node in htree["nodes"]:
            for o in node.get("options", []):
                out.append(f"{o['spell_id']}\t{o['name']}\t(node {node['id']})")
open("data/transcripts/warr_talent_names.txt", "w", encoding="utf-8").write("\n".join(out))
print(len(out), "lines -> data/transcripts/warr_talent_names.txt")
