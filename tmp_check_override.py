# -*- coding: utf-8 -*-
import json, re, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
db = json.load(open("data/spell_db.json", encoding="utf-8"))
src = open("app/main.py", encoding="utf-8").read()
i = src.find("# 전사 (2026-07-11")
blk = src[i:src.find("}", i)]
bad = 0
for name, sid in re.findall(r'"([^"]+)": (\d+)', blk):
    v = db.get(sid)
    nm = (v or {}).get("name_ko", "")
    ic = (v or {}).get("icon", "")
    flags = []
    if not v: flags.append("DB없음")
    elif nm != name: flags.append(f"이름불일치 db={nm}")
    if v and not ic: flags.append("아이콘없음")
    if flags:
        bad += 1
        print(name, sid, " / ".join(flags))
print(f"검사 완료 — 문제 {bad}건")
