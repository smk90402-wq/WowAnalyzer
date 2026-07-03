# -*- coding: utf-8 -*-
"""야수냥·냉법 프록/스킬 강화 전수 인벤토리 — 정점(트리 최하단 2행)·티어 세트·장신구·영웅.

입력(로컬 캐시):
  data/talent_trees.json                     노드/선택지 한글명·설명 (정점 행)
  data/rankings_zone46_mythic_dps_top100.csv 표본 목록
  data/v2_cache_player_fight.json            표본별 talents/nodes/gear
  data/spell_db.json                         버프 ID → 한글명
  이벤트 캐시(세션 스크래치패드, EVENTS_DIR):
    bm_cd_events.json      야수냥 362킬 — casts/buffs 타임라인
    frost_event_sets.json  냉법 302킬 — 킬별 buffs 집합 + casts 집계
    frost_cd_events.json   냉법 302킬 — casts 타임라인 (장신구 사용 타이밍)

외부(허용된 Blizzard API만, WCL 안 씀):
  아이템 툴팁(장신구 효과문), 아이템 세트 이름, 세트 보너스 주문 설명(ko_KR).
  세트 보너스 주문 ID는 /search/spell 로 확인해 둔 값을 하드코딩:
    사냥꾼 야수 12.0: 2세트 1264825 / 4세트 1264826
    마법사 냉기 12.0: 2세트 1264836 / 4세트 1264837
  (아이템 세트 엔드포인트는 마법사 세트에서 비전 문구만 반환해서 주문 쪽을 씀.)
  API 실패 시 효과문은 "확인 불가"로 남김.

출력(신규 파일만):
  data/proc_sources_bm.json
  data/proc_sources_frost.json
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
    r"C:\Users\smk90\AppData\Local\Temp\claude"
    r"\C--Users-smk90-OneDrive-------LogAnalyze"
    r"\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad"))

TIER_SET = {
    "BM": {"set_id": 1982, "items": [249986, 249987, 249988, 249989, 249991],
           "spell_2p": 1264825, "spell_4p": 1264826},
    "Frost": {"set_id": 1983, "items": [250058, 250059, 250060, 250061, 250063],
              "spell_2p": 1264836, "spell_4p": 1264837},
}
# API 다운 시에도 산출이 비지 않도록, 2026-07-04 Blizzard API 응답 원문 백업.
FALLBACK_TEXT = {
    1264825: "야수의 격노의 직접 피해가 25%만큼 증가합니다.",
    1264826: "야수의 격노 사용 시 8초 동안 광포한 야수 1마리를 소환합니다.",
    1264836: "진눈깨비의 공격력이 10%만큼 증가하며, 진눈깨비 시전 시 10%의 확률로 서리의 손가락이 부여됩니다.",
    1264837: "서리의 손가락이 산산조각의 공격력을 15%만큼 증가시킵니다.",
}


def load_samples(cls, spec):
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    out = []
    for r in rows:
        if r["class"] != cls or r["spec"].replace(" ", "") != spec:
            continue
        p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
        if isinstance(p, dict) and p.get("nodes"):
            out.append(p)
    return out


def apex_nodes(tree_key, n_rows=2):
    """spec 트리 최하단 n_rows 행의 노드들."""
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    spec_tree = tt[tree_key]["spec"]
    rows = sorted(set(n["row"] for n in spec_tree))
    bottom = set(rows[-n_rows:])
    return [n for n in sorted(spec_tree, key=lambda n: (n["row"], n["col"]))
            if n["row"] in bottom]


def choice_split(samples, node):
    """CHOICE 노드의 옵션별 채택 수. 노드 내 entry_id 오름차순 = talent_id 오름차순
    (tmp_mine_bm_talent_splits.py 에서 실측 검증한 규칙)."""
    nid = node["id"]
    tc = Counter()
    for p in samples:
        seq, tal = p.get("nodes") or [], p.get("talents") or []
        if len(seq) == len(tal):
            for a, b in zip(seq, tal):
                if a == nid:
                    tc[b] += 1
    opts = sorted(node["options"], key=lambda o: o["talent_id"])
    entries = sorted(tc)
    if len(entries) != len(opts):
        # 한쪽 옵션만 관측되면 entry 1개 — 매핑 확정 불가 시 이름 없이 수만
        return [{"name": None, "n": c} for e, c in tc.most_common()]
    m = dict(zip(entries, opts))
    return [{"name": m[e]["name"], "spell_id": m[e].get("spell_id"), "n": tc[e]}
            for e in sorted(tc, key=lambda e: -tc[e])]


def bm_buff_prevalence():
    d = json.load(open(EVENTS_DIR / "bm_cd_events.json", encoding="utf-8"))
    prev = Counter()
    for v in d.values():
        for i in set(e[1] for e in v.get("buffs", [])):
            prev[i] += 1
    return prev, len(d), d


def frost_buff_prevalence():
    d = json.load(open(EVENTS_DIR / "frost_event_sets.json", encoding="utf-8"))
    prev = Counter()
    cast_kills = Counter()
    for v in d.values():
        for i in set(v.get("buffs", [])):
            prev[i] += 1
        for sid in v.get("casts", {}):
            cast_kills[int(sid)] += 1
    return prev, len(d), cast_kills


def first_use_offsets(events, cast_id):
    """킬별 (해당 시전 첫 사용 시각 - 첫 시전 시각) 초. 타임라인 캐시용."""
    offs = []
    used = 0
    for v in events.values():
        casts = v.get("casts") or []
        if not casts:
            continue
        t0 = min(e[0] for e in casts)
        mine = [e[0] for e in casts if e[1] == cast_id]
        if mine:
            used += 1
            offs.append((min(mine) - t0) / 1000)
    offs.sort()
    mid = offs[len(offs) // 2] if offs else None
    within10 = sum(1 for o in offs if o <= 10) / len(offs) if offs else None
    return {"kills_used": used, "first_use_mid_s": round(mid, 1) if mid is not None else None,
            "used_within_10s_pct": round(within10 * 100) if within10 is not None else None}


def tier_piece_distribution(samples, item_ids):
    ids = set(item_ids)
    dist = Counter()
    for p in samples:
        c = sum(1 for g in p.get("gear", []) if g.get("id") in ids)
        dist[c] += 1
    return dict(sorted(dist.items()))


def trinket_counts(samples):
    c = Counter()
    for p in samples:
        for g in p.get("gear", []):
            if g.get("slot") in (12, 13):
                c[g["id"]] += 1
    return c


def get_blizzard():
    try:
        sys.path.insert(0, str(ROOT))
        from blizzard import Blizzard
        return Blizzard()
    except Exception as e:
        print(f"[경고] Blizzard API 클라이언트 사용 불가: {e}")
        return None


def spell_desc(cli, sid):
    if cli:
        d = cli.get(f"/data/wow/spell/{sid}")
        if d and d.get("description"):
            return d["description"]
    return FALLBACK_TEXT.get(sid, "확인 불가")


def item_tooltip(cli, iid):
    """장신구 효과문 리스트: [(주문ID, 주문이름, 설명)]. '사용 효과:'/'착용 효과:' 구분 포함."""
    if not cli:
        return None
    d = cli.get(f"/data/wow/item/{iid}")
    if not d:
        return None
    out = []
    for sp in (d.get("preview_item", {}).get("spells") or []):
        out.append({"spell_id": sp.get("spell", {}).get("id"),
                    "spell_name": sp.get("spell", {}).get("name"),
                    "text": sp.get("description")})
    return {"name": d.get("name"), "spells": out}


def item_set_name(cli, set_id):
    if cli:
        d = cli.get(f"/data/wow/item-set/{set_id}")
        if d:
            return d.get("name")
    return None


def pct(n, total):
    return f"{n}/{total} ({round(n / total * 100)}%)"


def main():
    cli = get_blizzard()
    spell_db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))

    def buff_name(i):
        return (spell_db.get(str(i)) or {}).get("name_ko")

    # ================= 야수냥 =================
    bm = load_samples("Hunter", "BeastMastery")
    n_bm = len(bm)
    bm_prev, bm_kills, bm_events = bm_buff_prevalence()
    print(f"BM 표본 {n_bm}명 / 이벤트 캐시 {bm_kills}킬")

    def bm_obs(*ids):
        """관측 버프: [{id, name, kills, pct}]"""
        return [{"id": i, "name": buff_name(i), "kills": bm_prev.get(i, 0),
                 "pct": round(bm_prev.get(i, 0) / bm_kills * 100)} for i in ids]

    def node_rate(samples, nid):
        return sum(1 for p in samples if nid in p["nodes"])

    bm_rows = []
    # --- 정점 (row 11~12) ---
    for nd in apex_nodes("Hunter/Beast Mastery"):
        nid = nd["id"]
        c = node_rate(bm, nid)
        opts = nd["options"]
        name = " / ".join(o["name"] for o in opts)
        row = {
            "source": "정점",
            "node_id": nid, "row": nd["row"],
            "name": name,
            "effect": " / ".join((o.get("desc") or "").strip() for o in opts),
            "adoption": pct(c, n_bm),
        }
        if nd.get("type") == "CHOICE" and c:
            row["choice_split"] = [
                {**o, "pct_of_pickers": round(o["n"] / c * 100)} for o in choice_split(bm, nd)]
        bm_rows.append(row)

    # 정점별 관측 버프·판정 (버프 ID는 로그 실측 + spell_db 이름 대조로 귀속)
    apex_buff_map_bm = {
        94966: (bm_obs(1258338, 1258344), "무관",
                "야수의 격노 → 다음 살상 명령에 자동 연계. 살상 명령은 어차피 최우선이라 따로 아낄 게 없음. "
                "버프(쇄도!)는 화면 확인용으로만 유용."),
        107285: (bm_obs(1235388), "무관",
                 "광포한 야수를 세게 만드는 패시브. 누르는 건 없음. 대신 보스별로 꿰뚫는 송곳니와 갈아끼우는 "
                 "빌드 갈림(채택 0~100%)이라 가이드의 보스별 빌드 표에 반영할 것."),
        102339: (bm_obs(1265063), "무관",
                 "피의 광란: 야수의 격노 중 날카로운 사격이 빨리 감 — 자동. 야생의 본능: 발구르기가 날카로운 "
                 "사격을 뿌림 — 자동. 어느 쪽도 새 버튼/추적 없음."),
        102371: (bm_obs(392054), "무관",
                 "야수의 격노 중 상시 적용 패시브. 버프는 뜨지만 보고 할 건 없음."),
        110428: (bm_obs(1276720), "무관",
                 "야수의 격노에 자동으로 붙어 나오는 소환. 누르는 것 없음."),
    }
    for row in bm_rows:
        obs, impact, note = apex_buff_map_bm.get(row["node_id"], (None, "확인 불가", None))
        row["observed_buff_id"] = obs
        row["rotation_impact"] = impact
        if note:
            row["note"] = note

    # --- 티어 세트 ---
    ts = TIER_SET["BM"]
    dist = tier_piece_distribution(bm, ts["items"])
    n4 = sum(v for k, v in dist.items() if k >= 4)
    n2 = sum(v for k, v in dist.items() if k >= 2)
    set_nm = item_set_name(cli, ts["set_id"]) or "원시 파수꾼의 위장"
    # 광포한 야수 소환 시전(여러 ID) — 4세트/특성/사냥지배자의 부름 프록이 뒤섞여 개별 귀속 불가
    dire_ids = [1283818, 1283817, 204526, 219199, 304051, 212396, 212382]
    dire_kills = sum(1 for v in bm_events.values()
                     if any(e[1] in dire_ids for e in v.get("casts", [])))
    bm_rows.append({
        "source": "티어",
        "name": f"{set_nm} 2세트",
        "effect": spell_desc(cli, ts["spell_2p"]),
        "adoption": pct(n2, n_bm) + " — 2부위 이상 착용",
        "observed_buff_id": None,
        "rotation_impact": "무관",
        "note": "수치만 올려주는 패시브. 새 버프 없음.",
        "piece_distribution": dist,
    })
    bm_rows.append({
        "source": "티어",
        "name": f"{set_nm} 4세트",
        "effect": spell_desc(cli, ts["spell_4p"]),
        "adoption": pct(n4, n_bm) + " — 4부위 이상 착용",
        "observed_buff_id": [
            {"id": dire_ids, "name": "광포한 야수 소환(버프 아님 — 시전 이벤트, ID 여러 개)",
             "kills": dire_kills, "pct": round(dire_kills / bm_kills * 100)}],
        "rotation_impact": "무관",
        "note": "야수의 격노에 자동으로 붙는 소환 — 광포한 야수 시전이 로그에 여러 ID로 찍히는데 "
                "4세트/자연의 교감자/사냥지배자의 부름 몫을 따로 가르는 건 확인 불가. 플레이어가 관리할 건 없음.",
    })

    # --- 장신구 ---
    tc = trinket_counts(bm)
    box_timing = first_use_offsets(bm_events, 383781)
    trinket_rows_bm = [
        (249343, "자동 프록", bm_obs(1266686, 1266687), "무관",
         "공격만 하면 알아서 터짐(알른시야 → 시전마다 지능 중첩). 누르는 타이밍 없음."),
        (193701, "사용형", bm_obs(383781), "오프너 정렬",
         f"20초 특화 뻥튀기, 2분 쿨. 실제 로그에서 쓴 킬의 절반이 전투 시작 "
         f"{box_timing['first_use_mid_s']}초 안에 눌렀고, 10초 안에 누른 비율 {box_timing['used_within_10s_pct']}% — "
         "오프너(야수의 격노·쇄도 창)에 맞춰 누르고 이후 쿨마다."),
        (249806, "자동(전투 외 변신만 사용형)", bm_obs(1260615, 1265808), "무관",
         "특화가 높게 시작해 60초에 걸쳐 줄어드는 착용 효과. 전투 중 누를 건 없음."),
    ]
    for iid, kind, obs, impact, note in trinket_rows_bm:
        tip = item_tooltip(cli, iid)
        bm_rows.append({
            "source": "장신구",
            "item_id": iid,
            "name": (tip or {}).get("name") or str(iid),
            "effect": " / ".join(filter(None, (s.get("text") for s in (tip or {}).get("spells", [])))) or "확인 불가",
            "use_type": kind,
            "adoption": pct(tc.get(iid, 0), n_bm),
            "observed_buff_id": obs,
            "rotation_impact": impact,
            "note": note,
        })

    # --- 영웅 (무리의 지도자 — bm_talent_splits: 890/890) ---
    bm_rows.append({
        "source": "영웅",
        "name": "무리의 지도자 — 무리의 지도자의 포효(곰·멧돼지·와이번 순환)",
        "effect": "살상 명령이 주기적으로 야수(곰/멧돼지/와이번)를 불러오고, 포효 버프가 다음 야수를 예고. "
                  "정점 '쇄도!'가 야수의 격노 시전 때 이 포효를 즉시 부여.",
        "adoption": pct(890, n_bm),
        "observed_buff_id": bm_obs(471877, 471878, 472324, 472325, 471881, 472640),
        "rotation_impact": "추적 필요",
        "note": "포효 버프가 떠 있는 동안의 살상 명령이 야수를 소환 — 어떤 야수가 나올 차례인지 버프로 보임. "
                "가이드 '추적할 버프'에 포함할 것.",
    })

    # ================= 냉법 =================
    fr = load_samples("Mage", "Frost")
    n_fr = len(fr)
    fr_prev, fr_kills, fr_cast_kills = frost_buff_prevalence()
    fr_cd = json.load(open(EVENTS_DIR / "frost_cd_events.json", encoding="utf-8"))
    print(f"Frost 표본 {n_fr}명 / 이벤트 캐시 {fr_kills}킬")

    def fr_obs(*ids):
        return [{"id": i, "name": buff_name(i), "kills": fr_prev.get(i, 0),
                 "pct": round(fr_prev.get(i, 0) / fr_kills * 100)} for i in ids]

    fr_rows = []
    apex_buff_map_fr = {
        62182: (fr_obs(1247730), "무관",
                "두뇌 빙결을 쓰면 다음 얼음창이 세짐 — 진눈깨비→얼음창 콤보를 이미 하고 있으면 저절로 소모됨. "
                "새 버튼 없음. 버프는 매 킬 100% 관측."),
        62184: (None, "무관",
                "얼음창이 산산조각 낼 때마다 서리 광선 쿨이 깎이는 패시브. 버프 없음. "
                "서리 광선이 표기 쿨보다 훨씬 자주 돌아오니 '쿨마다 즉시' 습관에 반영."),
        62185: (None, "무관",
                "상위권 885명 중 채택 0명, 302킬에서 시전 0회. 가이드에서 다룰 필요 없음(비추천 명시 정도)."),
        110422: (fr_obs(1263263), "무관",
                 "산산조각마다 10% 확률로 알아서 소환되는 프록. 누르는 것 없음. 버프는 매 킬 100% 관측."),
    }
    for nd in apex_nodes("Mage/Frost"):
        nid = nd["id"]
        c = node_rate(fr, nid)
        opts = nd["options"]
        row = {
            "source": "정점",
            "node_id": nid, "row": nd["row"],
            "name": " / ".join(o["name"] for o in opts),
            "effect": " / ".join((o.get("desc") or "").strip() for o in opts),
            "adoption": pct(c, n_fr),
        }
        obs, impact, note = apex_buff_map_fr.get(nid, (None, "확인 불가", None))
        row["observed_buff_id"] = obs
        row["rotation_impact"] = impact
        if note:
            row["note"] = note
        fr_rows.append(row)

    ts = TIER_SET["Frost"]
    dist = tier_piece_distribution(fr, ts["items"])
    n4 = sum(v for k, v in dist.items() if k >= 4)
    n2 = sum(v for k, v in dist.items() if k >= 2)
    set_nm = item_set_name(cli, ts["set_id"]) or "공허파괴자의 합의"
    fr_rows.append({
        "source": "티어",
        "name": f"{set_nm} 2세트 (냉기 효과)",
        "effect": spell_desc(cli, ts["spell_2p"]),
        "adoption": pct(n2, n_fr) + " — 2부위 이상 착용",
        "observed_buff_id": fr_obs(44544),
        "rotation_impact": "무관",
        "note": "새 버프를 만들지 않고 기존 '서리의 손가락'(44544) 충전을 더 자주 줌 — 이미 추적하는 버프에 "
                "합류. 진눈깨비 가치가 올라간다는 코멘트만 가이드에 반영.",
        "piece_distribution": dist,
        "text_source": "Blizzard API spell 1264836 (아이템 세트 엔드포인트는 비전 문구만 반환)",
    })
    fr_rows.append({
        "source": "티어",
        "name": f"{set_nm} 4세트 (냉기 효과)",
        "effect": spell_desc(cli, ts["spell_4p"]),
        "adoption": pct(n4, n_fr) + " — 4부위 이상 착용",
        "observed_buff_id": None,
        "rotation_impact": "무관",
        "note": "수치 패시브(서리의 손가락 소모가 더 아픔). 새 버프·버튼 없음.",
        "text_source": "Blizzard API spell 1264837",
    })

    tcf = trinket_counts(fr)
    vael_timing = first_use_offsets(fr_cd, 1260459)
    trinket_rows_fr = [
        (249343, "자동 프록", fr_obs(1266686, 1266687), "무관",
         "야수냥과 동일 — 알아서 터지는 지능 중첩 프록. 누르는 타이밍 없음."),
        (249346, "사용형", fr_obs(1260459), "오프너 정렬",
         f"특화 +148이 15초에 걸쳐 줄어드는 사용형, 1분 30초 쿨. 302킬 중 {vael_timing['kills_used']}킬에서 사용, "
         f"쓴 킬의 절반이 시작 {vael_timing['first_use_mid_s']}초 안에 눌렀고 10초 안 사용이 "
         f"{vael_timing['used_within_10s_pct']}% — 오프너에 맞추고 이후 쿨마다."),
    ]
    for iid, kind, obs, impact, note in trinket_rows_fr:
        tip = item_tooltip(cli, iid)
        fr_rows.append({
            "source": "장신구",
            "item_id": iid,
            "name": (tip or {}).get("name") or str(iid),
            "effect": " / ".join(filter(None, (s.get("text") for s in (tip or {}).get("spells", [])))) or "확인 불가",
            "use_type": kind,
            "adoption": pct(tcf.get(iid, 0), n_fr),
            "observed_buff_id": obs,
            "rotation_impact": impact,
            "note": note,
        })

    fr_rows.append({
        "source": "영웅",
        "name": "주문술사 — 쇄편폭풍",
        "effect": "주문 시전으로 서리 쇄편이 쌓이고, 일정량이 모이면 쇄편폭풍이 자동으로 몰아침.",
        "adoption": pct(885, n_fr) + " (frost_talent_splits: 885명 전원 주문술사)",
        "observed_buff_id": fr_obs(1247908),
        "rotation_impact": "무관",
        "note": "완전 자동 축적/발사. 버프는 매 킬 100% 관측 — 화면에 뜨는 이유 설명용으로만 가이드에 한 줄.",
    })

    # ================= 저장 =================
    meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inputs": "talent_trees.json + rankings_zone46_mythic_dps_top100.csv + v2_cache_player_fight.json "
                  "+ 이벤트 캐시(BM 362킬·냉법 302킬) + Blizzard API(툴팁 문구, ko_KR)",
        "rotation_impact_기준": "추적 필요=버프를 보고 플레이가 바뀜 / 오프너 정렬=시작 타이밍에 맞춰 누름 / 무관=자동이라 관리 불필요",
        "숫자_읽는_법": "adoption은 상위권 표본 중 몇 명이 채택했는지, observed pct는 몇 %의 킬 로그에서 그 버프가 실제로 떴는지.",
    }
    out_bm = {"_meta": {**meta, "spec": "Hunter|BeastMastery", "sample_n": n_bm, "event_kills": bm_kills},
              "sources": bm_rows}
    out_fr = {"_meta": {**meta, "spec": "Mage|Frost", "sample_n": n_fr, "event_kills": fr_kills},
              "sources": fr_rows}
    (DATA / "proc_sources_bm.json").write_text(json.dumps(out_bm, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "proc_sources_frost.json").write_text(json.dumps(out_fr, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장: data/proc_sources_bm.json, data/proc_sources_frost.json")

    for tag, rows in (("BM", bm_rows), ("Frost", fr_rows)):
        print(f"\n==== {tag} ====")
        for r in rows:
            obs = r.get("observed_buff_id")
            obs_s = ", ".join(f"{o['id']}({o['name']}) {o['pct']}%" for o in obs) if obs else "-"
            print(f" [{r['source']}] {r['name']}")
            print(f"   채택 {r['adoption']} | 판정 {r['rotation_impact']} | 관측 {obs_s}")


if __name__ == "__main__":
    main()
