# -*- coding: utf-8 -*-
"""생존·정술 6조합 실측 반영 — 파수꾼 레이드 0 명시, 정술 영웅 축 신설(텍스트)."""
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

R = "data/rotation_data.json"
d = json.load(open(R, encoding="utf-8"))
done = []

# ── 생존 ──
sv = d["Hunter"]["specs"].get("Survival")
if sv:
    b = sv.get("builds") or {}
    for k in b:
        if "파수" in k:
            note = b[k].get("hero_note") or ""
            add = "★레이드 신화 top100 채택 0/879 (실측) — 쐐기·트라이 전용. 레이드 광역 빌드도 전부 무리의 지도자가 씁니다.★"
            if "0/879" not in note:
                b[k]["hero_note"] = (add + " " + note).strip()
                done.append("SV 파수꾼 0명 명시")
        if "무리" in k:
            note = b[k].get("hero_note") or ""
            add = ("★빌드 3분화(실측 879명): ①광역 표준 = 치명적 보정+일당백(71% — 선봉대·바엘고어·벨로렌·우주의 왕관 사실상 전원) "
                   "②순단일 = 기습의 이점+쌍둥이 송곳니(보라시우스 61%, top20 70%) "
                   "③혼합단일 = 기습의 이점+일당백·쌍송곳니 없음(르우라 최다 빌드 39%). "
                   "'단일=쌍둥이 송곳니'가 아니라 보라시우스형 순단일만 쌍송곳니 — 르우라·카이메루스 단일은 ③이 다수.★")
            if "빌드 3분화" not in note:
                b[k]["hero_note"] = (note + " " + add).strip()
                done.append("SV 빌드 3분화")

# ── 정술 ──
ele = d["Shaman"]["specs"].get("Elemental")
if ele:
    b = ele.get("builds") or {}
    if "기본" in b:
        note = b["기본"].get("hero_note") or ""
        add = ("★이 탭 = 폭풍인도자 단일형(실측 533명 중 99.8%가 같은 빌드 — 융합+피뢰침+정기 작렬). "
               "보스별 영웅특성(전체/top20): 폭풍인도자 = 르우라 94·아베르지안 92·카이메루스 86·보라시우스 83·우주의 왕관 76 / "
               "선견자 = 선봉대 99(top20 전원)·바엘고어 91(top20 19/20), 살라다르는 52:45 경합(top20은 선견자 13). "
               "선견자는 내부 3빌드로 갈림 — 순광역 불꽃(선봉대·바엘고어), 융합 하이브리드(벨로렌 45%), 융합 무분노(살라다르 29%). "
               "선견자 로테이션 정식 탭은 상태표 채굴 후 추가 예정(이벤트 590킬 수집 완료).★")
        if "폭풍인도자 단일형" not in note:
            b["기본"]["hero_note"] = (note + " " + add).strip()
            done.append("Ele 영웅 축+선견자 요약")
    if isinstance(ele.get("stat"), str) and "정기 작렬·천둥 빌드" in ele["stat"]:
        ele["stat"] = ele["stat"].replace(
            "정기 작렬·천둥 빌드 따라 변동",
            "빌드 따라 변동 — 실제 축은 영웅특성(폭풍인도자=천둥) × 선견자 내 융합/무융합(정기 작렬 vs 대지 충격)")
        done.append("Ele stat 축 보정")

json.dump(d, open(R, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("완료:", done)
