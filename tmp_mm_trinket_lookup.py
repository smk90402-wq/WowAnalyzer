import json, sys
from pathlib import Path
sys.path.insert(0, ".")
from blizzard import Blizzard

OUT = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
cli = Blizzard()

items = [260235, 249344, 268292, 252420, 249345, 250144]
out = {}
for iid in items:
    d = cli.get(f"/data/wow/item/{iid}")
    if d:
        spells = []
        for sp in (d.get("preview_item", {}).get("spells") or []):
            spells.append({"spell_id": sp.get("spell", {}).get("id"), "spell_name": sp.get("spell", {}).get("name"), "text": sp.get("description")})
        out[iid] = {"name": d.get("name"), "spells": spells}
    else:
        out[iid] = None
(OUT / "mm_trinket_lookup.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("done")
