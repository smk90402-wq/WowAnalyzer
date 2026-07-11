# -*- coding: utf-8 -*-
"""6조합 감사 퀵픽스 — BM 하이브리드 보스, 악마 보스 변형, MM 파수꾼 요약, 무기 단일↔광 실측 명시."""
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

R = "data/rotation_data.json"
d = json.load(open(R, encoding="utf-8"))
done = []

# 1) BM 무리의 지도자 — 살라다르·카이메루스 하이브리드(top20 회전베기 선호)
bm = d["Hunter"]["specs"]["Beast Mastery"]["builds"].get("무리의 지도자")
if bm and bm.get("flow"):
    ad = bm["flow"].setdefault("aoe_diff", [])
    line = ("살라다르·카이메루스는 혼재 구간 — 전체 채택은 광빌드(회전베기) 38~47%지만 top20은 60~70%가 광빌드입니다. "
            "최고점을 노리면 이 두 보스도 광빌드(쫄 패딩 여지), 안정 지향이면 단일빌드도 다수파(실측).")
    if not any("살라다르" in x for x in ad):
        ad.append(line)
        done.append("BM 하이브리드 보스")

# 2) 악마 — 탭에 영웅명 명기 + 보라시우스/선봉대 변형
demo = d["Warlock"]["specs"].get("Demonology")
if demo:
    b = demo["builds"]
    if "기본" in b:
        note = b["기본"].get("hero_note") or ""
        add = ("영웅특성 = 악마학자(실측 889/897, 영혼수확자는 8명 소수). "
               "보스 변형(실측): 보라시우스 = 단일 변형 — 안토란 병기를 빼고(채택 2%) 안정된 차원문 89%·익숙한 의식 97%. "
               "선봉대 = 광 변형 — 공포채찍 88%(전체 평균 32%), 익숙한 의식은 18%로 드랍.")
        if "악마학자" not in note:
            b["기본"]["hero_note"] = (note + " " + add).strip()
            done.append("악마 영웅명+보스 변형")

# 3) MM 파수꾼 — 보스별 채택 요약
mm = d["Hunter"]["specs"]["Marksmanship"]["builds"].get("파수꾼")
if mm:
    note = mm.get("hero_note") or ""
    add = ("채택 보스(신화 top100 실측): 바엘고어 97%·선봉대 99%·벨로렌 96%·우주의 왕관 80% — 광/혼합 보스 전담. "
           "아베르지안·살라다르는 46%로 어둠 순찰자와 갈림. 순수 단일(보라시우스·카이메루스·르우라)은 어둠 순찰자 탭 참고.")
    if "채택 보스" not in note:
        mm["hero_note"] = (note + " " + add).strip()
        done.append("MM 파수꾼 요약")

# 4) 무기 학살자 — 단일↔광 = 특성 스왑일 뿐, 손은 동일 (combo matrix 실측)
asl = d["Warrior"]["specs"]["Arms"]["builds"]["학살자"]["flow"]
ad = asl.setdefault("aoe_diff", [])
line = ("단일빌드↔광빌드(실측 304킬 vs 338킬)는 특성 패키지만 스왑됩니다 — 혈행성 전이(단일: 르우라·보라시우스·카이메루스) ↔ "
        "몸풀기였을 뿐+휩쓸기 일격 연마(광: 벨로렌·살라다르·우주의 왕관). 누르는 순서는 상태표 기준 동일(1순위 차이 없음 실측)이라 "
        "이 체크리스트 하나로 둘 다 커버 — 광패키지에선 휩쓸기 일격 수동 시전만 불필요(거인의 강타가 자동 부여).")
if not any("혈행성 전이" in x for x in ad):
    ad.insert(1, line)
    done.append("무기 단일↔광 명시")

json.dump(d, open(R, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("완료:", done)
