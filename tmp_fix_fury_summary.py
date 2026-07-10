# -*- coding: utf-8 -*-
"""분노 summary 구버전(옛 보스별 영특 n≈40) → 2026-07-11 실측(n=893)으로 교체."""
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

P = "data/rotation_data.json"
d = json.load(open(P, encoding="utf-8"))
fury = d["Warrior"]["specs"]["Fury"]
fury["summary"] = (
    "격노(Enrage)를 끊김 없이 유지하며 분노를 광란으로 쏟는 ★비설계형 반응형 근딜★. "
    "도트 유지·디버프 윈도우 정렬 없음. 단 APM 게임 내 최상위라 손은 바쁨(어렵진 않고 입력량만 많음). "
    "★보스별 영웅특성(신화 top100 실측, n=893): 산왕 = 바엘고어 99%·선봉대 100%·벨로렌 94%·살라다르 79% / "
    "학살자 = 르우라 100%·보라시우스 98%·아베르지안 96%·우주의 왕관 83%·카이메루스 68% — 둘 다 필수.★ "
    "현실: 분노는 순수 단일딜이 강하지 않음 — 손 편함·유연성·전투의 외침 셔틀 가치. "
    "세기말 파스 관점에선 인구가 많아(784명) 백분위 쿠션이 있는 스펙."
)
json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("summary 교체 완료")
