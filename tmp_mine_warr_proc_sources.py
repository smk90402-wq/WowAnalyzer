# -*- coding: utf-8 -*-
"""분노/무기 전사 프록/스킬 강화 전수 인벤토리 — 특성(스펙+영웅+정점)·티어 세트·장신구.

BM/냉법판(tmp_mine_proc_sources.py)·고통판(tmp_mine_aff_proc_sources.py)과 같은 방식.
버튼이 다른 스킬로 바뀌는 효과는 task1_button_swap_map 섹션에 전수 수집
(플레이북 §3 '버튼 변신 전수 확인' 게이트) — 전사는
막무가내(피의 갈증→피범벅·분노의 강타→분쇄의 타격, 무희 창 한정)·
우레 작렬/폭풍의 화신(천둥벼락→우레 작렬, 산왕)·
전쟁의 지배자(격돌→영웅의 일격, 무기 정점)·
급살/대학살(마무리 일격 조건 해제 — 변신 아닌 버튼 활성화형)·
CHOICE 투신↔칼날폭풍(분노)·칼날폭풍↔쇠날발톱(무기)이 대상.

입력(로컬 캐시, API 호출 최소화):
  data/talent_trees.json (Warrior/Fury·Warrior/Arms) — 공식 한글명/설명
  data/fury_talent_splits.json / arms_talent_splits.json — 오늘자(2026-07-10) 893/887명 채택률(재계산 안 함)
  data/rankings_zone46_mythic_dps_top100.csv + v2_cache_player_fight.json — 티어 피스·장신구 착용 분포
  data/spell_db.json — 버프 ID → 한글명
  data/fury_proc_discipline.json / arms_proc_discipline.json — 프록 규율 실측(소모율/지연)
  이벤트 캐시(세션 스크래치패드, EVENTS_DIR): fury_cd_events.json / arms_cd_events.json (각 296킬 casts+buffs)

외부(Blizzard API만, WCL 안 씀):
  장신구 툴팁(item/{id}) + 티어 세트 보너스 주문 설명(spell/{id}, ko_KR).
  세트 보너스 주문 ID는 /data/wow/spell 대역 스캔으로 확인해 둔 값을 하드코딩:
    전사 무기 12.0(밤의 종결자의 분노): 2세트 1264875 / 4세트 1264876
    전사 분노 12.0(밤의 종결자의 분노): 2세트 1264877 / 4세트 1264878
  (item-set/1990 엔드포인트는 무기 문구만 반환 — 냉법 때와 같은 증상이라 주문 쪽을 씀.)
  API 실패 시 FALLBACK_TEXT 사용(2026-07-11 응답 원문).

출력(신규 파일만): data/proc_sources_fury.json, data/proc_sources_arms.json
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).parent
DATA = ROOT / "data"
EVENTS_DIR = Path(os.environ.get(
    "PROC_EVENTS_DIR",
    r"C:\Users\MKSEORTV\AppData\Local\Temp\claude"
    r"\C--Users-MKSEORTV-Desktop-WowAnalyzer"
    r"\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad"))

TIER_SET_ID = 1990  # 밤의 종결자의 분노 (item 249952 preview_item.set 실측)
TIER_ITEM_IDS = {249950, 249951, 249952, 249953, 249955}
TIER_SPELLS = {"Fury": {2: 1264877, 4: 1264878}, "Arms": {2: 1264875, 4: 1264876}}

TRINKET_IDS = {"Fury": [249343, 249342], "Arms": [249342, 249343, 260235]}

# API 다운 대비 백업(2026-07-11 Blizzard API 응답 원문, 확인됨)
FALLBACK_TEXT = {
    1264875: "필사의 일격과 회전베기의 공격력이 5%만큼 증가합니다. 거인의 강타가 받는 피해를 5%만큼 추가로 증가시킵니다.",
    1264876: "거인의 강타에 영향을 받는 대상에게 필사의 일격 또는 3명 이상의 대상에게 적중하는 회전베기로 피해를 입히면, "
             "해당 대상에게 부여된 거인의 강타의 지속시간이 1.0초만큼 증가합니다.",
    1264877: "광란의 공격력이 10%만큼, 오딘의 격노의 공격력은 10%만큼 증가합니다.",
    1264878: "광란이 오딘의 격노의 재사용 대기시간을 2.5초만큼 감소시키고, 오딘의 격노의 공격력은 10%만큼 증가시킵니다.",
}
FALLBACK_ITEM_TEXT = {
    249343: "착용 효과: 공격 및 치유 능력 사용 시 일정 확률로 12초 동안 알른시야가 부여됩니다. "
            "효과가 활성화된 동안 주문 및 능력 시전 시 불안정한 알른멸시를 현신시켜 12초 동안 지능이 2만큼 증가합니다. "
            "여러 번 사용 시 효과가 중첩됩니다.",
    249342: "착용 효과: 공격 시 일정 확률로 치명타 및 극대화가 83만큼 증가하고 크기가 커집니다. 이 효과는 12초에 걸쳐 사라집니다.",
    260235: "착용 효과: 꽁지깃의 암울로 치명타 및 극대화가 30만큼 증가하며, 60초에 걸쳐 감소한 후 완전한 어둠으로 돌아갑니다. "
            "또한 전투 중이 아닐 때 꽁지깃의 힘이 재생됩니다. / "
            "사용 효과: 전투 중이 아닐 때 꽁지깃의 양면성을 일깨워 광휘의 꽁지깃으로 변신시킵니다. (5분 후 재사용 가능)",
}


def get_blizzard():
    try:
        sys.path.insert(0, str(ROOT))
        from blizzard import Blizzard
        return Blizzard()
    except Exception as e:
        print(f"[경고] Blizzard API 클라이언트 사용 불가: {e}", flush=True)
        return None


def spell_desc(cli, sid):
    if cli:
        try:
            d = cli.get(f"/data/wow/spell/{sid}")
            if d and d.get("description"):
                return d["description"]
        except Exception:
            pass
    return FALLBACK_TEXT.get(sid, "확인 불가")


def item_tooltip(cli, iid):
    if cli:
        try:
            d = cli.get(f"/data/wow/item/{iid}")
            if d:
                texts = [sp.get("description") for sp in (d.get("preview_item", {}).get("spells") or [])]
                texts = [t for t in texts if t]
                if texts:
                    return d.get("name"), " / ".join(texts)
        except Exception:
            pass
    return None, FALLBACK_ITEM_TEXT.get(iid, "확인 불가")


def load_samples(spec):
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    out, seen = [], set()
    for r in rows:
        if r["class"] != "Warrior" or r["spec"] != spec:
            continue
        key = f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}'
        if key in seen:
            continue
        seen.add(key)
        p = pf.get(key)
        if isinstance(p, dict) and p.get("gear"):
            out.append(p)
    return out


def tier_piece_distribution(samples):
    dist = Counter()
    for p in samples:
        n = sum(1 for g in p.get("gear", []) if g.get("id") in TIER_ITEM_IDS)
        dist[min(n, 5)] += 1
    return dict(sorted(dist.items()))


def trinket_counts(samples):
    c = Counter()
    for p in samples:
        for g in p.get("gear", []):
            if g.get("slot") in (12, 13):
                c[g["id"]] += 1
    return c


def load_events(fname):
    return json.load(open(EVENTS_DIR / fname, encoding="utf-8"))


def buff_prevalence(events):
    prev = Counter()
    for v in events.values():
        for i in set(b[1] for b in v.get("buffs", []) if b[2] == "applybuff"):
            prev[i] += 1
    return prev


def cast_counts(events, ids):
    tot, kills = Counter(), Counter()
    for v in events.values():
        seen = set()
        for c in v.get("casts", []):
            if c[1] in ids:
                tot[c[1]] += 1
                seen.add(c[1])
        for i in seen:
            kills[i] += 1
    return tot, kills


def main():
    sdb = json.load(open(DATA / "spell_db.json", encoding="utf-8"))

    def buff_name(i):
        return (sdb.get(str(i)) or {}).get("name_ko")

    cli = get_blizzard()

    meta_common = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generated_by": "tmp_mine_warr_proc_sources.py",
        "zone": 46, "difficulty": "mythic",
        "inputs": ("talent_trees.json(Warrior/Fury·Arms) + fury/arms_talent_splits.json(2026-07-10 채택률) "
                   "+ v2_cache_player_fight.json(티어/장신구) + fury/arms_proc_discipline.json(프록 규율 실측) "
                   "+ 이벤트 캐시(각 296킬 casts/buffs) + Blizzard API(장신구/세트 툴팁 ko_KR)"),
        "rotation_impact_기준": "추적 필요=버프를 보고 플레이가 바뀜 / 오프너 정렬=시작 타이밍에 맞춰 누름 / 무관=자동이라 관리 불필요",
        "숫자_읽는_법": "adoption은 상위권 표본 중 채택 비율, observed pct는 몇 %의 킬 로그에서 그 버프가 실제로 떴는지. "
                    "영웅트리 종속 노드는 '해당 영웅 채택자 안에서의 비율'을 by_hero로 병기.",
        "naming": "스킬·특성·버프명은 talent_trees.json / spell_db.json 공식 한글명만 사용.",
        "no_wcl_api": True,
    }

    # ================================================================ 분노
    fury_samples = load_samples("Fury")
    fury_splits = json.load(open(DATA / "fury_talent_splits.json", encoding="utf-8"))
    fury_events = load_events("fury_cd_events.json")
    fury_prev = buff_prevalence(fury_events)
    n_fury = len(fury_samples)
    nk_f = len(fury_events)
    fury_hero = fury_splits["hero_tree"]["total"]  # {학살자: 470, 산왕: 423}
    print(f"분노 표본 {n_fury}명 (학살자 {fury_hero['학살자']} : 산왕 {fury_hero['산왕']}) / 이벤트 캐시 {nk_f}킬", flush=True)

    def obs_f(*ids):
        return [{"id": i, "name": buff_name(i), "kills": fury_prev.get(i, 0),
                 "pct": round(fury_prev.get(i, 0) / nk_f * 100)} for i in ids]

    fpd = json.load(open(DATA / "fury_proc_discipline.json", encoding="utf-8"))["segments"]["all"]

    def adoption_f(node_id):
        k = str(node_id)
        un = fury_splits["build_uniformity"]["unanimous_nodes"]
        vn = fury_splits["variable_nodes"]
        ap = fury_splits["apex_talent"]
        if k in un:
            return f"{n_fury}/{n_fury} (100%, 전원)"
        if k in ap:
            return f"{round(ap[k]['rate'] * n_fury)}/{n_fury} ({round(ap[k]['rate'] * 100)}%)"
        if k in vn:
            v = vn[k]
            bh = v.get("by_hero") or {}
            bh_s = " · ".join(f"{h} {round(r * 100)}%" for h, r in bh.items())
            return f"{round(v['overall_rate'] * n_fury)}/{n_fury} ({round(v['overall_rate'] * 100)}%) — {bh_s}"
        return "0% (미채택)"

    fury_rows = [
        # ---- 기본 메커니즘 (특성 아님 — 스펙 핵심) ----
        {"source": "기본(전문화 핵심)", "name": "격노", "spell_id": 184362,
         "effect": "피의 갈증이 30%의 확률로, 광란·오딘의 격노가 100%의 확률로 격노 상태를 부여합니다. "
                   "격노 중 가속 증가(+광포한/강대한 격노 특성 보너스, 자동 공격 무빗나감 등 다수 특성이 격노 조건).",
         "adoption": "기본 제공(특성 아님)",
         "observed_buff_id": obs_f(184362),
         "measured": {"uptime_pct_med": fpd["q1_enrage"]["uptime_pct_med"],
                      "gaps_per_min": fpd["q1_enrage"]["gaps_per_min"],
                      "drop_to_rampage_s_med": fpd["q1_enrage"]["drop_to_rampage_s_med"]},
         "rotation_impact": "추적 필요",
         "note": "분노의 기준점 버프 — 상위권 업타임 중앙 98.1%. 끊기면 1~2글쿨(중앙 2.5초) 안에 광란으로 복구가 규율. "
                 "전쟁 물감·혼돈의 집중·무자비함·광포한 격노 등 다수 특성이 '격노 중'에만 작동."},
        # ---- 특성(분노 전문화) ----
        {"source": "특성(분노 전문화)", "node_id": 90430, "name": "급살", "spell_id": 29725,
         "effect": "공격 시 일정 확률로 다음 마무리 일격을 분노를 소모하지 않고 대상의 생명력에 관계없이 사용할 수 있습니다. "
                   "이 일격은 40의 분노를 소모한 것과 같은 피해를 입힙니다.",
         "adoption": adoption_f(90430),
         "observed_buff_id": obs_f(52437),
         "measured": {"gains_per_min": fpd["q2_sudden_death"]["gains_per_min"],
                      "consumed_pct": fpd["q2_sudden_death"]["consumed_pct"],
                      "consume_delay_s_med": fpd["q2_sudden_death"]["consume_delay_s_med"],
                      "waste_pct": fpd["q2_sudden_death"]["waste_pct"]},
         "rotation_impact": "추적 필요",
         "note": "프록 버프 52437(실측 확정). 뜨면 마무리 일격이 공짜+체력 조건 무시 — 상위권 소모율 83.7%, 지연 중앙 1.88초. "
                 "낭비는 대부분 자연만료(11건)가 아니라 refresh 덮어씀(1036건). 학살자 임박한 파멸이 추가 공급원."},
        {"source": "특성(분노 전문화)", "node_id": 90388, "name": "막무가내", "spell_id": 396749,
         "effect": "무모한 희생을 활성화하면 50의 분노를 생성합니다. 또한 무모한 희생이 활성화된 동안 분노의 강타와 피의 갈증이 "
                   "각각 분쇄의 타격과 피범벅으로 강화됩니다.",
         "adoption": adoption_f(90388),
         "observed_buff_id": obs_f(1719),
         "rotation_impact": "추적 필요",
         "note": "★버튼 변신 노드★ — 상세는 task1 참고. 무모한 희생(무희) 창 안에서 피의 갈증→피범벅(335096)·"
                 "분노의 강타→분쇄의 타격(335097) 완전 변신(실측 확정). 무희 창=전투시간 36.7%, 칼날폭풍을 창 안에 넣는 게 규율(90%)."},
        {"source": "특성(분노 전문화)", "node_id": 90390, "name": "분노의 강타 연마", "spell_id": 383854,
         "effect": "분노의 강타가 2회 충전되고, 사용 시 25%의 확률로 재사용 대기시간이 즉시 초기화됩니다.",
         "adoption": adoption_f(90390),
         "observed_buff_id": obs_f(280270),
         "rotation_impact": "무관",
         "note": "초기화 프록은 버튼 충전이 다시 차는 것으로 보임 — 별도 버프를 볼 필요 없음(로그의 280270은 확인용). "
                 "천벌과 분노(학살자 91% 채택)가 격노 중 초기화 확률 +10%를 얹음."},
        {"source": "특성(분노 전문화)", "node_id": 90427, "name": "소용돌이 연마", "spell_id": 12950,
         "effect": "소용돌이 사용 시 다음 4번의 단일 대상 공격이 최대 4명의 대상에게 추가로 적중하여 65%의 피해를 입힙니다. "
                   "소용돌이가 3의 분노를 생성하고 적중한 대상 하나당 1의 분노를 추가로 생성합니다. 최대 8의 분노를 생성합니다.",
         "adoption": adoption_f(90427),
         "observed_buff_id": obs_f(85739),
         "rotation_impact": "추적 필요(광역 한정)",
         "note": "광역에서 소용돌이 버프(중첩 4)를 유지하며 단일기를 돌리는 전사 전통 광역 규칙 — 버프가 꺼지면 소용돌이로 재충전. "
                 "단일 대상에서는 볼 일 없음."},
        {"source": "특성(분노 전문화)", "node_id": 90399, "name": "신선한 고기", "spell_id": 215568,
         "effect": "대상에게 처음 피의 갈증을 사용하면 항상 격노 상태가 됩니다. 또한 격노가 발동할 확률이 15%만큼 증가합니다.",
         "adoption": adoption_f(90399),
         "observed_buff_id": None,
         "rotation_impact": "무관",
         "note": "오프너 첫 피의 갈증이 확정 격노 — 자동이라 관리 없음. 격노 업타임 98%의 밑바탕."},
        {"source": "특성(분노 전문화)", "node_id": 90406, "name": "광기", "spell_id": 335077,
         "effect": "광란 사용 시 12초 동안 가속이 2%만큼 증가합니다. 이 효과는 여러 번 중첩해서 사용할 수 있습니다.",
         "adoption": adoption_f(90406),
         "observed_buff_id": obs_f(335082),
         "rotation_impact": "무관",
         "note": "광란만 제때 누르면 알아서 쌓이는 가속 중첩 — 광란 간격 실측 중앙 2.89초라 사실상 상시 유지."},
        {"source": "특성(분노 전문화)", "node_id": 109969, "name": "피의 향기", "spell_id": 1265355,
         "effect": "광란이 다음 피의 갈증의 공격력을 10%만큼 증가시킵니다. 최대 2번까지 중첩됩니다.",
         "adoption": adoption_f(109969),
         "observed_buff_id": obs_f(1265399),
         "rotation_impact": "무관",
         "note": "광란→피의 갈증 순환에서 자동으로 소모되는 강화 — 보고 할 행동 없음."},
        {"source": "특성(분노 전문화)", "node_id": 90401, "name": "혈행성 전이", "spell_id": 385703,
         "effect": "피의 갈증 사용 시 시전자의 출혈 효과가 8초 동안 20%의 추가 피해를 입힙니다.",
         "adoption": adoption_f(90401),
         "observed_buff_id": obs_f(1265406),
         "rotation_impact": "무관",
         "note": "피의 갈증은 어차피 쿨마다 누르므로 사실상 상시 버프 — 관리 불필요."},
        {"source": "특성(분노 전문화)", "node_id": 90410, "name": "대학살", "spell_id": 206315,
         "effect": "남은 생명력이 35% 미만인 대상에게 마무리 일격을 시전할 수 있으며, 재사용 대기시간이 1.5초만큼 감소합니다.",
         "adoption": adoption_f(90410),
         "observed_buff_id": None,
         "rotation_impact": "추적 필요(처형 구간)",
         "note": "보스 35% 미만부터 마무리 일격 버튼이 켜짐 — 처형 구간 진입 신호. 급살 프록과 별개로 상시 사용 가능해짐."},
        # ---- 영웅(학살자) ----
        {"source": "영웅(학살자)", "node_id": 94814, "name": "학살자의 지배", "spell_id": 444767,
         "effect": "주 대상에게 공격 시 15%의 확률로 학살자의 일격을 발동시켜 피해를 입히고 집행자 중첩을 얻어 "
                   "12초 동안 마무리 일격의 공격력이 3%만큼 증가합니다. 집행자는 여러 번 중첩됩니다.",
         "adoption": adoption_f(94814),
         "observed_buff_id": obs_f(445584),
         "rotation_impact": "무관",
         "note": "학살자 트리의 뿌리 — 자동 프록. 집행자 중첩(445584)은 마무리 일격을 세게 만들 뿐, 따로 관리할 행동 없음."},
        {"source": "영웅(학살자)", "node_id": 94788, "name": "임박한 파멸", "spell_id": 444769,
         "effect": "학살자의 일격을 3회 사용할 때마다 급살이 부여됩니다. 급살 사용 시 다음 칼날폭풍이 가속화되어 추가로 1회 "
                   "공격을 가합니다. 급살이 100%의 확률로 폭풍을 거두는 자를 100%의 효율로 발동시킵니다.",
         "adoption": adoption_f(94788),
         "observed_buff_id": obs_f(445606),
         "rotation_impact": "무관",
         "note": "급살 프록의 추가 공급원(학살자 전용) — 급살 버프(52437) 하나만 보면 됨. 445606은 3회 카운터 확인용."},
        {"source": "영웅(학살자)", "node_id": 109817, "name": "격렬한 희열", "spell_id": 1270717,
         "effect": "칼날폭풍 사용 시 전투 몰입 상태가 되어, 칼날폭풍이 끝난 후 8초 동안 가속이 15%만큼 증가합니다.",
         "adoption": adoption_f(109817),
         "observed_buff_id": obs_f(1270731),
         "rotation_impact": "무관",
         "note": "칼날폭풍에 자동으로 붙는 가속 — 칼날폭풍을 무희 창 안에 넣는 규율(90%)에 이미 포함되는 보너스."},
        {"source": "영웅(학살자)", "node_id": 94820, "name": "붉은돌격대의 무자비함", "spell_id": 444780,
         "effect": "급살 사용 시 칼날폭풍의 재사용 대기시간이 5초만큼 감소하고, 집행자 중첩 하나당 주 대상에게 압도당함 중첩 1개를 "
                   "부여합니다. 칼날폭풍의 공격력이 20%만큼 증가합니다.",
         "adoption": adoption_f(94820),
         "observed_buff_id": None,
         "rotation_impact": "무관",
         "note": "급살을 제때 소모하면 칼날폭풍이 빨리 돌아오는 구조 — 급살 규율(1~2글쿨 내 소모)에 이미 포함."},
        # ---- 영웅(산왕) ----
        {"source": "영웅(산왕)", "node_id": 94785, "name": "우레 작렬", "spell_id": 435607,
         "effect": "방패 밀쳐내기 및 피의 갈증 사용 시 35%의 확률로 우레 작렬이 부여됩니다. 최대 2번까지 중첩됩니다. "
                   "다음 천둥벼락이 우레 작렬로 변화하여 폭풍충격 피해를 입히고 2의 분노를 생성합니다.",
         "adoption": adoption_f(94785),
         "observed_buff_id": obs_f(435615),
         "rotation_impact": "추적 필요(산왕 한정)",
         "note": "★버튼 변신 노드★ — 상세는 task1 참고. 버프(435615)가 뜨면 천둥벼락 버튼이 우레 작렬로 바뀜 — "
                 "산왕 광란 직전 GCD 최빈 5위(3144회)에 들 만큼 자주 누르는 프록."},
        {"source": "영웅(산왕)", "node_id": 94807, "name": "폭발적인 힘", "spell_id": 437118,
         "effect": "벼락이 15%의 확률로 다음 2회의 피의 갈증이 재사용 대기시간을 발동시키지 않게 합니다.",
         "adoption": adoption_f(94807),
         "observed_buff_id": obs_f(437121),
         "rotation_impact": "무관",
         "note": "피의 갈증 버튼이 그냥 다시 켜짐 — 쿨 돌 때마다 누르는 습관이면 자동으로 소화됨."},
        {"source": "영웅(산왕)", "node_id": 94805, "name": "폭풍의 화신", "spell_id": 437134,
         "effect": "투신 시전 시 우레 작렬이 2중첩 부여되고 천둥벼락의 재사용 대기시간이 초기화됩니다. "
                   "투신이 활성화되지 않은 동안에는 벼락이 10%의 확률로 4초 동안 투신을 활성화시킵니다.",
         "adoption": adoption_f(94805),
         "observed_buff_id": obs_f(107574),
         "rotation_impact": "추적 필요(산왕 한정)",
         "note": "벼락 프록으로 4초짜리 미니 투신이 랜덤하게 켜짐(투신 버프 107574로 표시) — 켜진 동안 벼락 발동 +30%(벼락 특성)·"
                 "전기 축적으로 연장 가능. 본 투신(20초)은 무모한 희생과 동시 사용이 산왕 표준(실측 100%)."},
        # ---- 정점(row 11~12) ----
        {"source": "정점", "node_id": 109968, "row": 11, "name": "집행인의 격노", "spell_id": 1265570,
         "effect": "마무리 일격이 5의 분노를 추가로 생성하고 4초 동안 광란의 공격력이 10%만큼 증가합니다.",
         "adoption": adoption_f(109968),
         "observed_buff_id": obs_f(1265575),
         "rotation_impact": "무관",
         "note": "마무리 일격→광란 순환에서 자동으로 발린 버프 — 보고 할 행동 없음."},
        {"source": "정점", "node_id": 90415, "row": 11, "name": "투신 / 칼날폭풍 (CHOICE)", "spell_id": None,
         "effect": "투신: 거구로 변신하여 모든 공격력이 20%만큼 증가. 20초 지속. / "
                   "칼날폭풍: 5.4초 동안 주위 모든 적에게 물리 피해를 입히는 파괴의 소용돌이.",
         "adoption": adoption_f(90415),
         "observed_buff_id": obs_f(107574, 446035),
         "rotation_impact": "오프너 정렬",
         "note": "★CHOICE로 버튼 자체가 갈림★ — 상세는 task1 참고. 학살자는 100% 칼날폭풍, 산왕은 100% 투신(n=893, 검증 게이트 확정). "
                 "산왕 = 투신+무모한 희생 동시(실측 100%), 학살자 = 칼날폭풍을 무희 창 안(90%)."},
        {"source": "정점", "node_id": 110412, "row": 12, "name": "날뛰는 광전사", "spell_id": 1269308,
         "effect": "광란의 공격력이 10%만큼 증가합니다. 또한 광란 사용 시 광폭화 상태가 되어 8초 동안 힘이 3%만큼 증가합니다. "
                   "광폭화는 여러 번 중첩해서 사용할 수 있습니다.",
         "adoption": adoption_f(110412),
         "observed_buff_id": obs_f(1269349),
         "rotation_impact": "무관",
         "note": "정점 최하단(row12) 유일 노드 — 전원 채택. 광란 간격이 3초 안짝이라 광폭화(1269349)는 알아서 상시 중첩."},
    ]

    # ---- 티어 세트 ----
    dist_f = tier_piece_distribution(fury_samples)
    n2 = sum(v for k, v in dist_f.items() if k >= 2)
    n4 = sum(v for k, v in dist_f.items() if k >= 4)
    fury_rows.append({
        "source": "티어", "item_set_id": TIER_SET_ID, "name": "밤의 종결자의 분노 2세트 (분노 효과)",
        "effect": spell_desc(cli, TIER_SPELLS["Fury"][2]),
        "adoption": f"{n2}/{n_fury} ({round(n2 / n_fury * 100)}%) — 2부위 이상 착용",
        "piece_distribution": dist_f,
        "rotation_impact": "무관",
        "note": "광란·오딘의 격노 수치 강화 — 새 버프·행동 변화 없음.",
        "text_source": "Blizzard API spell 1264877 (item-set 1990 엔드포인트는 무기 문구만 반환 — 주문 대역 스캔으로 확정)",
    })
    fury_rows.append({
        "source": "티어", "item_set_id": TIER_SET_ID, "name": "밤의 종결자의 분노 4세트 (분노 효과)",
        "effect": spell_desc(cli, TIER_SPELLS["Fury"][4]),
        "adoption": f"{n4}/{n_fury} ({round(n4 / n_fury * 100)}%) — 4부위 이상 착용",
        "piece_distribution": dist_f,
        "rotation_impact": "무관",
        "note": "광란이 오딘의 격노 쿨을 깎는 패시브 — 오딘 실효쿨이 표기(45초)보다 짧아지는 이유(실측 갭 27.4초). "
                "'오딘은 쿨 돌 때마다 즉시' 규율의 근거이지 따로 볼 버프는 없음.",
        "text_source": "Blizzard API spell 1264878",
    })

    # ---- 장신구 ----
    tc_f = trinket_counts(fury_samples)
    fury_trinket_defs = [
        (249343, "자동 프록", obs_f(1266686, 1266687), "무관",
         "공격만 하면 알아서 터짐(알른시야 → 시전마다 지능 중첩) — BM·냉법·고통과 같은 장신구, 관리 타이밍 없음."),
        (249342, "자동 프록", obs_f(1262753), "무관",
         "공격 시 일정 확률로 치명타 12초 증가 — 완전 자동, 관리 타이밍 없음. 분노 상위권 95% 착용."),
    ]
    for iid, kind, obs, impact, note in fury_trinket_defs:
        nm, text = item_tooltip(cli, iid)
        fury_rows.append({
            "source": "장신구", "item_id": iid, "name": nm or str(iid),
            "effect": text, "use_type": kind,
            "adoption": f"{tc_f.get(iid, 0)}/{n_fury} ({round(tc_f.get(iid, 0) / n_fury * 100)}%, 착용 데이터 집계)",
            "observed_buff_id": obs, "rotation_impact": impact, "note": note,
        })

    # ---- task1: 버튼 변신 맵 (분노) ----
    tot_f, kills_f = cast_counts(fury_events, [335096, 335097, 435222, 6343, 23881, 85288, 446035, 107574])
    fury_swap = [
        {
            "kind": "버튼 변신(쿨기 창 한정)", "original": "피의 갈증 / 분노의 강타", "becomes": "피범벅 / 분쇄의 타격",
            "node_id": 90388, "talent": "막무가내", "tree": "분노 전문화(row 11)", "spell_id_talent": 396749,
            "official_desc": "무모한 희생이 활성화된 동안 분노의 강타와 피의 갈증이 각각 분쇄의 타격과 피범벅으로 강화됩니다.",
            "condition": "무모한 희생(1719) 활성화 중에만 — 창이 끝나면 원래 버튼으로 복귀.",
            "adoption": adoption_f(90388),
            "measured": {"casts_피범벅_335096": tot_f[335096], "casts_분쇄의_타격_335097": tot_f[335097],
                         "casts_피의_갈증_23881": tot_f[23881], "casts_분노의_강타_85288": tot_f[85288],
                         "inside_window_check": "피범벅+분쇄의 타격 12,401캐스트 중 12,079(97%)가 무희 버프 창 안 — "
                                                "나머지는 창 경계 타이밍. proc_discipline 판정은 '완전 변신(100%)'.",
                         "buff_window_share_pct": 36.7},
            "note": "무희 창(전투시간 36.7%) 동안 두 주력 버튼이 강화판으로 바뀜 — 별도 판단 없이 원래 순환 그대로 누르면 됨. "
                    "피범벅은 출혈 연장(6초) 부가 효과.",
        },
        {
            "kind": "버튼 변신(프록)", "original": "천둥벼락", "becomes": "우레 작렬",
            "node_id": 94785, "talent": "우레 작렬", "tree": "영웅(산왕)", "spell_id_talent": 435607, "spell_id_cast": 435222,
            "official_desc": "방패 밀쳐내기 및 피의 갈증 사용 시 35%의 확률로 우레 작렬이 부여됩니다. 최대 2번까지 중첩됩니다. "
                             "다음 천둥벼락이 우레 작렬로 변화하여 폭풍충격 피해를 입히고 2의 분노를 생성합니다.",
            "condition": "우레 작렬 버프(435615, 최대 2중첩) 보유 중 천둥벼락 버튼이 우레 작렬로 변화. "
                         "폭풍의 화신이 투신 시전 시 2중첩을 즉시 부여.",
            "adoption": adoption_f(94785),
            "measured": {"casts_우레_작렬_435222": tot_f[435222], "casts_천둥벼락_6343": tot_f[6343],
                         "kills_with_cast": f"{kills_f[435222]}/{nk_f} — 산왕 채택 킬(141)과 정확히 일치",
                         "note": "산왕 킬에서 우레 작렬 6,079 vs 천둥벼락 3,681 — 프록판이 더 자주 나갈 만큼 공급이 넉넉함. "
                                 "광란 직전 GCD 최빈 5위."},
            "note": "산왕 전용 핵심 프록 버튼 — 학살자는 이 변신 자체가 없음.",
        },
        {
            "kind": "버튼 활성화(변신 아님)", "original": "마무리 일격(잠김)", "becomes": "마무리 일격(사용 가능)",
            "node_id": 90430, "talent": "급살 (+학살자 임박한 파멸, +대학살)", "tree": "분노 전문화",
            "official_desc": "급살: 공격 시 일정 확률로 다음 마무리 일격을 분노를 소모하지 않고 대상의 생명력에 관계없이 사용할 수 "
                             "있습니다. / 대학살: 남은 생명력이 35% 미만인 대상에게 마무리 일격을 시전할 수 있습니다.",
            "condition": "평시엔 잠긴 버튼이 급살 프록(52437) 또는 대상 체력 35% 미만(대학살)에서 켜짐.",
            "adoption": f"급살 {adoption_f(90430)} / 대학살 {adoption_f(90410)}",
            "measured": {"casts_마무리_일격": tot_f[280735] + tot_f.get(5308, 0),
                         "cast_ids": "280735(주 사용) / 5308(17킬 소수)",
                         "sudden_death": "소모율 83.7%, 지연 중앙 1.88초 (proc_discipline)"},
            "note": "변신은 아니지만 '버튼이 켜지는' 유형 — 추적 버프 1순위(급살 52437). 광란 직전 GCD 최빈 1위(5,127회)가 마무리 일격.",
        },
        {
            "kind": "버튼 자체가 갈림(CHOICE)", "original": "투신", "becomes": "칼날폭풍",
            "node_id": 90415, "tree": "분노 전문화(row 11)",
            "options": [
                {"talent": "칼날폭풍", "spell_id": 227847,
                 "official_desc": "멈출 수 없는 파괴의 소용돌이가 되어 5.4초 동안 주위 모든 적에게 물리 피해를 입힙니다.",
                 "adoption": {"share": 0.526, "by_hero": "학살자 100%"}},
                {"talent": "투신", "spell_id": 107574,
                 "official_desc": "거구로 변신하여 모든 공격력이 20%만큼 증가하고 광역 공격으로 받는 피해가 5%만큼 감소합니다. 20초 동안 지속됩니다.",
                 "adoption": {"share": 0.474, "by_hero": "산왕 100%"}},
            ],
            "measured": {"casts_칼날폭풍_446035": tot_f[446035], "casts_투신_107574": tot_f[107574],
                         "note": "칼날폭풍 시전은 스펠ID 446035로 찍힘(트리 표기 227847은 0캐스트 — 실측 확정). "
                                 "킬 분포(155/141)가 영웅특성 분포와 정확히 일치."},
            "note": "영웅특성이 곧 버튼 구성 — 학살자 가이드에 투신을 넣으면 안 되고(검증 게이트 확정), "
                    "산왕 가이드는 투신+무모한 희생 동시 사용(실측 100%)을 못 박아야 함.",
        },
    ]

    out_fury = {
        "_meta": {**meta_common, "spec": "Warrior|Fury", "sample_n": n_fury, "event_kills": nk_f,
                  "hero_split": fury_hero},
        "sources": fury_rows,
        "task1_button_swap_map": fury_swap,
    }

    # ================================================================ 무기
    arms_samples = load_samples("Arms")
    arms_splits = json.load(open(DATA / "arms_talent_splits.json", encoding="utf-8"))
    arms_events = load_events("arms_cd_events.json")
    arms_prev = buff_prevalence(arms_events)
    n_arms = len(arms_samples)
    nk_a = len(arms_events)
    arms_hero = arms_splits["hero_tree"]["total"]
    print(f"무기 표본 {n_arms}명 (학살자 {arms_hero['학살자']} : 거신 {arms_hero['거신']}) / 이벤트 캐시 {nk_a}킬", flush=True)

    def obs_a(*ids):
        return [{"id": i, "name": buff_name(i), "kills": arms_prev.get(i, 0),
                 "pct": round(arms_prev.get(i, 0) / nk_a * 100)} for i in ids]

    apd = json.load(open(DATA / "arms_proc_discipline.json", encoding="utf-8"))["segments"]["all"]

    def adoption_a(node_id):
        k = str(node_id)
        un = arms_splits["build_uniformity"]["unanimous_nodes"]
        vn = arms_splits["variable_nodes"]
        ap = arms_splits["apex_talent"]
        if k in un:
            return f"{n_arms}/{n_arms} (100%, 전원)"
        if k in ap:
            return f"{round(ap[k]['rate'] * n_arms)}/{n_arms} ({round(ap[k]['rate'] * 100)}%)"
        if k in vn:
            v = vn[k]
            bh = v.get("by_hero") or {}
            bh_s = " · ".join(f"{h} {round(r * 100)}%" for h, r in bh.items())
            return f"{round(v['overall_rate'] * n_arms)}/{n_arms} ({round(v['overall_rate'] * 100)}%) — {bh_s}"
        return "0% (미채택)"

    arms_rows = [
        # ---- 정점(row 12) — 무기 추적 1순위 ----
        {"source": "정점", "node_id": 110407, "row": 12, "name": "전쟁의 지배자", "spell_id": 1269314,
         "effect": "단일 대상 근접 능력 사용 시 일정 확률로 격돌이 영웅의 일격으로 강화됩니다. "
                   "격돌에 영향을 주는 모든 수정치와 특성이 영웅의 일격에도 영향을 줍니다.",
         "adoption": adoption_a(110407),
         "observed_buff_id": obs_a(1269391, 1269394, 1292058),
         "measured": {"gains_per_min": apd["q5_heroic_strike_proc"]["gains_per_min"],
                      "consumed_pct": apd["q5_heroic_strike_proc"]["consumed_pct"],
                      "consume_delay_s_med": apd["q5_heroic_strike_proc"]["consume_delay_s_med"],
                      "next_gcd_hs_pct": apd["q5_heroic_strike_proc"]["next_gcd_hs_pct"],
                      "next_gcd_ms_pct": apd["q5_heroic_strike_proc"]["next_gcd_ms_pct"]},
         "rotation_impact": "추적 필요",
         "note": "★버튼 변신 노드★ — 상세는 task1 참고. 프록 버프는 1269391(실측 확정 — 영웅의 일격 8,847캐스트의 99.8%가 "
                 "이 버프 제거와 ±150ms 일치). 같은 이름의 1269394와 영웅의 힘(1292058)은 영웅의 일격을 쓸 때마다 쌓이는 "
                 "누적 중첩형 별개 버프(효과문은 API 미제공 — 실측으로만 확인). 프록 후 1~2글쿨 안 소모(가급적 즉시)가 규율."},
        # ---- 특성(무기 전문화) ----
        {"source": "특성(무기 전문화)", "node_id": 90274, "name": "급살", "spell_id": 29725,
         "effect": "공격 시 일정 확률로 다음 마무리 일격을 분노를 소모하지 않고 대상의 생명력에 관계없이 사용할 수 있습니다. "
                   "이 일격은 40의 분노를 소모한 것과 같은 피해를 입힙니다.",
         "adoption": adoption_a(90274),
         "observed_buff_id": obs_a(52437),
         "measured": {"gains_per_min": apd["q6_sudden_death"]["gains_per_min"],
                      "consumed_pct": apd["q6_sudden_death"]["consumed_pct"],
                      "consume_delay_s_med": apd["q6_sudden_death"]["consume_delay_s_med"],
                      "waste_pct": apd["q6_sudden_death"]["waste_pct"]},
         "rotation_impact": "추적 필요",
         "note": "분노와 같은 프록 버프 52437. 소모율 84.5%, 지연 중앙 1.85초. 마무리 일격 캐스트 ID는 "
                 "학살자 281000 / 거신 163201로 갈림(실측 확정). 낭비는 거신 19.8%(쇄파 채널 개입) vs 학살자 0.9%."},
        {"source": "특성(무기 전문화)", "node_id": 90282, "name": "전술가", "spell_id": 184783,
         "effect": "분노를 소모하는 공격 사용 시 30%의 확률로 제압이 충전됩니다. "
                   "사용 능력의 분노 소모량이 0으로 감소한 경우에도 이 효과는 적용됩니다.",
         "adoption": adoption_a(90282),
         "observed_buff_id": obs_a(199854),
         "rotation_impact": "무관",
         "note": "제압 버튼 충전이 다시 차는 것으로 보임(제압 연마로 2충전이라 넘침도 완충) — 별도 버프 감시 불필요. "
                 "제압→필사 교차가 거신에서만 강한(48%/63%) 이유의 뿌리."},
        {"source": "특성(무기 전문화)", "node_id": 90445, "name": "집행자의 정밀함", "spell_id": 386634,
         "effect": "마무리 일격 사용 시 다음 필사의 일격의 공격력이 35%만큼 증가합니다. 최대 2번까지 중첩됩니다.",
         "adoption": adoption_a(90445),
         "observed_buff_id": obs_a(386633),
         "rotation_impact": "무관",
         "note": "마무리 일격→필사의 일격 순환에서 자동 소모 — 처형 구간에서 마무리 일격 연타 사이에 필사를 끼우는 근거이지만 "
                 "버프를 보며 판단할 건 없음."},
        {"source": "특성(무기 전문화)", "node_id": 90439, "name": "치명적 공격", "spell_id": 383703,
         "effect": "필사의 일격이 50%의 확률로 대상에게 척살의 징표를 부여하며, 최대 5번까지 중첩됩니다. "
                   "척살의 징표가 부여된 적에게 다음 마무리 일격 사용 시 중첩 하나당 추가 물리 피해를 입힙니다.",
         "adoption": adoption_a(90439),
         "observed_buff_id": None,
         "rotation_impact": "무관",
         "note": "학살자 전용(거신 0%). 대상에게 쌓이는 디버프라 플레이어 버프 창에 안 뜸 — 마무리 일격이 알아서 정산, 관리 불필요."},
        {"source": "특성(무기 전문화)", "node_id": 90273, "name": "마무리 일격 연마", "spell_id": 316405,
         "effect": "적이 살아남으면 마무리 일격의 재사용 대기시간이 발생하지 않고 소모한 분노의 10%를 돌려받습니다.",
         "adoption": adoption_a(90273),
         "observed_buff_id": None,
         "rotation_impact": "무관",
         "note": "학살자 전용(거신 0%). 처형 구간 마무리 일격 연타(분당 5.95→13.51)의 구조적 근거 — 버튼이 그냥 계속 켜져 있음."},
        {"source": "특성(무기 전문화)", "node_id": 90291, "name": "대학살", "spell_id": 281001,
         "effect": "남은 생명력이 35% 미만인 대상에게 마무리 일격을 시전할 수 있습니다.",
         "adoption": adoption_a(90291),
         "observed_buff_id": None,
         "rotation_impact": "추적 필요(처형 구간)",
         "note": "학살자 100% / 거신 0% — 학살자는 35%부터, 거신은 기본 규칙대로 20%부터 처형 구간. "
                 "보스 체력 구간이 곧 순환 전환 신호(분쇄 도포 중단 포함)."},
        {"source": "특성(무기 전문화)", "node_id": 90438, "name": "유혈", "spell_id": 383154,
         "effect": "분쇄와 치명상의 출혈 효과 지속시간이 33%만큼, 치명타 및 극대화율이 5%만큼 증가합니다. "
                   "분쇄를 배웠을 경우, 필사의 일격 사용 시 생명력이 35% 미만인 대상에게 분쇄를 겁니다.",
         "adoption": adoption_a(90438),
         "observed_buff_id": None,
         "rotation_impact": "무관",
         "note": "처형 구간에서 분쇄 수동 도포를 끊는(실측: 59.8%가 70% 지점 전 중단) 근거 — 필사의 일격이 알아서 발라줌."},
        {"source": "특성(무기 전문화)", "node_id": 92615, "name": "전투군주", "spell_id": 386630,
         "effect": "제압 사용 시 35%의 확률로 필사의 일격의 재사용 대기시간이 초기화됩니다. "
                   "또한 다음 필사의 일격의 자원 소모량이 33%만큼 감소합니다.",
         "adoption": adoption_a(92615),
         "observed_buff_id": obs_a(386631, 386632),
         "rotation_impact": "무관",
         "note": "거신 전용(학살자 0%). 필사의 일격 버튼이 다시 켜지는 것으로 충분 — 거신의 제압→필사 교차(48%/63%)를 만드는 축."},
        {"source": "특성(무기 전문화)", "node_id": 109680, "name": "무예 기량", "spell_id": 1273062,
         "effect": "제압 및 격돌 사용 시 다음 필사의 일격의 공격력이 5%만큼 증가합니다. 최대 3번까지 중첩됩니다.",
         "adoption": adoption_a(109680),
         "observed_buff_id": obs_a(316440),
         "rotation_impact": "무관",
         "note": "학살자 99% 채택 — 순환에서 자동으로 쌓이고 자동으로 소모. 관리할 행동 없음."},
        {"source": "특성(무기 전문화)", "node_id": 94787, "name": "용맹한 후속타 (CHOICE, vs 기회주의자)", "spell_id": 444773,
         "effect": "필사의 일격이 치명타 및 극대화로 적중하면 다음 필사의 일격의 공격력이 20%만큼 증가합니다.",
         "adoption": adoption_a(94787) + " — 선택지 내 용맹한 후속타 97%",
         "observed_buff_id": obs_a(458689),
         "rotation_impact": "무관",
         "note": "학살자 전용 노드. 크리 여부에 따라 자동으로 붙는 강화 — 기회주의자(3%)는 이단픽."},
        {"source": "특성(무기 전문화)", "node_id": 109682, "name": "부수적인 피해", "spell_id": 334779,
         "effect": "휩쓸기 일격의 지속시간 동안 능력을 사용해 두 번째 대상에게 피해를 입히면, 다음 회전베기 또는 소용돌이의 "
                   "공격력이 25%만큼 증가합니다. 최대 3번까지 중첩됩니다.",
         "adoption": adoption_a(109682),
         "observed_buff_id": obs_a(334783),
         "rotation_impact": "무관",
         "note": "거신 광역 패키지의 일부 — 광역 순환 중 자동으로 쌓임. 버프 보고 순서를 바꿀 일은 없음."},
        {"source": "특성(무기 전문화)", "node_id": 109683, "name": "궤멸적인 연계 (CHOICE, vs 전술적 우위)", "spell_id": 1261056,
         "effect": "거인의 강타 사용 시 다음 20초 동안 사용하는 2회의 회전베기가 재사용 대기시간을 발생시키지 않습니다.",
         "adoption": adoption_a(109683) + " — 선택지 내 궤멸적인 연계 97%",
         "observed_buff_id": obs_a(1261189),
         "rotation_impact": "무관",
         "note": "거신 전용. 거인의 강타 창 안에서 회전베기가 공짜로 이어짐 — 거강 창 정렬 규율에 이미 포함."},
        {"source": "특성(무기 전문화)", "node_id": 109686, "name": "광범위한 타격 (CHOICE, vs 몸풀기였을 뿐)", "spell_id": 1261049,
         "effect": "거인의 강타가 휩쓸기 일격을 부여합니다.",
         "adoption": adoption_a(109686) + " — 거신 100%는 광범위한 타격, 학살자는 55%가 이 노드(보스별 광역 패키지 스왑)",
         "observed_buff_id": obs_a(260708),
         "rotation_impact": "추적 필요(광역 한정)",
         "note": "휩쓸기 일격 버프(260708) 중 단일기가 옆 대상까지 침 — 광역에서 이 버프 창에 맞춰 단일기를 눌러야 함. "
                 "수동 시전(1,014회)과 거강 프록 부여가 병행됨(실측). 벨로렌 등 광역 보스에서 학살자도 99% 채택하는 스왑축."},
        # ---- 영웅(학살자) ----
        {"source": "영웅(학살자)", "node_id": 94814, "name": "학살자의 지배", "spell_id": 444767,
         "effect": "주 대상에게 공격 시 15%의 확률로 학살자의 일격을 발동시켜 피해를 입히고 집행자 중첩을 얻어 "
                   "12초 동안 마무리 일격의 공격력이 3%만큼 증가합니다.",
         "adoption": adoption_a(94814),
         "observed_buff_id": obs_a(445584),
         "rotation_impact": "무관",
         "note": "자동 프록 — 집행자 중첩은 마무리 일격 강화용, 관리할 행동 없음."},
        {"source": "영웅(학살자)", "node_id": 94788, "name": "임박한 파멸", "spell_id": 444769,
         "effect": "학살자의 일격을 3회 사용할 때마다 급살이 부여됩니다. 급살 사용 시 다음 칼날폭풍이 가속화됩니다.",
         "adoption": adoption_a(94788),
         "observed_buff_id": obs_a(445606),
         "rotation_impact": "무관",
         "note": "급살 프록 추가 공급원 — 볼 버프는 급살(52437) 하나면 충분."},
        {"source": "영웅(학살자)", "node_id": 109817, "name": "격렬한 희열", "spell_id": 1270717,
         "effect": "칼날폭풍 사용 시 전투 몰입 상태가 되어, 칼날폭풍이 끝난 후 8초 동안 가속이 15%만큼 증가합니다.",
         "adoption": adoption_a(109817),
         "observed_buff_id": obs_a(1270731),
         "rotation_impact": "무관",
         "note": "칼날폭풍에 자동으로 붙는 가속 — 칼폭을 거강 창 안(90%)·투신 창 안(82%)에 정렬하는 규율에 포함되는 보너스."},
        # ---- 영웅(거신) ----
        {"source": "영웅(거신)", "node_id": 94818, "name": "쇄파", "spell_id": 436358,
         "effect": "정밀하고 강력한 공격을 연달아 날리는 채널링 — 주 대상과 10미터 내 적에게 피해. "
                   "집중하는 동안 받는 피해 10% 감소, 기절·밀쳐내기 면역.",
         "adoption": adoption_a(94818),
         "observed_buff_id": obs_a(436358),
         "rotation_impact": "오프너 정렬",
         "note": "거신을 찍으면 생기는 새 버튼(변신 아님) — 첫 사용 4.7초, 판당 12~17회(실측). "
                 "채널이 급살 소모를 방해해 거신 급살 낭비 19.8%의 원인이기도 함."},
        {"source": "영웅(거신)", "node_id": 94819, "name": "거인의 힘", "spell_id": 429634,
         "effect": "거인의 힘이 다음 쇄파의 공격력을 5%만큼 증가시킵니다. 최대 5번까지 중첩됩니다(거신의 지배로 10). "
                   "필사의 일격 사용 시, 그리고 회전베기가 3명 이상 적중 시 중첩을 얻습니다.",
         "adoption": adoption_a(94819),
         "observed_buff_id": obs_a(440989),
         "rotation_impact": "무관",
         "note": "필사의 일격만 부지런히 누르면 알아서 쌓임 — 거신의 지배가 최대 중첩에서 쇄파 쿨까지 깎아줌. 따로 셀 필요 없음."},
        {"source": "영웅(거신)", "node_id": 109812, "name": "빠르게 찾아오는 결말", "spell_id": 1270710,
         "effect": "쇄파의 마지막 공격이 10초 동안 가속을 10%만큼 증가시키고 다음 필사의 일격의 치명타 및 극대화율을 "
                   "100%만큼 증가시킵니다.",
         "adoption": adoption_a(109812),
         "observed_buff_id": obs_a(1270843, 1270846),
         "rotation_impact": "무관",
         "note": "쇄파 채널 끝나고 필사의 일격을 잇는 자연스러운 순서에 자동 포함 — 확정 크리는 뼈 가르기·정밀한 힘 연쇄까지 덤."},
        {"source": "영웅(거신)", "node_id": 109813, "name": "뼈 가르기", "spell_id": 1270709,
         "effect": "필사의 일격이 치명타 및 극대화로 적중하면 8초 동안 분쇄와 치명상의 공격력이 15%만큼 증가합니다.",
         "adoption": adoption_a(109813),
         "observed_buff_id": obs_a(1270840),
         "rotation_impact": "무관",
         "note": "크리 여부로 자동 발동 — 관리할 행동 없음."},
        # ---- 티어 세트 ----
    ]

    dist_a = tier_piece_distribution(arms_samples)
    n2 = sum(v for k, v in dist_a.items() if k >= 2)
    n4 = sum(v for k, v in dist_a.items() if k >= 4)
    arms_rows.append({
        "source": "티어", "item_set_id": TIER_SET_ID, "name": "밤의 종결자의 분노 2세트 (무기 효과)",
        "effect": spell_desc(cli, TIER_SPELLS["Arms"][2]),
        "adoption": f"{n2}/{n_arms} ({round(n2 / n_arms * 100)}%) — 2부위 이상 착용",
        "piece_distribution": dist_a,
        "rotation_impact": "무관",
        "note": "수치 강화 + 거인의 강타 디버프가 5% 더 아파짐 — 새 버프·행동 변화 없음.",
        "text_source": "Blizzard API spell 1264875 (item-set 1990과 동일 문구 — 무기 쪽은 세트 엔드포인트도 정상)",
    })
    arms_rows.append({
        "source": "티어", "item_set_id": TIER_SET_ID, "name": "밤의 종결자의 분노 4세트 (무기 효과)",
        "effect": spell_desc(cli, TIER_SPELLS["Arms"][4]),
        "adoption": f"{n4}/{n_arms} ({round(n4 / n_arms * 100)}%) — 4부위 이상 착용",
        "piece_distribution": dist_a,
        "rotation_impact": "무관",
        "note": "거인의 강타 창 안에서 필사의 일격(광역은 회전베기 3+타깃)을 칠수록 창이 1초씩 늘어남 — "
                "'거강 창 안에 다 몰아넣기' 규율(칼폭 90%·투신 82% 정렬)의 가치를 키우는 패시브. 따로 볼 버프는 없음.",
        "text_source": "Blizzard API spell 1264876",
    })

    # ---- 장신구 ----
    tc_a = trinket_counts(arms_samples)
    arms_trinket_defs = [
        (249342, "자동 프록", obs_a(1262753), "무관",
         "공격 시 일정 확률로 치명타 12초 증가 — 완전 자동. 무기 상위권 93% 착용, top25 조합 1순위."),
        (249343, "자동 프록", obs_a(1266686, 1266687), "무관",
         "공격만 하면 알아서 터짐(알른시야 → 시전마다 지능 중첩) — 관리 타이밍 없음."),
        (260235, "착용 감쇠형(전투 중 조작 없음)", obs_a(1265808), "무관",
         "치명타가 높게 시작해 60초에 걸쳐 줄어드는 착용 효과 — 전투 중 누를 건 없음. 무기에서만 10% 착용이 보이지만 "
         "보정 딜 평균 -449 열세(실측) — 가이드는 응시+심장 고정 권장."),
    ]
    for iid, kind, obs, impact, note in arms_trinket_defs:
        nm, text = item_tooltip(cli, iid)
        arms_rows.append({
            "source": "장신구", "item_id": iid, "name": nm or str(iid),
            "effect": text, "use_type": kind,
            "adoption": f"{tc_a.get(iid, 0)}/{n_arms} ({round(tc_a.get(iid, 0) / n_arms * 100)}%, 착용 데이터 집계)",
            "observed_buff_id": obs, "rotation_impact": impact, "note": note,
        })

    # ---- task1: 버튼 변신 맵 (무기) ----
    tot_a, kills_a = cast_counts(arms_events, [1269383, 1464, 12294, 281000, 163201, 446035, 228920, 845, 260708])
    arms_swap = [
        {
            "kind": "버튼 변신(프록)", "original": "격돌", "becomes": "영웅의 일격",
            "node_id": 110407, "talent": "전쟁의 지배자", "tree": "무기 전문화(row 12 정점)",
            "spell_id_talent": 1269314, "spell_id_cast": 1269383,
            "official_desc": "단일 대상 근접 능력 사용 시 일정 확률로 격돌이 영웅의 일격으로 강화됩니다. "
                             "격돌에 영향을 주는 모든 수정치와 특성이 영웅의 일격에도 영향을 줍니다.",
            "condition": "프록 버프 1269391 '전쟁의 지배자'(실측 확정) 보유 중 격돌 버튼이 영웅의 일격으로 변화 — 소모하면 복귀.",
            "adoption": adoption_a(110407),
            "measured": {"casts_영웅의_일격_1269383": tot_a[1269383], "casts_격돌_1464": tot_a[1464],
                         "proc_match": "영웅의 일격 8,847캐스트 중 99.8%가 1269391 removebuff ±150ms 일치 (proc_discipline 근거)",
                         "next_gcd": "프록 후 다음 GCD: 영웅의 일격 49.8% vs 필사의 일격 21.5%, 소모 지연 중앙 1.24초",
                         "companion_buffs": "1269394(같은 이름)·1292058 '영웅의 힘'은 영웅의 일격을 쓸 때마다 쌓이는 "
                                            "누적 중첩형 별개 버프(9,405회 부여 중 9,383회가 프록 소모와 동시 — 실측). "
                                            "위크아우라는 1269391만 걸면 됨."},
            "note": "12.0.5부터 '프록 뜨면 영웅의 일격 > 필사의 일격'이 정설 — 실측과 정합(단 절대 최우선까진 아님, "
                    "1~2글쿨 내 소모가 규율). 무기 추적 버프 1순위.",
        },
        {
            "kind": "버튼 활성화(변신 아님)", "original": "마무리 일격(잠김)", "becomes": "마무리 일격(사용 가능)",
            "node_id": 90274, "talent": "급살 (+학살자 임박한 파멸·대학살)", "tree": "무기 전문화",
            "official_desc": "급살: 공격 시 일정 확률로 다음 마무리 일격을 분노를 소모하지 않고 대상의 생명력에 관계없이 사용할 수 "
                             "있습니다. / 대학살(학살자 전용): 남은 생명력이 35% 미만인 대상에게 마무리 일격을 시전할 수 있습니다.",
            "condition": "평시엔 잠긴 버튼이 급살 프록(52437) 또는 처형 구간(학살자 35%/거신 기본 20%)에서 켜짐.",
            "adoption": f"급살 {adoption_a(90274)} / 대학살 {adoption_a(90291)}",
            "measured": {"casts_마무리_일격": {"학살자_281000": tot_a[281000], "거신_163201": tot_a[163201]},
                         "cast_id_note": "마무리 일격 캐스트 ID가 영웅특성에 따라 281000(학살자)/163201(거신)으로 갈림 — "
                                         "SPEC_CONFIG에 둘 다 등록 필요(실측 확정). 5308은 무기에서 0캐스트.",
                         "sudden_death": "소모율 84.5%, 지연 중앙 1.85초. 처형 구간 마무리 분당 5.95→13.51 (proc_discipline)"},
            "note": "학살자는 대학살+마무리 일격 연마 덕에 35% 이하에서 마무리 일격이 사실상 필러가 됨 — 처형 구간 순환 전환의 축.",
        },
        {
            "kind": "버튼 자체가 갈림(CHOICE)", "original": "칼날폭풍", "becomes": "쇠날발톱",
            "node_id": 90441, "tree": "무기 전문화(row 9)",
            "options": [
                {"talent": "칼날폭풍", "spell_id": 227847,
                 "official_desc": "멈출 수 없는 파괴의 소용돌이가 되어 5.4초 동안 주위 모든 적에게 물리 피해를 입힙니다.",
                 "adoption": {"share": 0.735, "by_hero": "학살자 100%"}},
                {"talent": "쇠날발톱", "spell_id": 228920,
                 "official_desc": "대상에게 주위 적을 추적하는 소용돌이치는 무기를 던져 모든 적에게 10.7초에 걸쳐 물리 피해를 입힙니다. "
                                  "쇠날발톱이 활성화된 동안 회전베기와 소용돌이의 공격력이 50%만큼 증가합니다.",
                 "adoption": {"share": 0.265, "by_hero": "거신 100%"}},
            ],
            "measured": {"casts_칼날폭풍_446035": tot_a[446035], "casts_쇠날발톱_228920": tot_a[228920],
                         "kills": f"칼날폭풍 {kills_a[446035]}킬(학살자 204와 일치) / 쇠날발톱 {kills_a[228920]}킬(거신 92와 일치)",
                         "note": "무기도 칼날폭풍 캐스트는 446035로 찍힘(227847 아님). 쇠날발톱은 광 타이밍 저장용(대홀드 57%)."},
            "note": "영웅특성이 곧 버튼 구성 — 학살자=칼날폭풍(거강·투신 창 정렬), 거신=쇠날발톱(쫄 웨이브 저장).",
        },
        {
            "kind": "버튼 강화(부여형 — 변신 아님)", "original": "휩쓸기 일격(수동)", "becomes": "휩쓸기 일격(거인의 강타가 무료 부여)",
            "node_id": 109686, "talent": "광범위한 타격", "tree": "무기 전문화(row 7 CHOICE)", "spell_id": 1261049,
            "official_desc": "거인의 강타가 휩쓸기 일격을 부여합니다.",
            "condition": "채택 시 거인의 강타를 누르면 휩쓸기 일격 버프(260708)가 자동으로 붙음 — 버튼 자체는 그대로 존재.",
            "adoption": adoption_a(109686) + " — 거신 100% / 학살자 55%(광역 보스 스왑)",
            "measured": {"manual_casts_260708": tot_a[260708],
                         "buff_kills": f"{arms_prev.get(260708, 0)}/{nk_a}킬에서 버프 관측 — 수동 시전 1,014회와 병행"},
            "note": "광역 국면에서 휩쓸기 일격 버프 창에 단일기를 몰아넣는 운용의 공급원 — 광역 패키지 스왑축"
                    "(몸풀기였을 뿐/광범위한 타격 ↔ 혈행성 전이)과 함께 보스별로 갈림.",
        },
    ]

    out_arms = {
        "_meta": {**meta_common, "spec": "Warrior|Arms", "sample_n": n_arms, "event_kills": nk_a,
                  "hero_split": arms_hero},
        "sources": arms_rows,
        "task1_button_swap_map": arms_swap,
    }

    # ================================================================ 저장
    (DATA / "proc_sources_fury.json").write_text(
        json.dumps(out_fury, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "proc_sources_arms.json").write_text(
        json.dumps(out_arms, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장: data/proc_sources_fury.json, data/proc_sources_arms.json", flush=True)

    for tag, out in (("분노", out_fury), ("무기", out_arms)):
        print(f"\n==== {tag} (source {len(out['sources'])}건, button_swap {len(out['task1_button_swap_map'])}건) ====")
        for r in out["sources"]:
            obs = r.get("observed_buff_id")
            obs_s = ", ".join(f"{o['id']}({o['name']}) {o['pct']}%" for o in obs) if obs else "-"
            print(f" [{r['source']}] {r['name']}")
            print(f"   채택 {r['adoption']} | 판정 {r['rotation_impact']} | 관측 {obs_s}")


if __name__ == "__main__":
    main()
