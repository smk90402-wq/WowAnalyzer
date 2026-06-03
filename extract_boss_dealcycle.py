"""네임드별 실측 딜사이클 추출 — top-100 events 캐시에서 역산.

가이드의 '일반 로테'가 아니라, top 플레이어가 각 보스에서 실제로 어떻게 쳤는지:
- 오프너 합의 (시간순 첫 N캐스트의 최빈)
- 쿨기 첫사용/횟수 (야수의 격노·야생의 부름 등)
- 블러드 커버리지 + 타이밍
- 물약 커버리지 + 타이밍 (희박하면 참고표기)
- 핵심 버프 업타임%
- 빌드 분기 (회전베기=마구잡이 난타 노드로 광/단일)
- 킬타임

출력: data/boss_dealcycle.json (딜사이클 탭 '보스별' 뷰가 읽음).
스킬명 전부 공식 한글(spell_db). 사냥꾼 3스펙 먼저.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import Counter
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
DB = json.load(open(DATA / "spell_db.json", encoding="utf-8"))
def nm(s): return DB.get(str(s), {}).get("name_ko") or f"#{s}"

# 블러드/물약/쿨기 ID (캐시서 검증된 것)
LUST = {2825, 32182, 80353, 264667, 390386, 1222295, 272790, 335082, 116841,
        1277482, 1260277, 178207, 309658, 466904}
POTION = {1238443, 1236994, 1236998, 1235108, 431932, 431914, 1235110, 1235111}
TOPN = 25  # 보스당 분석 표본 (상위 N판)
BOX = 383781   # 알게타르 수수께끼 상자 (2분 버스트 장신구) — 첫 사용 타이밍 추출용
OPENER_S = 10  # 전투 N초 이내 사용 = 오프닝 사용으로 간주

# 오프너서 제외할 비-딜로테 캐스트 (종족특성·버프프록·이동기·생존기 — GCD 슬롯 먹어도 노이즈)
NOISE_CASTS = {
    20572, 33702, 33697,   # 피의 격노 (오크 종족특성)
    1236616,               # 빛의 잠재력 (버프 프록)
    109215, 118922,        # 급가속
    781, 186257, 186258,   # 철수, 치타의 상 (이동기)
    264735,                # 적자생존 (생존기/패시브 프록)
}

# 클래스별 핵심 쿨기/추적버프 (공식 한글 검증됨)
SPEC_CONFIG = {
    ("Hunter", "Beast Mastery"): {
        "cooldowns": {19574: "야수의 격노", 359844: "야생의 부름"},
        "track_buffs": {471877: "무리의 지도자의 포효", 1276720: "자연의 동맹"},
        "build_node": 102341, "build_label": ("마구잡이 난타(광)", "단일"),
    },
    ("Hunter", "Marksmanship"): {
        "cooldowns": {288613: "정조준", 466930: "검은 화살"},
        "track_buffs": {257622: "속사포"},
        "build_node": None, "build_label": (None, None),
    },
    ("Hunter", "Survival"): {
        "cooldowns": {360952: "협공", 266779: "협공"},
        "track_buffs": {259388: "창끝"},
        "build_node": None, "build_label": (None, None),
    },
}


def load():
    df = pd.read_csv(DATA / "rankings_zone46_mythic_dps_top100.csv")
    df["fid"] = df["fight_id"].astype(int)
    pf = json.load(open(DATA / "v2_cache_player_fight.json", encoding="utf-8"))
    ev = json.load(open(DATA / "v2_cache_events.json", encoding="utf-8"))
    meta = json.load(open(DATA / "v2_cache_report_meta.json", encoding="utf-8"))
    return df, pf, ev, meta


def fight_window(meta, rid, fid):
    m = meta.get(str(rid))
    if not m:
        return None
    f = next((x for x in (m.get("fights") or []) if x.get("id") == int(fid)), None)
    if not f:
        return None
    return f["startTime"], f["endTime"]


def analyze(df, pf, ev, meta, cls, spec, cfg):
    """한 (class,spec) 의 보스별 딜사이클."""
    sub = df[(df["class"] == cls) & (df["spec"] == spec)]
    out = {}
    for eid, g in sub.groupby("encounter_id"):
        g = g.sort_values("rank").head(TOPN)
        openers, bw_first, cotw_all = [], {}, {}
        lust_t, pot_t = [], []
        durs, builds = [], []
        box_opener, box_delayed = 0, []   # 상자: 오프닝 사용 수 / 미오프닝 첫사용 시각들
        buff_up = {bid: [] for bid in cfg["track_buffs"]}
        n = 0
        for _, r in g.iterrows():
            p = pf.get(f'{r["report_id"]}:{int(r["fid"])}:{r["character"]}')
            if not isinstance(p, dict):
                continue
            e = ev.get(f'{r["report_id"]}:{int(r["fid"])}:{p.get("sourceID")}')
            if not isinstance(e, dict):
                continue
            win = fight_window(meta, r["report_id"], r["fid"])
            if not win:
                continue
            t0, t1 = win
            dur = (t1 - t0) / 1000
            durs.append(dur)
            casts = e.get("casts") or []
            buffs = e.get("buffs") or []
            # 빌드 분기
            if cfg["build_node"]:
                builds.append(cfg["build_node"] in set(p.get("nodes") or []))
            # 오프너 — 비딜로테 캐스트 제외 + GCD 페이스 접기 (오프-GCD 노이즈 제거)
            seq = sorted((c[0], c[1]) for c in casts
                         if len(c) >= 3 and c[2] == "cast" and c[1] not in NOISE_CASTS)
            opener_clean = _gcd_collapse(seq, n=8)
            if opener_clean:
                openers.append(opener_clean)
            # 쿨기 첫사용 + 횟수
            for cid in cfg["cooldowns"]:
                ts = sorted((c[0] - t0) / 1000 for c in casts
                            if len(c) >= 3 and c[2] == "cast" and c[1] == cid)
                if ts:
                    bw_first.setdefault(cid, []).append(ts[0])
                    cotw_all.setdefault(cid, []).append(len(ts))
            # 상자(장신구) 첫 사용 타이밍 — 오프닝 사용 vs 미오프닝 첫사용
            box_ts = sorted((c[0] - t0) / 1000 for c in casts
                            if len(c) >= 3 and c[2] == "cast" and c[1] == BOX)
            if box_ts:
                if box_ts[0] <= OPENER_S:
                    box_opener += 1
                else:
                    box_delayed.append(box_ts[0])
            # 블러드/물약
            lt = [(b[0] - t0) / 1000 for b in buffs if len(b) >= 3 and b[1] in LUST and "apply" in b[2]]
            if lt:
                lust_t.append(min(lt))
            pt = [(b[0] - t0) / 1000 for b in buffs if len(b) >= 3 and b[1] in POTION and "apply" in b[2]]
            if pt:
                pot_t.append(min(pt))
            # 버프 업타임 (간이: apply~remove 페어 합 / dur)
            for bid in cfg["track_buffs"]:
                up = _uptime(buffs, bid, t0, t1)
                if up is not None:
                    buff_up[bid].append(up)
            n += 1
        if n < 5:
            continue
        # 오프너 — medoid (나머지와 가장 유사한 '실제' 시퀀스 1개). 위치별 최빈값은
        # 가짜 합성/중복을 만들어 폐기. 대표 시퀀스 + 그 시퀀스가 몇 % 와 일치하는지.
        opener_consensus = []
        opener_match = None
        if openers:
            med = _medoid(openers)
            # 대표 시퀀스가 다른 판들과 평균 몇 스킬 일치하나 (신뢰도)
            sims = [_seq_sim(med, o) for o in openers]
            opener_match = round(float(np.mean(sims)) * 100)
            opener_consensus = [{"skill": nm(s)} for s in med]
        # 쿨기 요약
        cds = []
        for cid, label in cfg["cooldowns"].items():
            if cid in bw_first and bw_first[cid]:
                cds.append({
                    "skill": label,
                    "first_s": round(float(np.median(bw_first[cid]))),
                    "count": int(np.median(cotw_all[cid])),
                })
        # 빌드
        build_info = None
        if builds and cfg["build_label"][0]:
            rate = float(np.mean(builds)) * 100
            build_info = {
                "aoe_label": cfg["build_label"][0], "st_label": cfg["build_label"][1],
                "aoe_pct": round(rate),
                "pick": cfg["build_label"][0] if rate >= 60 else (cfg["build_label"][1] if rate <= 40 else "혼재"),
            }
        # 상자(장신구) 타이밍 — 오프닝 사용 vs 미오프닝 첫사용 (사용자 요청)
        box_used = box_opener + len(box_delayed)
        box_info = None
        if box_used >= 3:
            box_info = {
                "used": box_used,
                "opener_pct": round(box_opener / box_used * 100),
                # 오프닝 안 쓸 때 첫 사용 시각 (미오프닝 판이 의미있을 때만)
                "delayed_first_s": round(float(np.median(box_delayed))) if box_delayed else None,
                "delayed_n": len(box_delayed),
            }
        out[int(eid)] = {
            "boss_kr": g.iloc[0]["encounter_name"],
            "n": n,
            "kill_s": round(float(np.median(durs))),
            "opener": opener_consensus,
            "opener_match": opener_match,
            "box": box_info,
            "cooldowns": cds,
            "lust": {"cover": f"{len(lust_t)}/{n}", "first_s": round(float(np.median(lust_t)))} if lust_t else None,
            "potion": {"cover": f"{len(pot_t)}/{n}", "first_s": round(float(np.median(pot_t)))} if pot_t else None,
            "buff_uptime": [{"buff": nm(bid), "pct": round(float(np.median(v)))}
                            for bid, v in buff_up.items() if v],
            "build": build_info,
        }
    return out


def _seq_sim(a, b):
    """두 오프너 시퀀스 위치별 일치율 (0~1)."""
    m = min(len(a), len(b))
    if not m:
        return 0.0
    return sum(1 for i in range(m) if a[i] == b[i]) / m


def _medoid(seqs):
    """나머지와 평균 유사도 최대인 '실제' 시퀀스 1개 (가짜 합성 회피)."""
    best, best_score = seqs[0], -1.0
    for cand in seqs:
        score = sum(_seq_sim(cand, o) for o in seqs)
        if score > best_score:
            best, best_score = cand, score
    return best


def _gcd_collapse(seq, n=8, gap_ms=750):
    """GCD 페이스로 접기 — 오프-GCD 프록/종족특성/장신구 노이즈 제거.

    WoW GCD 최저치=750ms. 그보다 가까운 연속 캐스트는 오프-GCD(펫 프록·종족특성·
    장신구 발동 등)라 GCD 슬롯을 안 먹음 → 첫 것만 남겨 실제 GCD 시퀀스로 정리.
    (살상 명령 충전식 1초 연타 등 ≥750ms 간격 정상 캐스트는 유지.)
    """
    out = []
    last_t = None
    for ts, sid in seq:
        if last_t is not None and ts - last_t < gap_ms:
            continue  # 오프-GCD: 직전 캐스트와 너무 가까움 → 슬롯 안 먹음
        out.append(sid)
        last_t = ts
        if len(out) >= n:
            break
    return out


def _uptime(buffs, bid, t0, t1):
    """간이 업타임: applybuff~removebuff 구간 합 / 전투시간."""
    evs = sorted((b[0], b[2]) for b in buffs if len(b) >= 3 and b[1] == bid)
    if not evs:
        return None
    total = 0.0
    open_t = None
    for ts, typ in evs:
        if "apply" in typ and open_t is None:
            open_t = ts
        elif "remove" in typ and open_t is not None:
            total += ts - open_t
            open_t = None
    if open_t is not None:
        total += t1 - open_t
    dur = t1 - t0
    return round(total / dur * 100) if dur else None


def main():
    df, pf, ev, meta = load()
    result = {}
    for (cls, spec), cfg in SPEC_CONFIG.items():
        boss_data = analyze(df, pf, ev, meta, cls, spec, cfg)
        if boss_data:
            result[f"{cls}|{spec}"] = boss_data
            print(f"{cls} {spec}: {len(boss_data)}개 보스 추출")
            for eid, d in boss_data.items():
                lust = f"블러드{d['lust']['cover']}@{d['lust']['first_s']}s" if d['lust'] else "블러드없음"
                pot = f"물약{d['potion']['cover']}" if d['potion'] else "물약X"
                build = f" [{d['build']['pick']}]" if d['build'] else ""
                print(f"  {d['boss_kr']}: n={d['n']} kill={d['kill_s']}s {lust} {pot}{build}")
    json.dump(result, open(DATA / "boss_dealcycle.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n저장: boss_dealcycle.json ({len(result)} 스펙)")


if __name__ == "__main__":
    main()
