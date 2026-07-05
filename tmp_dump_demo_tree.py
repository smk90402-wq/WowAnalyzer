# -*- coding: utf-8 -*-
import json, io, sys
from pathlib import Path

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
out = io.StringIO()

tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
d = tt["Warlock/Demonology"]

def dump_nodes(nodes, tag):
    out.write(f"\n===== {tag} (n={len(nodes)}) =====\n")
    for n in sorted(nodes, key=lambda n: (n["row"], n["col"])):
        opts = n.get("options", [])
        names = " / ".join(o["name"] for o in opts)
        out.write(f"[{n['row']:>2},{n['col']:>2}] id={n['id']} type={n.get('type')} max_rank={n.get('max_rank')} :: {names}\n")
        for o in opts:
            out.write(f"    talent_id={o.get('talent_id')} spell_id={o.get('spell_id')} name={o['name']}\n")
            out.write(f"    desc: {(o.get('desc') or '').strip()}\n")

dump_nodes(d["spec"], "spec tree (Demonology)")
rows = sorted(set(n["row"] for n in d["spec"]))
bottom2 = set(rows[-2:])
apex = [n for n in d["spec"] if n["row"] in bottom2]
dump_nodes(apex, f"APEX rows={sorted(bottom2)}")

for hname, hval in d["hero"].items():
    dump_nodes(hval["nodes"], f"hero tree: {hname}")

Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad\demo_tree_dump.txt").write_text(out.getvalue(), encoding="utf-8")
print("written, len", len(out.getvalue()))
