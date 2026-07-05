import json, sys
from pathlib import Path
sys.path.insert(0, ".")
from blizzard import Blizzard

OUT = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")
cli = Blizzard()

results = {}
for sid in range(1264820, 1264845):
    dd = cli.get(f"/data/wow/spell/{sid}")
    if dd and dd.get("description"):
        results[sid] = {"name": dd.get("name"), "desc": dd.get("description")}
(OUT / "mm_tier_spell_range.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print("saved", len(results))
