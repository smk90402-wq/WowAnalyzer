"""BM 필러 선택 버프 조건부 분석 — '어떤 버프가 떠 있을 때 코브라를 눌렀나'.

사용자 가설 검증: 상위 100 로그가 날카 충전이 있는데도 코브라를 먼저 누르는 이유가
'특정 프록/버프가 떠 있을 때 코브라 우선' 규칙 때문인지, 버프 ON/OFF 조건부로 전수 측정.

방법:
 1. 필러 시전(코브라 193455 / 날카 217200) 순간마다 플레이어 버프 상태를
    apply~remove 구간 복원으로 재구성 (시전과 같은 ms에 붙은 버프는 '결과'라 제외).
 2. 버프별 P(코브라 | 버프 ON) vs P(코브라 | 버프 OFF) → 차이가 큰 버프 양방향 추출.
 3. 야수의 격노 정렬 혼동 제거: 격노 밖(BW OFF) 시전만으로 같은 조건부를 한 번 더 계산.
 4. 펫 광기(272790)는 캐시 이벤트가 apply만 있고 갱신/스택/소멸이 없어 상태 복원 불가 → 측정 불가 명시.

데이터: 스크래치패드 bm_cd_events.json (362킬 풀 casts+buffs; bm_alt_events.json은
        버프가 2종만 필터되어 있어 전수 분석에 부적합 → 풀 캐시 사용).
사용: python tmp_mine_bm_buffcond.py explore   → 후보 버프 전수 테이블
      python tmp_mine_bm_buffcond.py           → 본 분석, data/bm_filler_buff_conditional.json
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")

KC = 34026; BARB = 217200; COBRA = 193455
WT_IDS = {1264359, 1264355}
BW = 19574
FRENZY = 272790
# tmp_mine_bm_alternation.py 실측 오프글쿨 목록
OFFGCD = {20572, 186257, 204526, 212382, 212396, 219199, 227723, 274738,
          304051, 1234768, 1236616, 1236998, 1253050, 1283817, 1283818}

ON_TYPES = ("applybuff", "refreshbuff", "applybuffstack")

BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어", 3179: "살라다르",
           3180: "선봉대", 3181: "우주의왕관", 3182: "벨로렌", 3183: "한밤의도래(르우라)",
           3306: "카이메루스"}


def load_names():
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    return {int(k): (v.get("name_ko") or v.get("name_en") or "?")
            for k, v in db.items() if isinstance(v, dict)}


def load_wanted():
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    bm = [r for r in rows if r["class"] == "Hunter" and r["spec"].replace(" ", "") == "BeastMastery"]
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    wanted = {}
    for r in bm:
        rid, fid, ch = r["report_id"], int(r["fight_id"]), r["character"]
        p = pf.get(f"{rid}:{fid}:{ch}")
        if not isinstance(p, dict): continue
        sid = p.get("sourceID")
        m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get("fights") or []) if x.get("id") == fid), None)
        if not f: continue
        key = f"{rid}:{fid}:{sid}"
        if key in wanted: continue
        wanted[key] = {"boss_id": int(r["encounter_id"]),
                       "boss": BOSS_KO.get(int(r["encounter_id"]), r["encounter_name"]),
                       "rank": int(r["rank"]), "char": ch,
                       "t0": f["startTime"], "t1": f["endTime"]}
    return wanted


def prep_fight(info, e):
    t0 = info["t0"]
    casts = sorted((c[0], c[1]) for c in (e.get("casts") or [])
                   if len(c) >= 3 and c[2] == "cast" and c[0] >= t0 - 1500)
    gcd = [(t, i) for t, i in casts if i not in OFFGCD]
    buffs = sorted((b for b in (e.get("buffs") or []) if len(b) >= 3), key=lambda b: b[0])
    return gcd, buffs


def frenzy_check(ev):
    """광기(272790)가 캐시에서 상태 복원 가능한 형태인지 실측."""
    types = Counter(); n_fights = 0; gaps = []
    for e in ev.values():
        evs = [b for b in (e.get("buffs") or []) if b[1] == FRENZY]
        if not evs: continue
        n_fights += 1
        for b in evs: types[b[2]] += 1
        ts = sorted(b[0] for b in evs)
        gaps.extend((b - a) / 1000 for a, b in zip(ts, ts[1:]))
    gaps.sort()
    med = gaps[len(gaps) // 2] if gaps else None
    return {"fights_with_events": n_fights, "event_types": dict(types),
            "apply_gap_median_s": round(med, 1) if med else None}


def buff_events_for_sweep(buffs, t0):
    """carried-in 버프(첫 이벤트가 remove/refresh/removestack)에 합성 apply 주입 후
    (t, bid, on/off/None) 이벤트열 반환. removebuffstack은 상태 유지(None)."""
    first_type = {}
    for b in buffs:
        if b[1] not in first_type:
            first_type[b[1]] = b[2]
    out = []
    for bid, ft in first_type.items():
        if ft in ("removebuff", "refreshbuff", "removebuffstack"):
            out.append((t0 - 10000, bid, True))   # 전투 시작 전부터 켜져 있었음
    for b in buffs:
        if b[2] in ON_TYPES:
            out.append((b[0], b[1], True))
        elif b[2] == "removebuff":
            out.append((b[0], b[1], False))
        # removebuffstack: 스택만 줄고 버프는 유지 → 무시
    out.sort(key=lambda x: x[0])
    return out


def sweep_fight(gcd, buffs, t0):
    """필러 시전마다 (spell, 그 순간 ON인 버프 집합, BW여부) 산출.
    시전과 같은 ms 이벤트는 반영 전(=결정 시점 상태)."""
    fills = [(t, i) for t, i in gcd if i in (BARB, COBRA)]
    bev = buff_events_for_sweep(buffs, t0)
    on = set(); j = 0
    out = []
    for t, spell in fills:
        while j < len(bev) and bev[j][0] < t:
            _, bid, flag = bev[j]
            if flag: on.add(bid)
            else: on.discard(bid)
            j += 1
        out.append((spell, frozenset(on), BW in on))
    return out


def collect(wanted, ev):
    """단일 필러판(난타<3)만 대상으로 버프별 조건부 카운트 집계."""
    # counts[bid] = [cobra_on, barb_on, cobra_on_bwoff, barb_on_bwoff]
    counts = defaultdict(lambda: [0, 0, 0, 0])
    tot = [0, 0, 0, 0]  # cobra, barb, cobra_bwoff, barb_bwoff
    buff_fights = Counter()
    # 판별 일관성 확인용: per_fight[bid] = list of (on_c, on_b, off_c, off_b)
    per_fight = defaultdict(list)
    n_st = 0
    for k, info in wanted.items():
        e = ev.get(k)
        if not e: continue
        gcd, buffs = prep_fight(info, e)
        if len(gcd) < 30: continue
        if sum(1 for _, i in gcd if i in WT_IDS) >= 3: continue  # 광역판 제외
        n_st += 1
        rows = sweep_fight(gcd, buffs, info["t0"])
        seen_bids = set(b[1] for b in buffs)
        for bid in seen_bids: buff_fights[bid] += 1
        f_on = defaultdict(lambda: [0, 0])
        f_tot = [0, 0]
        for spell, onset, bw_on in rows:
            ci = 0 if spell == COBRA else 1
            tot[ci] += 1
            f_tot[ci] += 1
            if not bw_on: tot[2 + ci] += 1
            for bid in onset:
                c = counts[bid]
                c[ci] += 1
                if not bw_on: c[2 + ci] += 1
                f_on[bid][ci] += 1
        for bid, (oc, ob) in f_on.items():
            per_fight[bid].append((oc, ob, f_tot[0] - oc, f_tot[1] - ob))
    return counts, tot, buff_fights, per_fight, n_st


def rate(c, b):
    return 100 * c / (c + b) if c + b else None


def build_rows(counts, tot, buff_fights, per_fight, names,
               min_on=400, min_off=400, min_fights=25):
    base = rate(tot[0], tot[1])
    base_bwoff = rate(tot[2], tot[3])
    rows = []
    for bid, (oc, ob, oc2, ob2) in counts.items():
        offc, offb = tot[0] - oc, tot[1] - ob
        if oc + ob < min_on or offc + offb < min_off: continue
        if buff_fights.get(bid, 0) < min_fights: continue
        p_on, p_off = rate(oc, ob), rate(offc, offb)
        # 격노 밖만
        offc2, offb2 = tot[2] - oc2, tot[3] - ob2
        p_on2 = rate(oc2, ob2) if oc2 + ob2 >= 200 else None
        p_off2 = rate(offc2, offb2) if offc2 + offb2 >= 200 else None
        # 판별 일관성: ON/OFF 양쪽에 5회 이상 필러가 있는 판 중, ON쪽 코브라 비율이 더 높은 판 수
        cons_n = cons_up = 0
        for fc, fb, xc, xb in per_fight.get(bid, []):
            if fc + fb >= 5 and xc + xb >= 5:
                cons_n += 1
                if rate(fc, fb) > rate(xc, xb): cons_up += 1
        rows.append({
            "buff_id": bid, "name": names.get(bid, f"spell{bid}"),
            "fights": buff_fights.get(bid, 0),
            "on_casts": oc + ob, "off_casts": offc + offb,
            "cobra_pct_on": round(p_on, 1), "cobra_pct_off": round(p_off, 1),
            "diff": round(p_on - p_off, 1),
            "cobra_pct_on_bw_off": round(p_on2, 1) if p_on2 is not None else None,
            "cobra_pct_off_bw_off": round(p_off2, 1) if p_off2 is not None else None,
            "diff_bw_off": round(p_on2 - p_off2, 1) if p_on2 is not None and p_off2 is not None else None,
            "fights_on_higher": f"{cons_up}/{cons_n}" if cons_n else None,
        })
    rows.sort(key=lambda r: -abs(r["diff"]))
    return rows, base, base_bwoff


# ── 정체 확인: 특성 트리 desc 검색 ─────────────────────────────

def talent_lookup(bid, name_ko):
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))
    bm = tt["Hunter/Beast Mastery"]
    pools = [("직업", bm.get("class") or []), ("전문화", bm.get("spec") or [])]
    for hname, hnodes in (bm.get("hero") or {}).items():
        pools.append((f"영웅:{hname}", hnodes if isinstance(hnodes, list) else hnodes.get("nodes") or []))
    hits = []
    for src, nodes in pools:
        for n in nodes:
            for o in (n.get("options") or []):
                direct = o.get("spell_id") == bid
                named = bool(name_ko) and name_ko != "?" and (
                    name_ko == o.get("name") or name_ko in (o.get("desc") or ""))
                if direct or named:
                    hits.append({"tree": src, "talent": o.get("name"),
                                 "spell_id": o.get("spell_id"),
                                 "match": "spell_id" if direct else "이름/설명",
                                 "desc": (o.get("desc") or "")[:220]})
    return hits


def main():
    names = load_names()
    wanted = load_wanted()
    ev = json.load(open(SCRATCH / "bm_cd_events.json", encoding="utf-8"))
    print(f"이벤트 캐시 적중: {len(ev)}/{len(wanted)}", flush=True)

    fz = frenzy_check(ev)
    print(f"광기(272790) 캐시 실태: {fz}", flush=True)

    counts, tot, buff_fights, per_fight, n_st = collect(wanted, ev)
    print(f"단일 필러판: {n_st}, 필러 시전 총 {tot[0]+tot[1]} (코브라 {tot[0]} / 날카 {tot[1]})", flush=True)
    rows, base, base_bwoff = build_rows(counts, tot, buff_fights, per_fight, names)
    print(f"기준선: 전체 코브라 비율 {base:.1f}% (격노 밖만 보면 {base_bwoff:.1f}%)")
    print(f"후보 버프(표본 충족): {len(rows)}개\n")

    hdr = f"{'버프':<24}{'판':>4}{'ON시전':>7}{'ON코브라%':>9}{'OFF코브라%':>10}{'차이':>7}{'격노밖차이':>9}{'판일관성':>10}"
    print(hdr)
    show = rows if "explore" in sys.argv else rows[:25]
    for r in show:
        d2 = r["diff_bw_off"]
        print(f"{r['name'][:22]:<24}{r['fights']:>4}{r['on_casts']:>7}"
              f"{r['cobra_pct_on']:>9}{r['cobra_pct_off']:>10}{r['diff']:>+7.1f}"
              f"{(f'{d2:+.1f}' if d2 is not None else '-'):>9}{(r['fights_on_higher'] or '-'):>10}"
              f"  ({r['buff_id']})")
    if "explore" in sys.argv:
        return

    # ── 정체 확인 + 분류 (explore 결과 + 특성 트리 desc로 확정) ──────────
    KIND = {
        1258338: "특성 버프(영웅:무리의 지도자, 쇄도! 472741) — 격노 시전 시 부여, '다음 살상 명령'이 쇄도를 일으킴. 격노 직후 창 표시",
        1258344: "특성 버프(쇄도! 472741의 진행 창) — 쇄도 발동 후 7초 야생동물 돌진 구간",
        1265063: "특성 버프(전문화, 피의 광란 407412) — 격노 후 10초간 날카 출혈이 2배속으로 들어감 → 이 창에 날카를 넣을 직접적 이유",
        19574:   "특성 버프(전문화) — 야수의 격노 본체(15초)",
        186254:  "특성 버프 — 야수의 격노(펫측 기록, 19574와 동일 창)",
        1235388: "특성 버프 — 야수의 격노(광포한 야수측 기록, 격노 창과 정렬)",
        1285912: "특성 버프 — 야수의 격노 파생(장시간 기록, 부차적)",
        471877:  "특성 버프(무리의 지도자의 포효 471876) — 30초 주기 '다음 살명이 맹수 소환' 대기 상태(업타임 ~91%). OFF=소환 직후 창",
        471878:  "특성 버프(무리의 지도자의 포효) — 소환 창 변형(곰/멧돼지/와이번 중 하나)",
        472324:  "특성 버프(무리의 지도자의 포효) — 소환 창 변형",
        472325:  "특성 버프(무리의 지도자의 포효) — 소환 창 변형",
        472640:  "특성 프록(멧돼지 기수 472639) — '다음 코브라 사격 공격력 +200%' 프록",
        471881:  "특성 버프(와이번의 울음소리) — 와이번 소환 중 공격력 +10% 창",
        459731:  "특성 버프(사냥지배자의 부름 459730) — 광포한 야수 소환 카운터(하티/펜리르)",
        1276720: "특성 버프(자연의 동맹 1273043) — 격노 시 동물 친구 15초 소환",
        246152:  "날카 자체 버프 — 날카 시전 후 8초 집중 회복. 날카를 '눌렀기 때문에' 켜지는 결과 버프(원인 아님)",
        272790:  "펫 버프(광기) — 캐시 기록 불완전(apply만 ~30초 간격), 이 행의 수치는 신뢰 불가",
        20572:   "종족 특성(오크, 피의 격노) — 버스트에 정렬되는 외부성 버프",
        383781:  "장신구(알게타르 수수께끼 상자) — 사용 효과, 버스트 정렬",
        1236616: "물약 — 빛의 잠재력(주스탯 30초)",
        1236998: "물약 — 날뛰는 방종의 비약",
        1266686: "장신구 — 알른시야",
        1266687: "장신구 — 알른멸시의 정수",
        1241715: "장신구 — 공허의 기세",
        1229746: "장신구 — 비전매듭 통찰",
        1260615: "장신구 — 광휘의 꽁지깃",
        1287425: "장신구 — 공허에 물든 보주",
        1258885: "장신구(세계수 계열) — 텔드랏실의 끈기",
        1258886: "장신구(세계수 계열) — 놀드랏실의 현명함",
        1258887: "장신구(세계수 계열) — 아미드랏실의 신속함",
        1258890: "장신구(세계수 계열) — 샬라드라실의 힘",
        1285161: "장신구 — 보호의 독버섯",
        118922:  "이동기 버프(급가속) — 유틸, 필러와 무관",
        186257:  "이동기 버프(치타의 상)",
        186258:  "이동기 버프(치타의 상)",
        264735:  "생존기 버프(적자생존)",
    }
    for r in rows:
        r["identity"] = KIND.get(r["buff_id"], "미분류(효과 미미)")
        hits = talent_lookup(r["buff_id"], r["name"])
        if hits:
            r["talent_hits"] = hits[:2]
        if r["buff_id"] == FRENZY:
            r["reliable"] = False

    frenzy_note = {
        "measurable": False,
        "cache_evidence": fz,
        "note": "광기(272790)는 펫 버프. 캐시엔 applybuff만 판당 ~7회, 약 30초 간격으로 남아 있고 "
                "갱신/스택/소멸 이벤트가 없음 — 실제 광기는 날카마다(~8초) 갱신되는 3스택 버프라 "
                "이 기록으로는 ON/OFF 구간 복원이 불가능. '광기 유지가 필러 선택을 가르는가'는 이 캐시로 측정 불가. "
                "(표의 272790 행은 참고용일 뿐 수치를 믿으면 안 됨)",
    }

    bw_row = next((r for r in rows if r["buff_id"] == BW), None)
    key_ids = {1258338, 1258344, 1265063, 19574, 246152, 472640}
    key_rows = [r for r in rows if r["buff_id"] in key_ids]

    out = {
        "meta": {
            "date": "2026-07-04",
            "question": "특정 프록/버프가 떠 있을 때 코브라를 우선하는가 — 필러 시전 순간 버프 상태 전수 조건부 분석",
            "sample": f"12.0.7 top100 신화 BM 단일 필러판 {n_st}킬, 필러 시전 {tot[0]+tot[1]}회 "
                      f"(코브라 {tot[0]} / 날카 {tot[1]})",
            "method": "버프 apply~remove 구간 복원(시전과 같은 ms 이벤트는 결정 이후로 간주). "
                      "버프별 P(코브라|ON) vs P(코브라|OFF). 격노 정렬 혼동 제거용으로 '격노 밖 시전만' 조건부 병기. "
                      "표본 기준: ON 400회+, OFF 400회+, 출현 25판+. "
                      "fights_on_higher = ON/OFF 양쪽 5회 이상인 판 중 ON쪽 코브라 비율이 더 높았던 판 수(방향 일관성).",
            "baseline_cobra_pct": round(base, 1),
            "baseline_cobra_pct_bw_off": round(base_bwoff, 1),
            "baseline_note": "이 분모는 '코브라+날카 시전만'(단일 필러판). 이전 분석의 54%는 살명 사이 전체 필러 분모라 수치가 다름.",
        },
        "frenzy_pet_buff": frenzy_note,
        "bestial_wrath_conditional": bw_row,
        "key_buffs": key_rows,
        "buffs_ranked_by_effect": rows[:40],
        "conclusion": {
            "cobra_calling_buff": "없음 — 코브라 선택 비율을 의미 있게 끌어올리는 프록/버프는 하나도 없다. "
                                  "겉보기 1위(날카로운 사격 246152, +50)는 날카를 '방금 눌렀기 때문에' 켜지는 결과 버프라 원인이 아니고, "
                                  "'다음 코브라 +200%'인 멧돼지 기수 프록이 떠 있어도 코브라 비율은 오히려 내려감(51.2% vs 63.0%) — "
                                  "그 창이 맹수 소환(날카 쿨 4초 감소, 무리 본능) 창과 겹치기 때문.",
            "barbed_calling_buffs": "뚜렷함 — 전부 '야수의 격노 창' 계열. 쇄도!(격노 직후, 코브라 4.1% vs 63.3%), "
                                    "쇄도 진행 7초(27.5% vs 67.1%), 피의 광란 10초(45.6% vs 68.4%, 197판 전부 같은 방향), "
                                    "격노 자체(54.1% vs 68.4%, 200판 전부 같은 방향). "
                                    "이유도 특성에 그대로 적혀 있음: 피의 향기(격노 시 날카 1충전 지급) + 피의 광란(격노 후 10초 날카 출혈 2배속).",
            "why_cobra_default": "격노 밖 평시엔 코브라가 68.4%로 기본 선택. 버프 조건이 아니라 상시 이유 때문 — "
                                 "코브라는 살상 명령 쿨 1초 단축(내장) + 절실한 소환장으로 무리의 지도자의 포효 쿨도 1초 단축. "
                                 "즉 코브라를 굴릴수록 살명과 맹수 소환이 빨리 돌아옴.",
            "frenzy": "펫 광기 유지가 선택을 가르는지는 이 캐시로 측정 불가(펫 버프 이벤트가 불완전하게 기록됨).",
            "guide_sentence": "코브라를 부르는 프록은 없다 — 반대로 '격노를 누른 직후 10초'(피의 향기 충전 + 피의 광란 2배속 출혈)가 "
                              "날카를 부르는 창이고, 그 창 밖의 남는 글쿨은 조건 없이 코브라가 기본이다(격노 밖 코브라 68%, 200판 전부 동일 방향).",
        },
    }
    json.dump(out, open(DATA / "bm_filler_buff_conditional.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n저장: data/bm_filler_buff_conditional.json")


if __name__ == "__main__":
    main()
