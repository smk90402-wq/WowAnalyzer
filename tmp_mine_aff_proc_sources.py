# -*- coding: utf-8 -*-
"""고통 흑마 프록/스킬 강화 전수 인벤토리 — 특성(일반+영웅+정점 최하단 2행)·티어 세트·장신구.

BM/Frost판(tmp_mine_proc_sources.py, data/proc_sources_bm.json·frost.json)과 같은 방식.
버튼이 다른 스킬로 바뀌는 효과('대체됩니다')는 task1_button_swap_map 섹션에 따로 수집
(냉법 proc_map 패턴 계승) — 고통 흑마는 어둠의 화살↔영혼 흡수(선택)·
어둠의 화살→재앙의 손아귀(암흑시선 소환 활성 중 조건부 대체)·부패→쇠퇴(영웅트리 대체, 채택 0)가 대상.

입력(로컬 캐시, API 호출 최소화):
  data/talent_trees.json (Warlock/Affliction) — spec(rows1-12)+hero(3종)+class
  data/aff_talent_splits.json — 오늘자(2026-07-05) 876명 채택률/보스별/CHOICE 분포(이미 산출됨, 재계산 안 함)
  data/rankings_zone46_mythic_dps_top100.csv + v2_cache_player_fight.json — 티어 피스 분포용
  data/item_db.json — 장신구 한글명
  data/spell_db.json — 버프 한글명
  스크래치패드 aff_cd_events.json (301킬, casts+buffs 타임라인) — 실사용 교차검증

외부(Blizzard API, WCL 안 씀 — 결과는 스크래치패드에 캐싱 후 재사용):
  아이템 툴팁(장신구 사용/착용 효과문) — item/{id}
  아이템 세트 보너스 문구 — item-set/{id} (고통 흑마 세트는 이 엔드포인트가 세트 효과 전문을 정상 반환 —
  냉법 때와 달리 비전 대체문구가 아니라 실제 2/4세트 효과문이 나옴, 확인됨)
  API 실패 시 FALLBACK_TEXT 사용.

출력: data/proc_sources_aff.json (신규 파일만, 기존 파일 덮어쓰지 않음)
"""
from __future__ import annotations

import csv
import json
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
SCRATCH = Path(
    r"C:\Users\smk90\AppData\Local\Temp\claude"
    r"\C--Users-smk90-OneDrive-------LogAnalyze"
    r"\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad"
)

TIER_SET_ID = 1989  # 불태우는 심연의 지배
TIER_ITEM_IDS = {250037, 250038, 250039, 250040, 250041, 250042, 250043, 250044, 250045}
TIER_SPELL_2P_TEXT = "세트 효과: 불안정한 고통과 부패의 씨앗의 공격력이 10%만큼 증가합니다."
TIER_SPELL_4P_TEXT = "세트 효과: 고통이 2중첩 상태로 부여되며, 공격력이 20%만큼 증가합니다."

TRINKET_IDS = [249343, 250144]  # 알른 선견자의 응시 / 잿불날개 깃털 (착용 데이터 상위 2종, 자동 수집)

# API 다운 대비 백업(2026-07-05 Blizzard API 응답 원문, 이미 확인됨)
FALLBACK_ITEM_TEXT = {
    249343: "착용 효과: 공격 및 치유 능력 사용 시 일정 확률로 12초 동안 알른시야가 부여됩니다. "
            "효과가 활성화된 동안 주문 및 능력 시전 시 불안정한 알른멸시를 현신시켜 12초 동안 지능이 2만큼 증가합니다. "
            "여러 번 사용 시 효과가 중첩됩니다.",
    250144: "사용 효과: 잿불날개 열파를 방출해 15초 동안 가속을 68만큼 증가시킵니다.\r\n\r\n"
            "낮은 확률로 잿불날개의 화염에 걸려 다른 보조 능력치 중 하나가 10초 동안 21만큼 감소합니다. (2분 후 재사용 가능)",
}


def get_blizzard():
    try:
        sys.path.insert(0, str(ROOT))
        from blizzard import Blizzard
        return Blizzard()
    except Exception as e:
        print(f"[경고] Blizzard API 클라이언트 사용 불가: {e}", flush=True)
        return None


def item_tooltip_text(cli, iid):
    if cli:
        try:
            d = cli.get(f"/data/wow/item/{iid}")
            spells = (d or {}).get("preview_item", {}).get("spells") or []
            if spells:
                return spells[0].get("description") or FALLBACK_ITEM_TEXT.get(iid, "확인 불가")
        except Exception:
            pass
    return FALLBACK_ITEM_TEXT.get(iid, "확인 불가")


def item_set_effects(cli, set_id):
    if cli:
        try:
            d = cli.get(f"/data/wow/item-set/{set_id}")
            eff = (d or {}).get("effects") or []
            if eff:
                return {e["required_count"]: e["display_string"] for e in eff}
        except Exception:
            pass
    return {2: TIER_SPELL_2P_TEXT, 4: TIER_SPELL_4P_TEXT}


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    return [r for r in rows if r["class"] == "Warlock" and r["spec"] == "Affliction"]


def tier_piece_distribution(aff_rows, pf):
    dist = Counter()
    seen = set()
    for r in aff_rows:
        key = f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}'
        if key in seen:
            continue
        seen.add(key)
        p = pf.get(key)
        if not isinstance(p, dict):
            continue
        n = sum(1 for g in (p.get("gear") or []) if g.get("id") in TIER_ITEM_IDS)
        dist[min(n, 5)] += 1
    return dict(sorted(dist.items()))


def load_item_name(iid):
    try:
        db = json.load(open(DATA / "item_db.json", encoding="utf-8"))
        v = db.get(str(iid))
        if v and v.get("name_ko"):
            return v["name_ko"]
    except Exception:
        pass
    return f"item {iid}"


def buff_name(sdb, i):
    v = sdb.get(str(i))
    return (v or {}).get("name_ko") if v else None


def load_events():
    d = json.load(open(SCRATCH / "aff_cd_events.json", encoding="utf-8"))
    return d


def observed(events, ids, sdb, kind="buff"):
    """ids 리스트 각각의 (킬수, 비율%) — buffs 또는 casts(kind='cast')."""
    n = len(events)
    out = []
    for i in ids:
        cnt = 0
        for v in events.values():
            src = v.get("buffs", []) if kind == "buff" else v.get("casts", [])
            key_idx = 1
            if kind == "cast":
                if any(len(c) >= 3 and c[1] == i and c[2] == "cast" for c in src):
                    cnt += 1
            else:
                if any(b[1] == i for b in src):
                    cnt += 1
        out.append({"id": i, "name": buff_name(sdb, i), "kills": cnt, "pct": round(cnt / n * 100) if n else 0})
    return out


def main():
    aff_rows = load_wanted()
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    sdb = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    talent_splits = json.load(open(DATA / "aff_talent_splits.json", encoding="utf-8"))
    sample_n = talent_splits["_meta"]["sample_n"]

    events = load_events()
    n_events = len(events)
    print(f"고통 흑마 표본 {sample_n}명 / 이벤트 캐시 {n_events}킬", flush=True)

    tier_dist = tier_piece_distribution(aff_rows, pf)
    print(f"티어 피스 분포: {tier_dist}", flush=True)

    cli = get_blizzard()
    tier_eff = item_set_effects(cli, TIER_SET_ID)
    trinket_text = {iid: item_tooltip_text(cli, iid) for iid in TRINKET_IDS}
    trinket_name = {iid: load_item_name(iid) for iid in TRINKET_IDS}

    apex = talent_splits["apex_talents"]
    unanimous = talent_splits["build_uniformity"]["unanimous_nodes"]
    variable = talent_splits["variable_nodes"]
    choice = talent_splits["choice_nodes"]

    def rate_of(node_id):
        key = str(node_id)
        if key in variable:
            return variable[key]["overall_rate"]
        if key in apex:
            return apex[key]["overall_rate"]
        if key in unanimous:
            return 1.0
        return None

    out = {
        "_meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "generated_by": "tmp_mine_aff_proc_sources.py",
            "spec": "Warlock|Affliction",
            "zone": 46,
            "difficulty": "mythic",
            "sample_talents": sample_n,
            "sample_event_kills": n_events,
            "inputs": ("talent_trees.json(Warlock/Affliction) + aff_talent_splits.json(2026-07-05 876명 채택률) "
                       "+ v2_cache_player_fight.json(티어 피스) + 이벤트 캐시(301킬 casts/buffs) + Blizzard API(장신구/세트 툴팁 ko_KR)"),
            "rotation_impact_기준": "추적 필요=버프를 보고 플레이가 바뀜 / 오프너 정렬=시작 타이밍에 맞춰 누름 / 무관=자동이라 관리 불필요",
            "naming": "스킬·특성명은 talent_trees.json / spell_db.json 공식 한글명만 사용.",
            "no_wcl_api": True,
        },
        "sources": [],
        "task1_button_swap_map": [],
    }

    # ============ 정점(row 11~12) ============
    apex_defs = [
        (109852, "치명적인 메아리", 11,
         "불안정한 고통의 지속시간이 끝나면 10%의 확률로 다시 불안정한 고통이 적용됩니다.",
         "무관", "불안정한 고통이 자연 만료되면 10% 확률로 알아서 재적용 — 버튼 없음. 부패의 씨앗 계열 빌드(바엘고어·선봉대)에서는 0% 채택."),
        (109855, "쏟아지는 재앙", 11,
         "자신의 불안정한 고통 효과가 적용된 대상에게 불안정한 고통을 시전하면 15초 동안 가속이 5%만큼 증가합니다.",
         "무관", "치명적인 메아리와 항상 함께 채택(swap_relations with_rate 100%) — 같은 UA 중첩 빌드의 짝. 가속 버프는 뜨지만 관리할 행동 없음."),
        (72033, "죽음의 은총", 11,
         "생명력이 35% 미만인 대상에 대한 고통, 부패, 불안정한 고통, 부패의 씨앗, 어둠의 화살의 공격력이 최대 40%까지 증가합니다.",
         "무관", "전원 채택(100%). 대상 체력이 낮을 때 자동으로 강화 — 관리 불필요."),
        (109853, "최초 감염자", 11,
         "부패의 씨앗이 대상에게 입히는 피해가 50%만큼 증가합니다.",
         "무관", "바엘고어·선봉대(다수 대상)에서만 100% 채택, 나머지 보스는 0% — 부패의 씨앗 중심 빌드 전용 패시브."),
        (109854, "씨앗 뿌리기", 11,
         "부패의 씨앗이 50%의 효율로 주위 적 2명에게 추가로 악마의 씨앗을 심습니다.",
         "무관", "최초 감염자와 완전히 같은 채택 패턴(항상 함께) — 부패의 씨앗 빌드의 광역 확장 패시브."),
        (110405, "나스레자의 그림자", 12,
         "유령 출몰 시전 시 뒤틀린 황천에서 악마의 영혼을 불러내 대상을 괴롭히게 합니다. 지속시간에 걸쳐 대상과 10미터 내 "
         "자신의 부패가 부여된 적 3명에게 2,474의 암흑 피해를 입힙니다.",
         "무관", "정점 최하단(row12) 유일 노드 — 전원 채택(100%). 유령 출몰을 누르면 자동으로 붙는 소환이라 별도 관리 없음."),
    ]
    for node_id, name, row, effect, impact, note in apex_defs:
        info = apex.get(str(node_id)) or apex.get(node_id) or {}
        out["sources"].append({
            "source": "정점", "node_id": node_id, "row": row, "name": name, "effect": effect,
            "adoption": f"{round(info.get('overall_rate', 0) * sample_n)}/{sample_n} "
                        f"({round(info.get('overall_rate', 0) * 100)}%)",
            "per_boss_rate": {b: v["rate"] for b, v in (info.get("per_boss") or {}).items()},
            "rotation_impact": impact, "note": note,
        })

    # ============ 특성(일반 스펙 트리) 프록 핵심 3종 ============
    spec_procs = [
        (109857, "조각의 불안정성", 9, 1260264,
         "어둠의 화살로 피해를 입히면 20%의 확률로 다음 불안정한 고통이 영혼의 조각을 소모하지 않으며 즉시 시전됩니다.",
         [1260269], "추적 필요",
         "어둠의 화살(또는 영혼 흡수) 피해마다 20% 확률로 뜨는 버프(조각의 불안정성) — 뜨면 다음 불안정한 고통이 "
         "조각 공짜+즉시시전. aff_proc_discipline.json 실측: 소모지연 중앙 1.4초, 2초 내 사용 65%, 낭비(겹침/만료) 12%. "
         "바엘고어·선봉대(부패의 씨앗 빌드)에서는 채택 0~5% — 그 보스는 이 프록 자체가 없다."),
        (72047, "일몰", 4, 108558,
         "부패로 피해를 입히면 다음 어둠의 화살 또는 재앙의 손아귀의 공격력이 25%만큼 증가합니다. "
         "효과에 영향을 받는 동안 어둠의 화살이 즉시 시전되고 재앙의 손아귀가 50%만큼 더 빨리 시전됩니다.",
         [264571, 1260279], "추적 필요",
         "전원 채택(100%, 부패 자체가 필수 DoT). 부패 도트 틱마다 확률로 버프 부여 — 뜨면 다음 공격 주문(어둠의 화살/"
         "영혼 흡수/재앙의 손아귀/부패의 씨앗)이 강화+즉발. aff_proc_discipline.json 실측: 소모지연 중앙 1.5초, "
         "2초 내 사용 56%, 4초 내 82%, 낭비 8%, 분당 7.7회 — 냉법 서리의 손가락만큼 자주 뜨는 주력 프록."),
        (109851, "밤의 수혜", 9, 1260271,
         "부패의 공격력이 10%만큼 증가하고, 일몰이 추가로 다음 부패의 씨앗이 영혼의 조각을 소모하지 않고 즉시 시전되게 합니다.",
         [], "무관",
         "부패의 씨앗 빌드(바엘고어·선봉대) 전용 — 그 두 보스에서만 100% 채택, 나머지는 0~20%. 일몰 프록이 뜨면 "
         "어둠의 화살류 대신 부패의 씨앗을 공짜+즉발로 쏘게 하는 갈래. 조각의 불안정성과 상호배타(같이 채택 0)."),
    ]
    for node_id, name, row, spell_id, effect, buff_ids, impact, note in spec_procs:
        rate = rate_of(node_id)
        obs = observed(events, buff_ids, sdb) if buff_ids else []
        out["sources"].append({
            "source": "특성(고통 전문화)", "node_id": node_id, "row": row, "name": name, "spell_id": spell_id,
            "effect": effect,
            "adoption": f"{round((rate or 0) * sample_n)}/{sample_n} ({round((rate or 0) * 100)}%)" if rate is not None else "확인 필요",
            "observed_buff_id": obs or None,
            "rotation_impact": impact, "note": note,
        })

    # ============ 특성(일반) — 기타 강화 패시브 ============
    misc_defs = [
        (94829, "파멸의 씨앗", 4, 440055,
         "쇠퇴가 8번 중첩되거나 대상의 생명력이 20% 이하로 떨어지면 쇠퇴가 대상에게 1초마다 378의 암흑불길 피해를 입힙니다. "
         "검게 물든 영혼이 피해를 입히면 일정 확률로 조각의 불안정성이 부여됩니다.",
         "무관", "지옥소환사(쇠퇴 계열) 전용 노드 — 영혼 수확자가 875/876으로 사실상 전부라 이 노드 자체가 죽어있음(채택 표에 없음, 0%에 가까움)."),
        (102247, "게걸스러운 고통", 10, 459440,
         "고통, 부패, 불안정한 고통의 치명타 및 극대화 효과가 일정 확률로 일몰을 부여합니다.",
         "무관", "전원 채택(100%, unanimous). 도트 크리티컬마다 추가로 일몰을 얹어주는 패시브 — 버튼 없음, 일몰이 더 자주 뜨게 만들 뿐."),
        (109858, "재앙의 손아귀", 8, 1261149,
         "암흑시선 소환이 활성화된 동안 어둠의 화살이 재앙의 손아귀로 변화합니다. 재앙의 손아귀로 피해를 입히면 시전자의 "
         "다른 모든 주기적인 고통 공격 효과가 즉시 통상적인 주기적인 피해의 30%에 해당하는 피해를 입힙니다.",
         "추적 필요", "★버튼 변신 노드★ — 상세는 task1 참고. 전체 57.5%가 채택하지만 바엘고어·선봉대는 0%(암흑시선 소환 창 관리가 "
         "무의미한 보스), 살라다르 top20은 100%."),
    ]
    for node_id, name, row, spell_id, effect, impact, note in misc_defs:
        rate = rate_of(node_id)
        out["sources"].append({
            "source": "특성(고통 전문화)", "node_id": node_id, "row": row, "name": name, "spell_id": spell_id,
            "effect": effect,
            "adoption": f"{round((rate or 0) * sample_n)}/{sample_n} ({round((rate or 0) * 100)}%)" if rate is not None else "0/876 (0%, 죽은 노드)",
            "rotation_impact": impact, "note": note,
        })

    # ============ 영웅(영혼 수확자, 875/876 채택) ============
    hero_defs = [
        (94851, "악마의 영혼", 2, 449614,
         "악마가 시전자의 영혼에 자리를 잡습니다. 영혼의 조각이 생성됐을 때 탐스러운 영혼인지를 감별할 수 있도록 합니다. "
         "탐스러운 영혼을 흡수하면 악마의 영혼을 방출해 대상의 10미터 내에 있는 모든 적에게 1,342의 암흑 피해를 입힙니다.",
         [449793, 1269042], "추적 필요",
         "영혼 수확자 트리의 뿌리 — 전원 채택(875/876). 영혼의 조각 중 일부가 '탐스러운 영혼'(관측 버프: 탐스러운 영혼 100%)으로 "
         "표시되고, 그걸 소모(공격 주문으로 조각 사용)하면 악마의 영혼이 방출(실체화된 악마의 영혼 100%)돼 광역 피해. "
         "조각 색이 바뀌는 것뿐 — 조각 소비 순서(불안정한 고통/부패의 씨앗)는 그대로 최우선."),
        (94847, "영혼 파문", 3, 449624,
         "악마의 영혼 해방 시 대상의 영혼에 사악함을 깃들게 하여 10초에 걸쳐 488의 암흑 피해를 입힙니다. "
         "이 효과가 다시 부여되면 남은 피해량을 새로운 영혼 파문에 합산합니다.",
         [], "무관", "전원 채택. 악마의 영혼 방출에 자동으로 따라붙는 도트 — 관리할 행동 없음."),
        (94825, "강령사의 가르침", 3, 449620,
         "어둠의 화살의 공격력이 20%만큼 증가합니다. 또한 마력 착취가 악마 화살의 공격력을 추가로 20%만큼 증가시킵니다.",
         [], "무관", "전원 채택. 순수 수치 강화 패시브."),
        (94857, "죽음의 그림자", 6, 449638,
         "악마 폭군 소환 주문이 내면에 있는 악마에 의해 강화되어 각각 탐스러운 영혼이 포함되어 있는 영혼의 조각 3개를 부여하도록 합니다.",
         [], "오프너 정렬", "전원 채택. 악마 폭군(공용 소환수 CD)을 쓰면 조각 3개가 즉시 채워짐 — 폭군 CD 타이밍에 조각 관리가 걸려 있다는 뜻."),
    ]
    for node_id, name, row, spell_id, effect, buff_ids, impact, note in hero_defs:
        obs = observed(events, buff_ids, sdb) if buff_ids else []
        out["sources"].append({
            "source": "영웅(영혼 수확자)", "node_id": node_id, "row": row, "name": name, "spell_id": spell_id,
            "effect": effect, "adoption": "875/876 (99.9%, 영웅트리 자체 채택)",
            "observed_buff_id": obs or None, "rotation_impact": impact, "note": note,
        })

    # ============ 티어 세트 ============
    out["sources"].append({
        "source": "티어", "item_set_id": TIER_SET_ID, "name": "불태우는 심연의 지배 2세트",
        "effect": tier_eff.get(2, TIER_SPELL_2P_TEXT),
        "adoption": f"{sum(n for k, n in tier_dist.items() if k >= 2)}/{sum(tier_dist.values())} — 2부위 이상 착용",
        "piece_distribution": tier_dist,
        "rotation_impact": "무관", "note": "불안정한 고통·부패의 씨앗 공격력 +10% — 수치만 강화, 새 버프·행동 변화 없음.",
    })
    out["sources"].append({
        "source": "티어", "item_set_id": TIER_SET_ID, "name": "불태우는 심연의 지배 4세트",
        "effect": tier_eff.get(4, TIER_SPELL_4P_TEXT),
        "adoption": f"{sum(n for k, n in tier_dist.items() if k >= 4)}/{sum(tier_dist.values())} — 4부위 이상 착용",
        "piece_distribution": tier_dist,
        "rotation_impact": "무관",
        "note": "고통이 항상 2중첩으로 시전되고 공격력 +20% — 고통을 누르는 순간 자동 적용, 관리할 타이밍 없음.",
    })

    # ============ 장신구(착용 데이터 자동 수집 상위 2종) ============
    trinket_obs = {
        249343: observed(events, [1266686, 1266687], sdb),
        250144: observed(events, [1250508], sdb, kind="cast"),
    }
    out["sources"].append({
        "source": "장신구", "item_id": 249343, "name": trinket_name[249343],
        "effect": trinket_text[249343], "use_type": "자동 프록",
        "adoption": "849/876 (97%, 착용 데이터 집계)",
        "observed_buff_id": trinket_obs[249343],
        "rotation_impact": "무관", "note": "공격만 하면 알아서 터짐(알른시야 → 시전마다 지능 중첩) — BM·냉법과 같은 장신구, 관리 타이밍 없음.",
    })
    out["sources"].append({
        "source": "장신구", "item_id": 250144, "name": trinket_name[250144],
        "effect": trinket_text[250144], "use_type": "사용형(2분 쿨)",
        "adoption": "765/876 (87%, 착용 데이터 집계)",
        "observed_buff_id": trinket_obs[250144],
        "rotation_impact": "오프너 정렬",
        "note": "15초 가속 대폭 버프, 2분 쿨. 실측 301킬 중 269킬(89%)이 사용 — 사용 타이밍(오프너 정렬 여부)은 "
                "추가 확인 필요(미해결, aff_cd_events 캐스트 오프셋으로 검증 가능하나 이번 인벤토리 범위 밖).",
    })

    # ============ task1: 버튼 변신 맵 ============
    out["task1_button_swap_map"] = [
        {
            "kind": "버튼 변신(대체, CHOICE)", "original": "어둠의 화살", "becomes": "영혼 흡수",
            "node_id": 72045, "tree": "고통 전문화",
            "options": [
                {"talent": "어둠의 화살 연마", "spell_id": 453080, "entry": 96568,
                 "official_desc": "어둠의 화살의 시전 시간이 15%만큼 감소하고 공격력은 40%만큼 증가합니다.",
                 "adoption": {"n": 333, "of": 876, "pct": 38.0}},
                {"talent": "영혼 흡수", "spell_id": 388667, "entry": 129530,
                 "official_desc": "어둠의 화살을 대체합니다. 적의 영혼을 흡수해 4.5초에 걸쳐 2,117의 암흑 피해를 입힙니다. "
                                   "남은 생명력이 20% 미만인 적에게 공격력이 100%만큼 증가합니다. "
                                   "이 효과가 지속되는 동안 대상이 죽으면 영혼의 조각 1개를 생성합니다.",
                 "adoption": {"n": 543, "of": 876, "pct": 62.0}},
            ],
            "measured": {"casts_어둠의_화살_686": 114, "casts_영혼_흡수_198590": 187,
                         "note": "301킬 이벤트 캐시 킬 단위 카운트(총 캐스트 수는 각 4886/6541회) — 채택 비율(38/62)과 방향 일치."},
            "note": "보스별로 크게 갈림 — 바엘고어(다수 대상)는 영혼 흡수 20%뿐(어둠의 화살 연마가 80%), "
                    "우주의 왕관·벨로렌(단일 위주)은 영혼 흡수가 80% 이상. 처형 구간(대상 20% 미만)에서 영혼 흡수가 "
                    "공격력 2배라 단일 지속 딜에 유리, 어둠의 화살 연마는 즉발성(시전시간 -15%)이 강점.",
        },
        {
            "kind": "버튼 변신(조건부 대체)", "original": "어둠의 화살(또는 영혼 흡수)", "becomes": "재앙의 손아귀",
            "node_id": 109858, "tree": "고통 전문화", "spell_id_talent": 1261149, "spell_id_cast": 1261153,
            "official_desc": "암흑시선 소환이 활성화된 동안 어둠의 화살이 재앙의 손아귀로 변화합니다. "
                              "재앙의 손아귀\n대상을 황혼으로 속박하여 3.6초에 걸쳐 4,003의 암흑 피해를 입힙니다. "
                              "재앙의 손아귀로 피해를 입히면 시전자의 다른 모든 주기적인 고통 공격 효과가 즉시 통상적인 "
                              "주기적인 피해의 30%에 해당하는 피해를 입힙니다.",
            "condition": "암흑시선 소환(20초 지속 소환수, 전원 채택) 활성화 중에만 버튼이 재앙의 손아귀로 바뀜 — "
                         "소환수가 없으면 다시 어둠의 화살/영혼 흡수로 돌아옴.",
            "adoption": {"n": 504, "of": 876, "pct": 57.5,
                         "per_boss_note": "바엘고어·선봉대 0% / 살라다르 top20 100% — 완전한 부패 빌드(다수 대상)와 상호배타적."},
            "measured": {"casts_1261153": 179, "casts_1261149(구ID)": 0,
                         "note": "실제 로그 캐스트는 스펠ID 1261153으로 찍힘(트리 표기 1261149와 다름 — 실측으로 확정)."},
            "note": "암흑시선 소환의 20초 창을 재앙의 손아귀로 도배하면, 재앙의 손아귀 자체가 다른 도트(고통/부패/UA)를 "
                    "그 자리에서 30%만큼 즉시 정산 — 창이 열려 있을 때 어둠의 화살류 대신 이 버튼을 눌러야 함(추적 필요).",
        },
        {
            "kind": "버튼 변신(대체, 영웅트리 배타)", "original": "부패", "becomes": "쇠퇴",
            "node_id": 94840, "tree": "영웅(지옥소환사)", "spell_id": 445468,
            "official_desc": "대상에게 흉악한 저주를 내려 힘줄과 근육을 살라 먹게 합니다. 즉시 74의 암흑불길 피해를 입히고 "
                              "추가로 18초에 걸쳐 1,251의 암흑불길 피해를 입힙니다.\n\n부패를 대체합니다.",
            "adoption": {"n": 1, "of": 876, "pct": 0.1},
            "measured": {"casts_445468": 0, "note": "301킬 이벤트 캐시에서 쇠퇴 시전 0회."},
            "note": "지옥소환사 영웅트리를 타면 부패 버튼이 쇠퇴로 바뀌지만, 고통 흑마 상위권 875/876이 영혼 수확자를 "
                    "채택해 이 대체는 사실상 죽어있음 — 가이드에서 다룰 필요 없음.",
        },
    ]

    OUT = DATA / "proc_sources_aff.json"
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"저장: {OUT} (source {len(out['sources'])}건, button_swap {len(out['task1_button_swap_map'])}건)", flush=True)


if __name__ == "__main__":
    main()
