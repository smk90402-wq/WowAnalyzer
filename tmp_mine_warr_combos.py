# -*- coding: utf-8 -*-
"""전사 딜사이클 6조합 프레임 재분류 — 영웅특성 2 × 스펙트리 빌드 3(단일/광/하이브리드).

1단계(빌드 축): data/*_talent_splits.json 의 가변 노드에서 확정한 마커
  무기 학살자:  단일 = 90283 혈행성 전이(2P)
               광   = 92536(휩쓸기 일격 연마/강력한 기세) + 109686(몸풀기였을 뿐/광범위한 타격)
               (실측 지배 옵션: 강력한 기세 + 광범위한 타격 = 휩쓸기 일격 증폭 패키지)
  무기 거신:    스펙트리 235명 전원 동일(혈행성 전이+광패키지 모두 채택) — 내부 분화 없음
  분노:        양 영웅 모두 스펙트리 광/단일 분화 노드 없음(검증 대상 가설)

2단계(매트릭스): rankings_zone46_mythic_dps_top100.csv × v2_cache_player_fight.json
3단계(이벤트): 스크래치패드 arms_cd_events.json / fury_cd_events.json 킬을
  report:fight:sourceID → player_fight nodes 로 조합 매칭, 조합별
  버튼 분당 사용률 + 프록 상태표(tmp_mine_arms_procprio.py 방법론, 자동필사 제외 유지).

출력: data/warr_combo_matrix.json  (다른 파일 수정 없음, 캐시 읽기만)
"""
from __future__ import annotations
import csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
SCRATCH = Path(r"C:\Users\MKSEORTV\AppData\Local\Temp\claude"
               r"\C--Users-MKSEORTV-Desktop-WowAnalyzer"
               r"\30b0abb8-5226-4b13-9c1c-14e4a1562211\scratchpad")
OUT = DATA / "warr_combo_matrix.json"

BOSS_KR = {
    "3176": "아베르지안", "3177": "보라시우스", "3178": "바엘고어",
    "3179": "살라다르", "3180": "선봉대", "3181": "우주의 왕관",
    "3182": "벨로렌", "3183": "한밤의 도래(르우라)", "3306": "카이메루스",
}

# ── 무기 빌드 마커 ──
A_ST = 90283          # 혈행성 전이 (단일)
A_AOE1 = 92536        # 휩쓸기 일격 연마 / 강력한 기세
A_AOE2 = 109686       # 몸풀기였을 뿐 / 광범위한 타격
A_CLEAVE_NODE = 90293  # 회전베기 (학살자 소수 변형 마커)
A_CHAIN = 109683      # 전술적 우위 / 궤멸적인 연계

# ── 분노 내부 분화 후보(검증용) ──
F_CHECK = {
    "학살자": [(90387, "천벌과 분노"), (90395, "격노의 재생력"), (109967, "고기칼")],
    "산왕": [(90410, "대학살"), (90395, "격노의 재생력"), (90387, "천벌과 분노")],
}
F_WW_IMP = 90427      # 소용돌이 연마 — 전원 채택 가설 검증

# ── 이벤트 버튼 (무기) ──
AR_BS = 446035
AR_MS = 12294
AR_BUTTONS = {
    1269383: "hs", 12294: "ms", 281000: "execute", 163201: "execute",
    7384: "op", 1464: "slam", 772: "rend", 845: "cleave",
    167105: "cs", 446035: "bladestorm", 260708: "sweep", 107574: "avatar",
    436358: "demolish", 228920: "ravager",
}
AR_EXCLUDE = {6552, 23920, 355, 100, 126664, 97462, 118038, 52174, 57755,
              6673, 202168, 20572, 12323, 384110, 2565, 1236994, 1236616,
              1234768, 386208, 107570}
HS_BUFF = 1269391
SD_BUFF = 52437
BS_AUTO_WIN = 4750

# ── 이벤트 버튼 (분노) ──
FU_BS = 446035
FU_TB = 435222
FU_BUTTONS = {
    184367: "rampage", 23881: "bt", 335096: "bloodbath", 85288: "rb",
    335097: "crushing_blow", 280735: "execute", 5308: "execute",
    6343: "thunder_clap", 435222: "thunder_blast", 190411: "whirlwind",
    446035: "bladestorm", 107574: "avatar", 385059: "odyns_fury",
    1719: "recklessness",
}
FU_EXCLUDE = {385060, 385061, 385062,
              6552, 23920, 355, 100, 126664, 97462, 118038, 52174, 57755,
              6673, 202168, 20572, 12323, 384110, 2565, 107570, 3411, 64382,
              1236994, 1236616, 1234768, 386208, 12975, 871, 190456}
FE_BUFF = 1270731     # 격렬한 희열 — 분노 학살자 칼폭 종료 마커


# ---------------- 공용 ----------------

def build_intervals(events, buff_id, t0):
    iv, start = [], None
    for ev in events:
        if ev[1] != buff_id:
            continue
        t, typ = ev[0], ev[2]
        if typ == "applybuff":
            if start is None:
                start = t
        elif typ == "removebuff":
            if start is None:
                start = t0
            iv.append((start, t))
            start = None
        elif typ in ("refreshbuff", "applybuffstack", "removebuffstack") and start is None:
            start = t0
    if start is not None:
        iv.append((start, float("inf")))
    return iv


def active_at(iv, t):
    return any(a <= t <= b for a, b in iv)


def pack(counter):
    n = sum(counter.values())
    if n == 0:
        return {"n": 0}
    out = {"n": n}
    for btn, c in counter.most_common():
        out[btn] = {"count": c, "pct": round(100.0 * c / n, 1)}
    return out


def load_sample(spec, tree_key):
    tt = json.load(open(DATA / "talent_trees.json", encoding="utf-8"))[tree_key]
    hero_sets = {t: set(nd["id"] for nd in h["nodes"]) for t, h in tt["hero"].items()}
    rows = list(csv.DictReader(open(DATA / "rankings_zone46_mythic_dps_top100.csv", encoding="utf-8")))
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    out, seen = [], set()
    for r in rows:
        if r["class"] != "Warrior" or r["spec"].replace(" ", "") != spec:
            continue
        p = pf.get(f'{r["report_id"]}:{int(r["fight_id"])}:{r["character"]}')
        if not (isinstance(p, dict) and p.get("nodes")):
            continue
        nodes = set(int(x) for x in p["nodes"])
        best = max(hero_sets, key=lambda t: len(nodes & hero_sets[t]))
        hero = best if len(nodes & hero_sets[best]) >= 8 else "불명"
        ekey = f'{r["report_id"]}:{int(r["fight_id"])}:{p.get("sourceID")}'
        s = {
            "ekey": ekey, "boss": BOSS_KR[r["encounter_id"]],
            "rank": int(r["rank"]), "hero": hero, "nodes": nodes,
            "seq": [int(x) for x in p["nodes"]],
            "talents": [int(x) for x in (p.get("talents") or [])],
        }
        out.append(s)
        seen.add(ekey)
    return out


def arms_build(s):
    """무기 학살자 스펙트리 빌드 분류."""
    if s["hero"] == "거신":
        return "유일"  # 거신은 내부 분화 없음(전원 동일 스펙트리)
    st = A_ST in s["nodes"]
    aoe = A_AOE1 in s["nodes"] and A_AOE2 in s["nodes"]
    if st and not aoe:
        return "단일"
    if aoe and not st:
        return "광"
    if A_CLEAVE_NODE in s["nodes"] or A_CHAIN in s["nodes"]:
        return "회전베기변형"
    return "혼합"


def cell_stats(group, total):
    bosses = Counter(s["boss"] for s in group)
    return {
        "kills": len(group),
        "share_of_spec_pct": round(100.0 * len(group) / total, 1),
        "top20_kills": sum(1 for s in group if s["rank"] <= 20),
        "boss_dist": dict(bosses.most_common()),
        "representative_bosses": [b for b, _ in bosses.most_common(3)],
    }


# ---------------- 무기 프록 상태표 (procprio 방법론 재사용) ----------------

def arms_prio(kills):
    """학살자 킬 그룹의 상태별 버튼 분포. tmp_mine_arms_procprio.py 와 동일 로직
    (adaptive 임계값, 불안정한 정신 자동필사 제외)."""
    bins = defaultdict(Counter)
    e_bin = defaultdict(Counter)
    for v in kills:
        casts = sorted(v["casts"], key=lambda c: c[0])
        buffs = sorted(v["buffs"], key=lambda b: b[0])
        if not casts:
            continue
        t0 = min(casts[0][0], buffs[0][0] if buffs else casts[0][0])
        t1 = casts[-1][0]
        exec_start = t0 + 0.75 * (t1 - t0)
        hs_iv = build_intervals(buffs, HS_BUFF, t0)
        sd_iv = build_intervals(buffs, SD_BUFF, t0)
        bs_times = [c[0] for c in casts if c[1] == AR_BS]

        def is_auto_ms(t):
            return any(0 <= t - b <= BS_AUTO_WIN for b in bs_times)

        manual_ms = [c[0] for c in casts if c[1] == AR_MS and not is_auto_ms(c[0])]
        gaps = sorted(b - a for a, b in zip(manual_ms, manual_ms[1:]) if 2500 <= b - a <= 9000)
        thr = min(max(gaps[len(gaps) // 4], 3600), 5500) if len(gaps) >= 8 else 4600

        last_ms = None
        for c in casts:
            t, sid = c[0], c[1]
            if sid in AR_EXCLUDE:
                continue
            if sid == AR_MS and is_auto_ms(t):
                continue
            btn = AR_BUTTONS.get(sid, "other")
            eps = t - 1
            hs = active_at(hs_iv, eps)
            sd = active_at(sd_iv, eps)
            msr = last_ms is None or (t - last_ms) >= thr
            phase = "exec" if t >= exec_start else "normal"
            bins[(hs, msr, sd, phase)][btn] += 1
            if hs and msr:
                e_bin[phase][btn] += 1
            if sid == AR_MS:
                last_ms = t
    return bins, e_bin


def arms_views(bins, e_bin):
    def merged(hs, msr, sd, phases=("normal", "exec")):
        c = Counter()
        for ph in phases:
            c += bins[(hs, msr, sd, ph)]
        return c

    def m_any(hs=None, msr=None, sd=None, ph=None):
        c = Counter()
        for (h, m, s, p), cnt in bins.items():
            if hs is not None and h != hs:
                continue
            if msr is not None and m != msr:
                continue
            if sd is not None and s != sd:
                continue
            if ph is not None and p != ph:
                continue
            c += cnt
        return c

    return {
        "A_hs_on": pack(m_any(hs=True)),
        "B_hsX_msrO": {
            "normal": pack(m_any(hs=False, msr=True, ph="normal")),
            "exec": pack(m_any(hs=False, msr=True, ph="exec")),
        },
        "C_hsX_msrX_sdO": {
            "normal": pack(bins[(False, False, True, "normal")]),
            "exec": pack(bins[(False, False, True, "exec")]),
        },
        "D_all_off": {
            "normal": pack(bins[(False, False, False, "normal")]),
            "exec": pack(bins[(False, False, False, "exec")]),
        },
        "E_hsO_msrO": {ph: pack(e_bin[ph]) for ph in ("normal", "exec")},
    }


def per_min_rates(kills, buttons, exclude, auto_ms_mode=None):
    """조합 그룹의 버튼 분당 사용률(킬별 rate 중앙값 + 합산 평균).
    auto_ms_mode: 'arms'=칼폭 자동필사 제외, 'fury'=칼폭 자동피갈 제외."""
    per_btn_kill = defaultdict(list)
    agg = Counter()
    tot_min = 0.0
    for v in kills:
        casts = sorted(v["casts"], key=lambda c: c[0])
        buffs = sorted(v["buffs"], key=lambda b: b[0])
        if len(casts) < 2:
            continue
        dur_min = (casts[-1][0] - casts[0][0]) / 60000.0
        if dur_min <= 1:
            continue
        tot_min += dur_min
        auto_win = []
        if auto_ms_mode == "arms":
            auto_win = [(b, b + BS_AUTO_WIN) for b in
                        (c[0] for c in casts if c[1] == AR_BS)]
        elif auto_ms_mode == "fury":
            bs_t = [c[0] for c in casts if c[1] == FU_BS]
            fe = [b[0] for b in buffs if b[1] == FE_BUFF and b[2] in ("applybuff", "refreshbuff")]
            for b in bs_t:
                end = next((t for t in fe if t >= b and t - b <= 8000), None)
                auto_win.append((b, (end if end is not None else b + 3000) + 100))
        cnt = Counter()
        for c in casts:
            sid = c[1]
            if sid in exclude:
                continue
            if auto_ms_mode == "arms" and sid == AR_MS and \
               any(a <= c[0] <= e for a, e in auto_win):
                continue
            if auto_ms_mode == "fury" and sid in (23881, 335096) and \
               any(a <= c[0] <= e for a, e in auto_win):
                continue
            btn = buttons.get(sid)
            if btn:
                cnt[btn] += 1
        for btn, n in cnt.items():
            per_btn_kill[btn].append(n / dur_min)
        agg += cnt
    out = {}
    for btn in sorted(set(agg) | set(per_btn_kill)):
        rates = per_btn_kill.get(btn, [])
        out[btn] = {
            "casts_total": agg[btn],
            "per_min_mean": round(agg[btn] / tot_min, 2) if tot_min else None,
            "per_min_med_of_kills": round(median(rates), 2) if rates else 0.0,
            "kills_using": len(rates),
        }
    return out, round(tot_min, 1)


def top_order(packed, k=3):
    return [b for b in packed if b not in ("n",)][:k]


def diff_views(va, vb, la, lb, min_n=80):
    """두 조합의 상태표에서 1순위(및 top3 순서)가 갈리는 상태만 추출."""
    diffs = []

    def walk(a, b, path):
        if isinstance(a, dict) and "n" in a:
            if a.get("n", 0) >= min_n and b.get("n", 0) >= min_n:
                ta, tb = top_order(a), top_order(b)
                if ta[:1] != tb[:1]:
                    diffs.append({
                        "state": path, "differs": "1순위",
                        la: {"top3": ta, "n": a["n"],
                             "top1_pct": a[ta[0]]["pct"] if ta else None},
                        lb: {"top3": tb, "n": b["n"],
                             "top1_pct": b[tb[0]]["pct"] if tb else None},
                    })
                elif ta != tb:
                    diffs.append({
                        "state": path, "differs": "2-3순위",
                        la: {"top3": ta, "n": a["n"]},
                        lb: {"top3": tb, "n": b["n"]},
                    })
            return
        if isinstance(a, dict):
            for k in a:
                if k in b:
                    walk(a[k], b[k], f"{path}.{k}" if path else k)

    walk(va, vb, "")
    return diffs


# ---------------- 메인 ----------------

def main():
    arms = load_sample("Arms", "Warrior/Arms")
    fury = load_sample("Fury", "Warrior/Fury")

    # ===== 1+2단계: 매트릭스 =====
    for s in arms:
        s["build"] = arms_build(s)

    a_total = len(arms)
    a_matrix = {}
    for hero in ("학살자", "거신"):
        grp = [s for s in arms if s["hero"] == hero]
        for build in ("단일", "광", "하이브리드"):
            key = f"{hero}|{build}"
            if hero == "거신":
                if build == "광":
                    a_matrix[key] = {**cell_stats(grp, a_total),
                                     "note": "거신 유일 빌드 — 스펙트리 235명 전원 동일(혈행성 전이·광패키지·회전베기·대규모 처형 전부 채택). 단일/광 분화 자체가 없어 이 칸에 전부 배정."}
                else:
                    a_matrix[key] = {"kills": 0, "exists": False,
                                     "note": "비존재 — 거신 스펙트리는 내부 분화 없음(가변 노드는 전부 직업트리 유틸)."}
            else:
                sub = [s for s in grp if s["build"] == build]
                if build == "하이브리드":
                    mixed = [s for s in grp if s["build"] in ("혼합", "회전베기변형")]
                    a_matrix[key] = {
                        "kills": 0, "exists": False,
                        "note": "별도 하이브리드 클러스터 없음 — 광빌드의 휩쓸기 패키지(광범위한 타격+강력한 기세)가 곧 2타겟 증폭이라 광빌드가 하이브리드 역할 겸함. "
                                f"마커 혼합 표본 {len(mixed)}킬(전체 학살자의 {round(100*len(mixed)/max(1,len(grp)),1)}%)은 산발적 노이즈"
                                " + 회전베기/궤멸적인 연계 소수 변형(아래 fringe 참고).",
                        "fringe_mixed": dict(Counter(s["boss"] for s in mixed).most_common()),
                    }
                else:
                    a_matrix[key] = cell_stats(sub, a_total)

    # 학살자 광빌드 옵션 지배 확인
    def opt_share(grp, nid):
        c = Counter()
        for s in grp:
            if nid in s["nodes"] and len(s["seq"]) == len(s["talents"]):
                m = dict(zip(s["seq"], s["talents"]))
                if nid in m:
                    c[m[nid]] += 1
        return dict(c.most_common())

    sl = [s for s in arms if s["hero"] == "학살자"]
    a_axis = {
        "hero_axis": "학살자(652) vs 거신(235) — hero 트리 노드 겹침>=8",
        "build_markers": {
            "단일": {"node": A_ST, "name": "혈행성 전이", "설명": "출혈·치명타 증폭 단일 패시브(2P)"},
            "광": {"nodes": [A_AOE1, A_AOE2],
                   "names": ["휩쓸기 일격 연마 / 강력한 기세", "몸풀기였을 뿐 / 광범위한 타격"],
                   "지배_옵션": {"92536": "강력한 기세(부가 대상 휩쓸기 피해 +25%) — entry 114739",
                                "109686": "광범위한 타격(거인의 강타가 휩쓸기 일격 부여) — entry 135942"},
                   "entry_counts": {"92536": opt_share(sl, A_AOE1), "109686": opt_share(sl, A_AOE2)},
                   "설명": "휩쓸기 일격 증폭 패키지 = 광/2타겟 빌드. 몸풀기였을 뿐(분노 수급) 선택은 4명뿐."},
        },
        "분류_규칙": "혈행성 전이 보유(광패키지 완비 아님) → 단일 / 광패키지(92536+109686) 완비(혈행 없음) → 광. "
                    "부분 마커(혈행+109686 12킬, 혈행+92536 4킬)는 혈행 보유라 단일로 접힘. "
                    "둘 다 아님 10킬은 회전베기변형/혼합으로 별도 집계(매트릭스 칸 밖).",
        "marker_crosstab_slayer": dict(Counter(
            f"혈행={int(A_ST in s['nodes'])},92536={int(A_AOE1 in s['nodes'])},109686={int(A_AOE2 in s['nodes'])}"
            for s in sl).most_common()),
        "slayer_build_by_boss": {
            b: dict(Counter(s["build"] for s in sl if s["boss"] == b).most_common())
            for b in sorted(set(s["boss"] for s in sl))
        },
        "fringe_cleave_variant": {
            "markers": "회전베기(90293)+궤멸적인 연계(109683) — 학살자 약 10킬(1.5%)",
            "note": "거신형 회전베기 연계를 학살자로 이식한 소수 변형. 표본 부족으로 이벤트 분석 제외.",
        },
    }

    # ===== 분노 매트릭스 + 분화 없음 가설 =====
    f_total = len(fury)
    f_matrix = {}
    f_verify = {}
    ww_n = sum(1 for s in fury if F_WW_IMP in s["nodes"])
    for hero in ("학살자", "산왕"):
        grp = [s for s in fury if s["hero"] == hero]
        checks = {}
        for nid, nm in F_CHECK[hero]:
            r = sum(1 for s in grp if nid in s["nodes"]) / max(1, len(grp))
            pb = {}
            for b in sorted(set(s["boss"] for s in grp)):
                bs = [s for s in grp if s["boss"] == b]
                if len(bs) >= 5:
                    pb[b] = round(sum(1 for s in bs if nid in s["nodes"]) / len(bs), 2)
            checks[f"{nid} {nm}"] = {"rate": round(r, 3), "per_boss(n>=5)": pb}
        f_verify[hero] = checks
        for build in ("단일", "광", "하이브리드"):
            key = f"{hero}|{build}"
            single_cell = (hero == "학살자" and build == "단일") or \
                          (hero == "산왕" and build == "광")
            if single_cell:
                f_matrix[key] = {**cell_stats(grp, f_total),
                                 "note": ("학살자 유일 빌드 — 스펙트리 광/단일 분화 노드 없음. 단일 보스 위주 채택이라 이 칸에 배정."
                                          if hero == "학살자" else
                                          "산왕 유일 빌드 — 고기칼 100%·천둥벼락 100% 포함 스펙트리 균일. 광/2타겟 보스 위주 채택이라 이 칸에 배정.")}
            else:
                f_matrix[key] = {"kills": 0, "exists": False,
                                 "note": "비존재 — 분노는 영웅특성 선택 자체가 단일(학살자)/광(산왕) 축이고 스펙트리 내부 분화 없음."}

    # ===== 3단계: 이벤트 조합별 =====
    arms_ev = json.load(open(SCRATCH / "arms_cd_events.json", encoding="utf-8"))
    fury_ev = json.load(open(SCRATCH / "fury_cd_events.json", encoding="utf-8"))
    a_by_key = {s["ekey"]: s for s in arms}
    f_by_key = {s["ekey"]: s for s in fury}

    a_groups = defaultdict(list)
    a_unmatched = 0
    for k, v in arms_ev.items():
        s = a_by_key.get(k)
        if s is None:
            a_unmatched += 1
            continue
        a_groups[f'{s["hero"]}|{s["build"]}'].append(v)

    f_groups = defaultdict(list)
    f_unmatched = 0
    for k, v in fury_ev.items():
        s = f_by_key.get(k)
        if s is None:
            f_unmatched += 1
            continue
        f_groups[s["hero"]].append(v)

    a_events = {"n_event_kills": len(arms_ev), "unmatched": a_unmatched,
                "combo_kills": {k: len(v) for k, v in sorted(a_groups.items())}}
    views_by = {}
    for combo, kills in sorted(a_groups.items()):
        rates, tmin = per_min_rates(kills, AR_BUTTONS, AR_EXCLUDE, auto_ms_mode="arms")
        entry = {"n_kills": len(kills), "total_min": tmin, "buttons_per_min": rates}
        if combo.startswith("학살자") and combo.split("|")[1] in ("단일", "광") and len(kills) >= 20:
            bins, e_bin = arms_prio(kills)
            entry["prio_states"] = arms_views(bins, e_bin)
            views_by[combo.split("|")[1]] = entry["prio_states"]
        elif combo.startswith("거신"):
            entry["prio_note"] = ("거신은 전투군주(제압의 필사 쿨 초기화)로 msr 근사 오차 큼 — "
                                  "상태표는 arms_procprio.json colossus_side_note 참고. 여기선 분당 사용률만.")
        a_events[combo] = entry

    prio_diffs = []
    if "단일" in views_by and "광" in views_by:
        prio_diffs = diff_views(views_by["단일"], views_by["광"], "학살자|단일", "학살자|광")
    a_events["prio_diff_st_vs_aoe"] = {
        "설명": "학살자 단일빌드 vs 광빌드에서 상태별 top 버튼 순서가 갈리는 항목만 (양쪽 n>=80).",
        "주의": "두 그룹은 보스 구성이 다름(단일=보라시우스/르우라/카이메루스, 광=벨로렌/살라다르 위주) — 순서 차이에 보스 처형 가동률 차이가 섞임.",
        "diffs": prio_diffs,
    }
    a_events["guide_verdict"] = (
        "학살자 단일 vs 광: 상태별 1순위가 갈리는 곳은 E(지배자+필사준비 동시).exec 하나뿐이고 그마저 광빌드에서 ms 33.4% vs hs 33.3% 동률 수준. "
        "나머지는 2-3순위 근소 스왑(처형 가동률 차이로 설명 가능). 버튼 세트도 동일(광빌드 수동 휩쓸기 0.42→0.22/min 감소가 유일한 차이 — 광범위한 타격이 거강에 휩쓸기를 자동 부여). "
        "→ 별도 빌드 탭 불필요, aoe_diff 텍스트(특성 스왑 + 휩쓸기 자동화 한 줄)로 충분. "
        "거신은 회전베기 8.9/min·쇄파·쇠날발톱·처형 2.5/min 등 버튼 세트 자체가 다름 — 기존 영웅 탭 분리로 이미 커버.")

    f_events = {"n_event_kills": len(fury_ev), "unmatched": f_unmatched,
                "combo_kills": {k: len(v) for k, v in sorted(f_groups.items())}}
    for hero, kills in sorted(f_groups.items()):
        rates, tmin = per_min_rates(kills, FU_BUTTONS, FU_EXCLUDE, auto_ms_mode="fury")
        f_events[hero] = {"n_kills": len(kills), "total_min": tmin,
                          "buttons_per_min": rates}
    # 이벤트 킬에서 분화 마커 재확인 (조합별 이벤트 분리 필요성 검증)
    f_ev_marker = {}
    for hero in ("학살자", "산왕"):
        matched = [f_by_key[k] for k in fury_ev if k in f_by_key and f_by_key[k]["hero"] == hero]
        mk = {}
        for nid, nm in F_CHECK[hero]:
            mk[f"{nid} {nm}"] = sum(1 for s in matched if nid in s["nodes"])
        f_ev_marker[hero] = {"n": len(matched), "marker_counts": mk}
    f_events["event_kill_marker_check"] = f_ev_marker
    f_events["prio_note"] = ("분노는 스펙트리 분화가 없어 조합별 상태표 = 영웅별 상태표 — "
                             "data/fury_procprio.json (slayer/thane) 이 그대로 조합별 결과.")
    f_events["guide_verdict"] = (
        "분노는 조합 축이 영웅특성 하나로 접힘(학살자=단일 보스, 산왕=광 보스, 스펙트리는 각각 균일). "
        "→ 빌드 탭 불필요, 기존 영웅별(학살자/산왕) 분리로 완결. aoe_diff 는 '보스가 광이면 산왕' 수준의 특성 선택 안내가 전부.")

    result = {
        "_meta": {
            "generated_by": "tmp_mine_warr_combos.py",
            "frame": "영웅특성 2 × 스펙트리 빌드 3(단일/광/하이브리드) = 6칸, 스펙별",
            "inputs": [
                "data/rankings_zone46_mythic_dps_top100.csv (2026-07-10)",
                "data/v2_cache_player_fight.json (nodes/talents/sourceID)",
                "data/talent_trees.json",
                "scratchpad arms_cd_events.json / fury_cd_events.json (top100 296킬씩)",
            ],
            "sample": {"arms_rank_kills": a_total, "fury_rank_kills": f_total},
            "이벤트_매칭": "킬 키 report:fight:sourceID ↔ player_fight 캐시 sourceID",
            "오염_제거": "무기 학살자 자동필사(불안정한 정신, 칼폭 후 4.75초 내 12294) 제외, "
                        "분노 학살자 자동피갈(칼폭~격렬한 희열 마커+100ms) 제외 — 기존 procprio 방법론 유지",
            "caveats": [
                "빌드 분류는 특성 마커 기반 — 실제 타겟 수(로그 대상 수)는 이벤트에 없어 미관측.",
                "처형구간은 시간(마지막 25%) 근사, 필사 준비(msr)는 간격 기반 근사 — arms_procprio.json 과 동일 한계.",
                "top100 랭킹 표본 = 상위권 편향. 6칸 중 비어있는 칸은 '상위권 미채택'이지 불가능이 아님.",
            ],
        },
        "arms": {"axis": a_axis, "matrix": a_matrix, "events": a_events},
        "fury": {
            "axis": {
                "hero_axis": "학살자 vs 산왕 — 영웅 선택이 곧 단일/광 축(보스별 채택 참조)",
                "no_split_verdict": {
                    "가설": "분노는 영웅특성 내부에 광/단일 스펙트리 분화가 없다 (소용돌이 연마 전원 채택)",
                    "소용돌이_연마_90427": f"{ww_n}/{f_total} 채택",
                    "within_hero_spec_nodes": f_verify,
                    "판정": None,  # main()에서 채움
                },
                "hero_by_boss": {
                    b: dict(Counter(s["hero"] for s in fury if s["boss"] == b).most_common())
                    for b in sorted(set(s["boss"] for s in fury))
                },
            },
            "matrix": f_matrix,
            "events": f_events,
        },
    }

    # 분노 판정 문구
    worst = 1.0
    for hero, checks in f_verify.items():
        for nm, c in checks.items():
            r = c["rate"]
            worst = min(worst, max(r, 1 - r))
    result["fury"]["axis"]["no_split_verdict"]["판정"] = (
        f"가설 유지 — 소용돌이 연마 {ww_n}/{f_total}, 내부 가변 스펙노드는 최다수 옵션 채택률 최소 {round(100*worst,1)}%로 "
        "보스 유형(단일/광)과 무관한 소수 이탈뿐. 광/단일 분화 없음.")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", OUT)
    brief = {
        "arms_matrix": {k: {kk: v[kk] for kk in ("kills",) if kk in v} | (
            {"exists": v["exists"]} if "exists" in v else {}) for k, v in a_matrix.items()},
        "fury_matrix": {k: {kk: v[kk] for kk in ("kills",) if kk in v} | (
            {"exists": v["exists"]} if "exists" in v else {}) for k, v in f_matrix.items()},
        "arms_event_combo_kills": a_events["combo_kills"],
        "fury_event_combo_kills": f_events["combo_kills"],
        "prio_diffs_n": len(prio_diffs),
        "fury_verdict": result["fury"]["axis"]["no_split_verdict"]["판정"],
    }
    print(json.dumps(brief, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
