# -*- coding: utf-8 -*-
"""산왕 flow — 피의 갈증을 급살 마무리 위로 (실측: 급살 들고도 피갈 계열 25% > 마무리 18.5%)."""
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

R = "data/rotation_data.json"
d = json.load(open(R, encoding="utf-8"))
rows = d["Warrior"]["specs"]["Fury"]["builds"]["산왕"]["flow"]["checklist"]

bt_i = next(i for i, r in enumerate(rows) if r["a"] == "피의 갈증")
sd_i = next(i for i, r in enumerate(rows) if r["a"] == "마무리 일격" and "급살" in r["q"])
bt = rows.pop(bt_i)
sd_i = next(i for i, r in enumerate(rows) if r["a"] == "마무리 일격" and "급살" in r["q"])
rows.insert(sd_i, bt)
bt["q"] = "우레 작렬·오딘 다음은 피의 갈증 — 급살보다 먼저"
bt["why"] = ("산왕은 피의 갈증이 우레 작렬 엔진(35% 충전)이라 급살 마무리보다 위입니다 — "
             "상위권은 급살을 들고도 피갈부터(실측 피갈 계열 25% > 마무리 18.5%, 급살 소모 지연 2.8초로 "
             "학살자 1.7초보다 느긋). 급살은 1~2글쿨 안에만 처리하면 됩니다")
json.dump(d, open(R, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("산왕 피갈>급살 순서 교정:", [r["a"] for r in rows])
