"""BM 오프너 재점검 — 마구잡이 난타 vs 야수의 격노 선후 관계.

질문: 쫄웨이브 절차는 '난타(휩쓸기) → 격노'인데 dealcycle 오프너는 '격노 → 난타'.
어느 게 맞나? 전투 개시(풀링)와 전투 중 쫄웨이브에서 순서가 다른가?

데이터: 스크래치패드 bm_alt_events.json (362킬 전체 캐스트 + 광기/날카 펫버프)
        — tmp_mine_bm_alternation.py 가 만든 캐시 재사용, WCL API 호출 없음.
출력: data/bm_opener_recheck.json
"""
from __future__ import annotations
import json, sys, csv
from pathlib import Path
from collections import Counter, defaultdict

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DATA = Path(r"C:\Users\smk90\OneDrive\바탕 화면\LogAnalyze\data")
SCRATCH = Path(r"C:\Users\smk90\AppData\Local\Temp\claude\C--Users-smk90-OneDrive-------LogAnalyze\14ae7942-82ef-4227-a050-cd5f2462c948\scratchpad")

KC = 34026; BARB = 217200; COBRA = 193455; BW = 19574
WT_IDS = {1264359, 1264355}
PUZZLE = 383781
FRENZY = 272790
BOSS_KO = {3176: "아베르지안", 3177: "보라시우스", 3178: "바엘고어&에조라크", 3179: "살라다르",
           3180: "선봉대", 3181: "우주의 왕관", 3182: "벨로렌", 3183: "한밤의 도래(르우라)",
           3306: "카이메루스"}
AOE_BOSSES = {3178, 3180, 3176}          # 광(쫄) 보스
ST_BOSSES = {3177, 3181, 3183, 3182}     # 단일 보스

# bm_alternation.json 채굴 때 실측으로 판별된 글쿨 안 먹는(오프글쿨/자동발동) 캐스트
OFFGCD = {20572, 186257, 204526, 212382, 212396, 219199, 227723, 274738, 304051,
          1234768, 1236616, 1236998, 1253050, 1283817, 1283818}
FORCE_KEEP = {BW} | WT_IDS   # 순서 판단 대상은 무조건 시퀀스에 남김


def load_names():
    db = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
    n = {int(k): (v.get("name_ko") or v.get("name_en") or f"#{k}")
         for k, v in db.items() if isinstance(v, dict)}
    for w in WT_IDS: n[w] = "마구잡이 난타"
    n[BW] = "야수의 격노"
    return n


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
        wanted[key] = {"eid": int(r["encounter_id"]), "rank": int(r["rank"]),
                       "t0": f["startTime"], "t1": f["endTime"]}
    return wanted


def med(vals):
    if not vals: return None
    v = sorted(vals); n = len(v)
    return round((v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2), 1)


def main():
    names = load_names()
    wanted = load_wanted()
    ev = json.load(open(SCRATCH / "bm_alt_events.json", encoding="utf-8"))
    print(f"캐시 {len(ev)}킬, wanted {len(wanted)}")

    def nm(i): return names.get(i, f"#{i}")
    def is_wt(i): return i in WT_IDS

    # ── 수집용 컨테이너 ─────────────────────────────
    per_boss = defaultdict(lambda: {
        "n": 0, "n20": 0,
        "seq_all": Counter(), "seq20": Counter(),
        "wt_open15": 0,          # 첫 15초 안에 난타
        "wt_any": 0, "wt_counts": [],
        "bw1": [], "wt1": [],
        "open_both": 0, "open_wt_first": 0, "open_gaps": [],
    })
    # 전투 중(개시 30초 이후) 격노 캐스트 기준: ±8초 안 난타의 선후
    wave = defaultdict(lambda: {"bw_n": 0, "near": 0, "wt_first": 0, "leads": [], "lags": []})
    # 난타 클러스터(=쫄웨이브 근사) 시작 기준: ±15초 안 격노의 선후
    cluster = defaultdict(lambda: {"n": 0, "bw_near": 0, "bw_after": 0, "offs": []})
    # 광기(펫버프) 발동 직전 캐스트 — 난타가 광기를 주는지 검증
    frenzy_src = Counter(); frenzy_n = 0
    # 개시 난타선행 vs 격노선행 — 등수 비교 (광 보스)
    open_order_rank = {"난타선행": [], "격노선행": []}

    for key, info in wanted.items():
        e = ev.get(key)
        if not e: continue
        eid, rank, t0 = info["eid"], info["rank"], info["t0"]
        casts = sorted((t, i) for t, i in e["casts"])
        # 글쿨 시퀀스 (표시/순서용)
        gseq = [(t, i) for t, i in casts if i not in OFFGCD or i in FORCE_KEEP]

        b = per_boss[eid]
        b["n"] += 1
        top20 = rank <= 20
        if top20: b["n20"] += 1

        # 1) 오프너: 개시 -3초부터 글쿨 캐스트 8개
        opener = [(t, i) for t, i in gseq if t >= t0 - 3000][:8]
        sig = tuple("마구잡이 난타" if is_wt(i) else nm(i) for t, i in opener)
        b["seq_all"][sig] += 1
        if top20: b["seq20"][sig] += 1

        wt_ts = [t for t, i in casts if is_wt(i)]
        bw_ts = [t for t, i in casts if i == BW]
        b["wt_counts"].append(len(wt_ts))
        if wt_ts: b["wt_any"] += 1
        if any(t0 <= t <= t0 + 15000 for t in wt_ts): b["wt_open15"] += 1
        if bw_ts: b["bw1"].append((bw_ts[0] - t0) / 1000)
        if wt_ts: b["wt1"].append((wt_ts[0] - t0) / 1000)

        # 2) 개시 순서: 첫 20초 안에 둘 다 있으면 선후·간격
        ow = [t for t in wt_ts if t <= t0 + 20000]
        ob = [t for t in bw_ts if t <= t0 + 20000]
        if ow and ob:
            b["open_both"] += 1
            if ow[0] < ob[0]: b["open_wt_first"] += 1
            b["open_gaps"].append((ob[0] - ow[0]) / 1000)  # +: 난타→격노
            if eid in AOE_BOSSES:
                open_order_rank["난타선행" if ow[0] < ob[0] else "격노선행"].append(rank)

        # 3) 전투 중 격노(개시 30초 이후) 기준 ±8초 난타
        w = wave[eid]
        for tb in bw_ts:
            if tb < t0 + 30000: continue
            w["bw_n"] += 1
            near = [tw for tw in wt_ts if abs(tw - tb) <= 8000]
            if not near: continue
            w["near"] += 1
            closest = min(near, key=lambda tw: abs(tw - tb))
            if closest < tb:
                w["wt_first"] += 1
                w["leads"].append((tb - closest) / 1000)
            else:
                w["lags"].append((closest - tb) / 1000)

        # 4) 난타 클러스터 시작(직전 20초 난타 없음, 개시 30초 이후) = 쫄웨이브 근사
        c = cluster[eid]
        prev = None
        for tw in wt_ts:
            if prev is not None and tw - prev <= 20000:
                prev = tw; continue
            prev = tw
            if tw < t0 + 30000: continue
            c["n"] += 1
            nb = [tb for tb in bw_ts if abs(tb - tw) <= 15000]
            if nb:
                c["bw_near"] += 1
                closest = min(nb, key=lambda tb: abs(tb - tw))
                off = (closest - tw) / 1000
                c["offs"].append(off)
                if off > 0: c["bw_after"] += 1

        # 5) 광기 스택 출처: applybuff(stack)/refresh 직전 1초 안 마지막 캐스트
        for bev in e.get("buffs", []):
            if bev[1] != FRENZY: continue
            if bev[2] not in ("applybuff", "applybuffstack", "refreshbuff"): continue
            tb = bev[0]
            cand = [(t, i) for t, i in casts if tb - 1000 <= t <= tb]
            if cand:
                frenzy_n += 1
                frenzy_src["마구잡이 난타" if is_wt(cand[-1][1]) else nm(cand[-1][1])] += 1

    # ── 리포트 조립 ─────────────────────────────
    def top_seqs(cnt, k=3):
        return [{"seq": list(s), "n": n} for s, n in cnt.most_common(k)]

    out_boss = {}
    for eid in sorted(per_boss, key=lambda e: (e not in ST_BOSSES, e)):
        b = per_boss[eid]
        entry = {
            "encounter_id": eid,
            "type": "광(쫄)" if eid in AOE_BOSSES else ("단일" if eid in ST_BOSSES else "기타"),
            "n": b["n"], "n_rank1_20": b["n20"],
            "opener_top3_rank1_20": top_seqs(b["seq20"]),
            "opener_top3_all": top_seqs(b["seq_all"]),
            "난타_사용_킬_pct": round(100 * b["wt_any"] / b["n"]),
            "난타_첫15초_pct": round(100 * b["wt_open15"] / b["n"]),
            "난타_횟수_중앙값": med(b["wt_counts"]),
            "첫_격노_s": med(b["bw1"]), "첫_난타_s": med(b["wt1"]),
        }
        if b["open_both"]:
            entry["개시_둘다_n"] = b["open_both"]
            entry["개시_난타선행_pct"] = round(100 * b["open_wt_first"] / b["open_both"])
            entry["개시_난타→격노_간격_s_중앙값"] = med(b["open_gaps"])
        out_boss[BOSS_KO.get(eid, str(eid))] = entry

    out_wave = {}
    for eid, w in sorted(wave.items()):
        if w["near"] == 0: continue
        out_wave[BOSS_KO.get(eid, str(eid))] = {
            "격노캐스트_개시30초이후_n": w["bw_n"],
            "8초내_난타있음_n": w["near"],
            "난타선행_pct": round(100 * w["wt_first"] / w["near"]),
            "난타→격노_s_중앙값": med(w["leads"]),
            "격노→난타_s_중앙값": med(w["lags"]),
        }

    out_cluster = {}
    for eid, c in sorted(cluster.items()):
        if c["n"] == 0: continue
        out_cluster[BOSS_KO.get(eid, str(eid))] = {
            "난타클러스터(쫄웨이브근사)_n": c["n"],
            "15초내_격노_n": c["bw_near"],
            "격노가_난타뒤_pct": round(100 * c["bw_after"] / c["bw_near"]) if c["bw_near"] else None,
            "난타→격노_offset_s_중앙값": med(c["offs"]),
        }

    out = {
        "meta": {
            "date": "2026-07-04",
            "n_kills": sum(b["n"] for b in per_boss.values()),
            "source": "scratchpad bm_alt_events.json (2026-07-03 rankings 362킬) 재사용, API 미호출",
            "method": [
                "오프너 = 전투 개시 -3초부터 글쿨 캐스트 8개 (오프글쿨/자동발동 제외, 격노·난타는 항상 포함)",
                "개시 선후 = 첫 20초 안에 난타·격노 둘 다 있는 킬에서 첫 시전 비교",
                "전투 중 = 개시 30초 이후 격노 캐스트 기준 ±8초 안 가장 가까운 난타의 선후",
                "쫄웨이브 근사 = 직전 20초에 난타 없던 난타 시전(클러스터 시작) 기준 ±15초 격노",
            ],
        },
        "per_boss": out_boss,
        "midfight_bw_vs_wt": out_wave,
        "wave_cluster_vs_bw": out_cluster,
        "frenzy_source_check": {
            "n_events": frenzy_n,
            "직전1초_마지막캐스트_분포": dict(frenzy_src.most_common(8)),
        },
        "open_order_rank_compare_aoe": {
            k: {"n": len(v), "rank_med": med([float(x) for x in v]),
                "top20_pct": round(100 * sum(1 for x in v if x <= 20) / len(v)) if v else None}
            for k, v in open_order_rank.items()
        },
        "conclusions": {
            "단일_표준_오프너": [
                "풀 ~2초 전: 알게타르 수수께끼(+물약)",
                "날카로운 사격 ×1~2 (중첩 소모)",
                "야수의 격노 (개시 2~3초)",
                "살상 명령 → 날카로운 사격 → 살상 명령 → 이후 살상↔필러(코브라·날카) 교대",
                "마구잡이 난타는 안 씀 (보라시우스 47킬 중 난타 0회)",
                "예외: 우주의 왕관(첫 격노 ~18초 홀드 파 존재)·르우라(전원 ~13.7초 홀드) — 기믹 때문에 격노만 늦추고 나머지는 동일",
            ],
            "광_표준_오프너": [
                "풀 ~2초 전: 알게타르 수수께끼(+물약)",
                "날카로운 사격 ×1~2",
                "마구잡이 난타 (휩쓸기 먼저) — 격노보다 먼저가 66~68%",
                "야수의 격노 (개시 3~4초)",
                "살상 명령 → 날카로운 사격 중심 광 교대(난타 8초마다)",
                "단, 아베르지안은 쫄이 1분 뒤에 나와서 개시는 단일 오프너 그대로 (첫 난타 중앙값 56초)",
            ],
            "쫄웨이브_절차": [
                "웨이브 등장 → 마구잡이 난타(휩쓸기 점화)가 먼저",
                "격노는 난타 뒤 — 아베르지안 81%·바엘고어 79% (난타 후 4~5.5초 뒤 격노)",
                "즉 기존 팁 '난타 → 격노+살상 즉발' 그대로 유효",
            ],
            "보라시우스_난타_규명": [
                "실측 47킬 전부 난타 0회 — 보라시우스 오프너에 난타가 낀 자료는 오탐/보스 혼동",
                "'격노→난타' 오프너의 출처는 boss_dealcycle.json 3178(바엘고어) — n=6 킬의 대표(medoid) 1개 시퀀스이고 일치율 62%. 46킬 전수로 보면 난타 선행이 66%로 다수",
                "펫 광기 스택용도 아님 — 광기 발동 직전 1초 캐스트 분포에 난타 0건 (광기는 날카로운 사격 계열로만 쌓임)",
            ],
        },
    }
    json.dump(out, open(DATA / "bm_opener_recheck.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
