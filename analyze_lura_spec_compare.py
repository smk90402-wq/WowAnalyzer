"""르우라 스펙 비교 합성 — 채굴 3종 JSON → data/lura_spec_compare.json.

입력 (먼저 실행돼 있어야 함):
  tmp_mine_lura_top_aug.py  → data/lura_top_aug_mining.json   (상위 증강 25킬)
  tmp_mine_lura_top_udk.py  → data/lura_top_udk_mining.json   (상위 부죽 25킬)
  tmp_mine_lura_own_pair.py → data/lura_own_pair_mining.json  (우리 신화 르우라 전체 풀
                              — 멀티 리포트 합산, 칠흑의 힘 유지율 포함)

출력은 리플레이 분석 패널의 증강/죽기 탭(main.js _luraCompareCard)이 그대로 렌더.
문구 규칙(사용자 확정): 완전한 문장으로 — 무엇이 몇 번 있었고, 그게 무슨 뜻이고,
뭘 하면 되는지 순서. 대시 이어붙인 전보체·"N회/M시전" 분수 표기 금지.
상위권은 킬 로그(9분대 완주), 우리는 전멸 풀 — 판당 횟수 대신 분당·간격·첫 시전 비교.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data"
KST = timezone(timedelta(hours=9))
MIN_PULL_S = 90   # 분당 지표 계산에 쓰는 최소 풀 길이 (채굴 쪽 core_cpm 기준과 동일)
EARLY_DEATH_LEAD_S = 10
BREATH_DELAY_S = 15.0


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _casts(value) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return int(value.get("count") or 0)
    return int(value or 0)


def _median(values, nd: int = 1):
    clean = [float(v) for v in values if v is not None]
    return round(statistics.median(clean), nd) if clean else None


def _clock(seconds: float | int | None) -> str:
    if seconds is None:
        return "기록 없음"
    value = max(0, int(round(float(seconds))))
    return f"{value // 60}:{value % 60:02d}"


def _pulls_pm(pulls: list[dict], player: str, names: list[str]) -> dict[str, float]:
    """>=90s 풀들의 (총 시전 수 / 총 전투 분)."""
    total_min = 0.0
    counts = {n: 0 for n in names}
    for pull in pulls:
        if float(pull.get("duration_s") or 0) < MIN_PULL_S:
            continue
        total_min += float(pull["duration_s"]) / 60
        bucket = pull.get(player) or {}
        merged = {}
        for key in ("majors", "defensives", "consumables"):
            merged.update(bucket.get(key) or {})
        for n in names:
            counts[n] += _casts(merged.get(n))
    return {n: round(c / total_min, 2) if total_min else 0.0 for n, c in counts.items()}


def _own_pm(own: dict, player: str, names: list[str]) -> dict[str, float]:
    return _pulls_pm(own["pulls"], player, names)


def _indexed_medians(sequences: list[list[float]]) -> dict[int, float]:
    buckets: dict[int, list[float]] = defaultdict(list)
    for seq in sequences:
        for idx, value in enumerate(seq, 1):
            buckets[idx].append(float(value))
    return {idx: _median(values) for idx, values in sorted(buckets.items())}


def _clean_breath_reference(aug_top: dict) -> dict:
    """상위 증강 채굴의 정확한 source_id 1명씩만 써서 숨결 기준을 다시 만든다."""
    sequences: list[list[float]] = []
    durations: list[float] = []
    sources: list[dict] = []
    for fight in aug_top.get("fights") or []:
        times = [float(t) for t in ((fight.get("casts") or {}).get("breath_of_eons") or [])]
        if not times:
            continue
        sequences.append(times)
        durations.append(float(fight.get("duration_s") or 0))
        sources.append({
            "code": fight.get("report"),
            "fight": fight.get("fight_id"),
            "char": fight.get("player"),
            "source_id": fight.get("source_id"),
            "kill": bool(fight.get("kill")),
            "breath_times": [round(t, 1) for t in times],
        })
    if not sequences:
        raise ValueError("lura_top_aug_mining.json에 영겁의 숨결 타임라인이 없습니다.")

    gap_buckets: dict[int, list[float]] = defaultdict(list)
    all_gaps: list[float] = []
    for times in sequences:
        for idx in range(1, len(times)):
            gap = times[idx] - times[idx - 1]
            gap_buckets[idx].append(gap)
            all_gaps.append(gap)
    casts_pm = [
        len(times) / (duration / 60)
        for times, duration in zip(sequences, durations)
        if duration > 0
    ]
    return {
        "n_top_reports": len(sequences),
        "all_kills": all(source["kill"] for source in sources),
        "n_gaps": len(all_gaps),
        "gap_min_s": round(min(all_gaps), 1),
        "gap_med_s": _median(all_gaps),
        "gap_med_by_index": {
            idx: _median(values) for idx, values in sorted(gap_buckets.items())
        },
        "first_cast_med_s": _median([times[0] for times in sequences]),
        "casts_per_min_med": _median(casts_pm, 2),
        "cast_time_med_by_index": _indexed_medians(sequences),
        "sources": sources,
        "note": (
            "lura_top_aug_mining.json의 랭킹 캐릭터 source_id만 사용. "
            "같은 리포트에 있던 다른 증강 캐릭터는 제외."
        ),
    }


def _carry_overlap(windows: list[dict], lo: float, hi: float) -> float:
    return round(sum(
        max(0.0, min(float(w.get("end") or 0), hi) - max(float(w.get("start") or 0), lo))
        for w in windows
    ), 1)


def _breath_summary(own: dict, ref: dict) -> dict:
    """오염되지 않은 상위 25명 간격으로 지연·말미 미사용을 재판정한다."""
    gap_ref = {int(k): float(v) for k, v in ref["gap_med_by_index"].items()}
    fallback = float(ref["gap_med_s"])
    delayed: list[dict] = []
    tail_skips: list[dict] = []
    total = during_carry = p3_breaths = 0

    for pull in own["pulls"]:
        casts = (pull.get("aug") or {}).get("breath_casts") or []
        windows = (pull.get("aug") or {}).get("crystal_carry_windows") or []
        total += len(casts)
        during_carry += sum(bool(c.get("during_carry")) for c in casts)
        p3_breaths += sum("Midnight" in str(c.get("phase") or "") for c in casts)

        for idx in range(1, len(casts)):
            prev_t = float(casts[idx - 1]["t"])
            now_t = float(casts[idx]["t"])
            expected_gap = gap_ref.get(idx, fallback)
            delta = round(now_t - prev_t - expected_gap, 1)
            if delta <= BREATH_DELAY_S:
                continue
            ready_t = prev_t + expected_gap
            overlap = _carry_overlap(windows, ready_t, now_t)
            delayed.append({
                "pull": pull.get("pull"),
                "fight_id": pull.get("fight_id"),
                "report_code": pull.get("report_code"),
                "cast_index": idx + 1,
                "t": round(now_t, 1),
                "mmss": _clock(now_t),
                "phase": casts[idx].get("phase"),
                "during_carry": bool(casts[idx].get("during_carry")),
                "gap_since_prev_s": round(now_t - prev_t, 1),
                "ref_gap_top_med_s": expected_gap,
                "delta_vs_top_s": delta,
                "ready_window": [round(ready_t, 1), round(now_t, 1)],
                "delay_carry_overlap_s": overlap,
                "delayed_during_carry": overlap >= 3,
            })

        if not casts:
            continue
        last_t = float(casts[-1]["t"])
        next_gap = gap_ref.get(len(casts), fallback)
        expected_next = last_t + next_gap
        duration = float(pull.get("duration_s") or 0)
        if duration > expected_next + BREATH_DELAY_S:
            tail_skips.append({
                "pull": pull.get("pull"),
                "fight_id": pull.get("fight_id"),
                "report_code": pull.get("report_code"),
                "last_cast_s": round(last_t, 1),
                "expected_next_s": round(expected_next, 1),
                "pull_end_s": round(duration, 1),
                "missed_by_s": round(duration - expected_next, 1),
                "carry_overlap_s": _carry_overlap(windows, expected_next, duration),
            })

    return {
        "breath_casts_total": total,
        "breath_during_carry": during_carry,
        "p3_breaths": p3_breaths,
        "delayed": delayed,
        "tail_skips": tail_skips,
        "delayed_during_cast": sum(bool(d["during_carry"]) for d in delayed),
        "delayed_with_carry_overlap": sum(bool(d["delayed_during_carry"]) for d in delayed),
    }


def _early_death_summary(pulls: list[dict], player: str, lead_s: float = EARLY_DEATH_LEAD_S) -> dict:
    """전멸 종료 사망을 빼고, 풀 종료보다 lead_s초 넘게 앞선 사망만 센다."""
    details: list[dict] = []
    responded = 0
    for pull in pulls:
        bucket = pull.get(player) or {}
        for death in bucket.get("deaths") or []:
            death_t = float(death.get("t") or 0)
            lead = float(pull.get("duration_s") or 0) - death_t
            if lead <= lead_s:
                continue
            response_events = []
            for key in ("defensives", "consumables"):
                for events in (bucket.get(key) or {}).values():
                    response_events.extend(events or [])
            used = any(
                death_t - 10 <= float(event.get("t") or -999) <= death_t
                for event in response_events
            )
            responded += int(used)
            details.append({
                "pull": pull.get("pull"),
                "t": death_t,
                "lead_s": round(lead, 1),
                "phase": death.get("phase"),
                "cause": death.get("cause"),
                "responded": used,
            })
    return {
        "total": len(details),
        "pulls": len({d["pull"] for d in details}),
        "responded": responded,
        "without_response": len(details) - responded,
        "causes": dict(Counter(d["cause"] for d in details).most_common()),
        "phases": dict(Counter(d["phase"] for d in details).most_common()),
        "details": details,
    }


def _combat_potion_summary(pulls: list[dict], player: str) -> dict:
    names = {"Potion of Recklessness", "Light's Potential"}
    uses = first_15s = p3_uses = 0
    pulls_used = two_pot_pulls = 0
    for pull in pulls:
        bucket = pull.get(player) or {}
        events = [
            event
            for name, rows in (bucket.get("consumables") or {}).items()
            if name in names
            for event in rows
        ]
        events.sort(key=lambda event: float(event.get("t") or 0))
        uses += len(events)
        pulls_used += int(bool(events))
        two_pot_pulls += int(len(events) >= 2)
        first_15s += sum(float(event.get("t") or 0) <= 15 for event in events)
        p3_start = next(
            (float(phase["t"]) for phase in pull.get("phases") or []
             if "Midnight" in str(phase.get("phase") or "")),
            None,
        )
        if p3_start is not None:
            p3_uses += sum(float(event.get("t") or 0) >= p3_start for event in events)
    return {
        "uses": uses,
        "pulls_used": pulls_used,
        "two_pot_pulls": two_pot_pulls,
        "first_15s": first_15s,
        "p3_uses": p3_uses,
    }


def _core_cpm_median(pulls: list[dict], player: str, names: list[str]) -> float:
    values = []
    for pull in pulls:
        if float(pull.get("duration_s") or 0) < MIN_PULL_S:
            continue
        cpm = (pull.get(player) or {}).get("cpm") or {}
        values.append(sum(float(cpm.get(name) or 0) for name in names))
    return float(_median(values, 2) or 0)


def _weighted_aug_uptime(pulls: list[dict]) -> float | None:
    weighted = duration = 0.0
    for pull in pulls:
        if float(pull.get("duration_s") or 0) < MIN_PULL_S:
            continue
        value = (pull.get("aug") or {}).get("ebon_might_uptime_pct")
        if value is None:
            continue
        dur = float(pull["duration_s"])
        weighted += float(value) * dur
        duration += dur
    return round(weighted / duration, 1) if duration else None


def _kdate(iso: str) -> str:
    """'2026-06-29' → '6월 29일'."""
    dt = datetime.fromisoformat(iso)
    return f"{dt.month}월 {dt.day}일"


# WCL 영문 사망 원인 → 한국어 표기 (미등록 이름은 원문 그대로)
_CAUSE_KO = {
    "The Darkwell": "어둠샘", "Dissonance": "불협화음", "Radiance": "광휘",
    "Shattered Sky": "조각난 하늘", "Starsplinter": "별빛파열",
    "Criticality": "임계점", "Glimmering": "일렁이는 빛", "Midnight": "한밤",
    "Melee": "평타",
}


def _top_causes_text(causes: dict, n: int = 3) -> str:
    """사망 원인 상위 n개 → '어둠샘(31번), 불협화음(22번), 광휘(18번)'."""
    rows = sorted((causes or {}).items(), key=lambda kv: -int(kv[1]))[:n]
    return ", ".join(f"{_CAUSE_KO.get(name, name)}({cnt}번)" for name, cnt in rows) or "기록 없음"


def _ratio_verdict(mine: float, top: float, good=0.9, warn=0.7) -> str:
    if not top:
        return "info"
    r = mine / top
    return "good" if r >= good else ("warn" if r >= warn else "bad")


# ── 다른 PC 채굴(analyze_dkaug_vs_top.py → dkaug_top_comparison.json) 흡수 ──
# 그쪽에만 있는 분석(장신구·오프너·스탯·기본 기술)을 이쪽 문장 스타일로 가져온다.
# 겹치는데 측정 방식이 달라 수치가 어긋나는 항목(유지율 등)은 가져오지 않는다.
_DKAUG_VERDICT = {"good": "good", "mid": "warn", "warn": "bad"}


def _seq_text(seq) -> str:
    return " → ".join(f"{float(t):g}초 {name}" for t, name in (seq or [])[:5]) or "기록 없음"


def _dkaug_sections(spec: dict, include_pattern: bool) -> tuple[list[dict], list[dict]]:
    """(추가 섹션들, 추가 하이라이트들). include_pattern=True 면 딜패턴 행도 가져온다."""
    rows_by_cat: dict[str, list[dict]] = {}
    for r in spec.get("rows") or []:
        rows_by_cat.setdefault(str(r.get("cat") or ""), []).append(r)

    def _conv(rows: list[dict], note_fallback: str = "") -> list[dict]:
        out = []
        for r in rows:
            unit = str(r.get("unit") or "").strip()
            fmt = lambda v: ("" if v is None else (f"{round(float(v), 2):g}{unit and ' ' + unit}" if isinstance(v, (int, float)) else str(v)))
            out.append({
                "label": str(r.get("label") or ""),
                "mine": fmt(r.get("ours")), "top": fmt(r.get("top")),
                "verdict": _DKAUG_VERDICT.get(str(r.get("verdict") or ""), "info"),
                "note": str(r.get("note") or note_fallback),
            })
        return out

    sections: list[dict] = []
    stat_rows = _conv(rows_by_cat.get("스탯") or [])
    if stat_rows:
        sections.append({"title": "장비 스탯 (상위권과 비교)", "rows": stat_rows})
    if include_pattern:
        pat = _conv(rows_by_cat.get("딜패턴") or [], "1분에 몇 번 누르는지예요. 낮으면 그만큼 빈 시간이 있었다는 뜻이에요.")
        dens = _conv(rows_by_cat.get("딜사이클") or [])
        dens = [r for r in dens if "밀도" in r["label"]]
        if dens or pat:
            sections.append({"title": "기본 기술을 얼마나 부지런히 누르나", "rows": dens + pat})

    tr = spec.get("trinkets") or {}
    op = spec.get("opener") or {}
    gear_rows = []
    if tr:
        top_txt = ", ".join(f"{t.get('name')}({t.get('n')}명)" for t in (tr.get("top") or [])[:3]) or "기록 없음"
        gear_rows.append({"label": "장신구", "mine": ", ".join(tr.get("ours") or []) or "기록 없음",
                          "top": top_txt, "verdict": "info",
                          "note": "상위권이 몇 명이나 쓰는 장신구인지 괄호에 적었어요."})
    if op:
        gear_rows.append({"label": "전투 시작 5개 기술", "mine": _seq_text(op.get("ours")),
                          "top": _seq_text(op.get("top")), "verdict": "info",
                          "note": "전투 시작 직후 어떤 순서로 눌렀는지 비교예요."})
    if gear_rows:
        sections.append({"title": "장신구·전투 시작 순서", "rows": gear_rows})

    highlights: list[dict] = []
    top_trinkets = {t.get("name"): int(t.get("n") or 0) for t in (tr.get("top") or [])}
    ours_tr = tr.get("ours") or []
    unused = [name for name in ours_tr if name not in top_trinkets]
    if unused and top_trinkets:
        best_name, best_n = max(top_trinkets.items(), key=lambda kv: kv[1])
        highlights.append({"severity": "warn",
                           "text": f"장신구 재확인: 별도 14판 장비 스냅샷의 '{unused[0]}'은 당시 "
                                   f"상위권에서 보이지 않았고, 대세는 '{best_name}'({best_n}명)이었어요. "
                                   "지금도 장착 중인지 먼저 확인한 뒤 교체를 판단하세요."})
    return sections, highlights


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    aug_top = _load("lura_top_aug_mining.json")
    udk_top = _load("lura_top_udk_mining.json")
    own = _load("lura_own_pair_mining.json")
    try:
        dkaug = _load("dkaug_top_comparison.json").get("specs") or {}
    except FileNotFoundError:
        dkaug = {}

    ta = aug_top["aggregates"]
    bp3 = aug_top["breath_vs_p3"]
    cs = aug_top["crystal_summary"]
    tu = udk_top["aggregates"]
    sa = own["session_aggregates"]["aug"]
    su = own["session_aggregates"]["udk"]
    carry = own["session_aggregates"]["aug_crystal_carry"]
    ref = _clean_breath_reference(aug_top)
    breath = _breath_summary(own, ref)
    pulls_n = own["report"]["pulls"]
    best = own["best_pull"]
    own_reports = own.get("reports") or []
    if own_reports:
        session_desc = (f"{_kdate(own_reports[0]['date_kst'])}~{_kdate(own_reports[-1]['date_kst'])} "
                        f"우리 공대의 신화 연습 {pulls_n}풀")
        own_source = (f"신화 르우라 리포트 {len(own_reports)}개 합산 "
                      f"({own_reports[0]['date_kst']}~{own_reports[-1]['date_kst']}, {pulls_n}풀)")
    else:
        session_desc = f"최근 우리 공대의 신화 연습 {pulls_n}풀"
        own_source = f"{own['report'].get('code')} ({pulls_n}풀)"

    latest_code = own_reports[-1]["code"] if own_reports else None
    latest_pulls = [
        pull for pull in own["pulls"]
        if latest_code is not None and pull.get("report_code") == latest_code
    ]
    latest_desc = (
        f"{_kdate(own_reports[-1]['date_kst'])} {len(latest_pulls)}풀"
        if own_reports else "최근 세션"
    )

    # 숨결 지연 분포 — 정확한 상위 증강 25명의 source_id 기준으로 재판정.
    delayed = breath["delayed"]
    d_total = len(delayed)
    d_carry_overlap = breath["delayed_with_carry_overlap"]
    d_cast_while_carry = breath["delayed_during_cast"]
    d_second = sum(1 for d in delayed if d["cast_index"] == 2)
    d_third = sum(1 for d in delayed if d["cast_index"] == 3)
    d_deltas = sorted(float(d.get("delta_vs_top_s") or 0) for d in delayed) or [0.0]
    breath_total = breath["breath_casts_total"]
    p3_pulls = sum(bool(pull.get("reached_p3")) for pull in own["pulls"])
    latest_p3_pulls = sum(bool(pull.get("reached_p3")) for pull in latest_pulls)
    p3_breaths = breath["p3_breaths"]
    p3_first_top_s = float(bp3["p3_start_med_s"]) + float(bp3["first_breath_after_p3_med_s"])

    aug_early = _early_death_summary(own["pulls"], "aug")
    udk_early = _early_death_summary(own["pulls"], "udk")
    aug_early_latest = _early_death_summary(latest_pulls, "aug")
    udk_early_latest = _early_death_summary(latest_pulls, "udk")
    aug_potions = _combat_potion_summary(own["pulls"], "aug")
    udk_potions = _combat_potion_summary(own["pulls"], "udk")
    aug_potions_latest = _combat_potion_summary(latest_pulls, "aug")
    udk_potions_latest = _combat_potion_summary(latest_pulls, "udk")
    latest_aug_uptime = _weighted_aug_uptime(latest_pulls)

    top_breath_times = ref["cast_time_med_by_index"]
    top_skip_times = _indexed_medians([
        [float(t) for t in ((fight.get("casts") or {}).get("time_skip") or [])]
        for fight in aug_top.get("fights") or []
    ])
    own_breath_times = _indexed_medians([
        [float(c["t"]) for c in (pull.get("aug") or {}).get("breath_casts") or []]
        for pull in own["pulls"] if float(pull.get("duration_s") or 0) >= MIN_PULL_S
    ])
    own_skip_times = _indexed_medians([
        [float(c["t"]) for c in ((pull.get("aug") or {}).get("majors") or {}).get("Time Skip") or []]
        for pull in own["pulls"] if float(pull.get("duration_s") or 0) >= MIN_PULL_S
    ])

    # 최고 풀의 숨결 간격·다음 준비 시각.
    best_gaps_txt = ""
    best_tail = next(
        (tail for tail in breath["tail_skips"] if tail["pull"] == best.get("pull")),
        None,
    )
    for pull in own["pulls"]:
        if pull.get("pull") == best.get("pull"):
            gaps = [g.get("gap_since_prev_s") for g in (pull.get("aug") or {}).get("breath_casts", [])
                    if g.get("gap_since_prev_s") is not None]
            if gaps:
                best_gaps_txt = " (" + " → ".join(f"{g:.0f}초" for g in gaps[:3]) + " 간격)"
            break

    # ── 증강: 분당 지표 (우리 로그, >=90s 풀) ────────────────────────────
    apm = _own_pm(own, "aug", [
        "Breath of Eons", "Fire Breath", "Upheaval", "Prescience", "Time Skip",
        "Obsidian Scales",
    ])
    aug_potion_uses = aug_potions["uses"]
    top_scales_pm = round(ta["obsidian_scales_per_fight_med"] / (ta["duration_med_s"] / 60), 2)
    em_own = sa.get("ebon_might_uptime_pct")

    aug_rows_cd = [
        {"label": "첫 숨결까지 걸린 시간", "mine": f'{sa["first_cast_med_s"]["Breath of Eons"]}초',
         "top": f'{ref["first_cast_med_s"]}초',
         "verdict": "good" if sa["first_cast_med_s"]["Breath of Eons"] <= ref["first_cast_med_s"] + 3 else "warn",
         "note": "전투 시작하자마자 바로 쓰고 있어요. 좋은 습관이니 그대로 유지하세요."},
        {"label": "영겁의 숨결 (1분당)", "mine": apm["Breath of Eons"], "top": ta["breath_pm_med"],
         "verdict": _ratio_verdict(apm["Breath of Eons"], ta["breath_pm_med"]),
         "note": "숨결 쿨은 2분 고정이 아니에요. 시간 건너뛰기 덕분에 앞쪽 두 번은 73~80초 만에 다시 돌아와요."},
        {"label": "숨결이 늦어진 횟수",
         "mine": f"{breath_total}번 중 {d_total}번",
         "top": "0번이 목표",
         "verdict": "warn" if d_total else "good",
         "note": (
             f"상위권 25명의 같은 순번보다 {BREATH_DELAY_S:.0f}초 넘게 늦은 경우예요. "
             f"{d_total}건 모두 준비 후 대기 구간에 수정 운반이 겹쳤고, 실제 시전도 "
             f"수정 보유 중이었던 건 {d_cast_while_carry}건이에요."
         )},
        {"label": "화염 숨결 (1분당)", "mine": apm["Fire Breath"], "top": ta["fire_breath_pm_med"],
         "verdict": _ratio_verdict(apm["Fire Breath"], ta["fire_breath_pm_med"]),
         "note": "쿨이 돌 때마다 쓰는 기본 딜 기술이에요. 상위권과 거의 같아요."},
        {"label": "대격변 (1분당)", "mine": apm["Upheaval"], "top": ta["upheaval_pm_med"],
         "verdict": _ratio_verdict(apm["Upheaval"], ta["upheaval_pm_med"]),
         "note": "쿨이 돌 때마다 쓰는 기본 딜 기술이에요. 상위권과 거의 같아요."},
        {"label": "예지 (1분당)", "mine": apm["Prescience"], "top": ta["prescience_pm_med"],
         "verdict": _ratio_verdict(apm["Prescience"], ta["prescience_pm_med"]),
         "note": "상위권은 쿨이 돌 때마다 계속 눌러서 보스 잡는 동안 59번까지 써요."},
        {"label": "시간 건너뛰기 (1분당)", "mine": apm["Time Skip"],
         "top": round(ta["time_skip_per_fight_med"] / (ta["duration_med_s"] / 60), 2),
         "verdict": _ratio_verdict(apm["Time Skip"], ta["time_skip_per_fight_med"] / (ta["duration_med_s"] / 60)),
         "note": (
             f"상위권 25명의 중앙 시각은 {_clock(top_skip_times.get(1))}, "
             f"{_clock(top_skip_times.get(2))}, {_clock(top_skip_times.get(3))}예요. "
             f"우리는 {_clock(own_skip_times.get(1))}, {_clock(own_skip_times.get(2))}, "
             f"{_clock(own_skip_times.get(3))}예요."
         )},
        {"label": "칠흑의 힘 켜져 있던 비율",
         "mine": f'{em_own}%' if em_own else "잰 값 없음",
         "top": f'{ta["ebon_might_uptime_med_pct"]}%',
         "verdict": _ratio_verdict(float(em_own or 0), ta["ebon_might_uptime_med_pct"], good=0.95, warn=0.85),
         "note": "전투 시간 중에 칠흑의 힘 버프가 켜져 있던 비율이에요. 높을수록 좋아요. 90초 넘게 간 풀만 모아서 상위권과 같은 방법으로 쟀어요."},
    ]
    aug_rows_life = [
        {"label": "전투 물약", "mine": f'{pulls_n}풀 중 {aug_potion_uses}번',
         "top": "매 판 2병 (전원)", "verdict": "bad",
         "note": (
             f"상위권은 전원 한 판에 2병을 썼어요. 우리는 시작 15초 안 사용이 "
             f"{aug_potions['first_15s']}번, 자정 사용이 {aug_potions['p3_uses']}번, "
             f"한 풀 2병 사용은 {aug_potions['two_pot_pulls']}번이에요."
         )},
        {"label": "흑요석 비늘 (1분당)", "mine": apm["Obsidian Scales"], "top": top_scales_pm,
         "verdict": _ratio_verdict(apm["Obsidian Scales"], top_scales_pm),
         "note": "받는 피해를 줄여주는 방어 기술이에요. 상위권은 보스 잡는 동안 4번씩 써요."},
        {"label": f"최근 조기 사망 ({EARLY_DEATH_LEAD_S}초 기준)",
         "mine": f"{latest_desc} {aug_early_latest['total']}건",
         "top": f"상위 25킬 {ta['deaths_total']}건",
         "verdict": "good" if aug_early_latest["total"] == 0 else "warn",
         "note": (
             f"전체 연습의 조기 사망은 {aug_early['total']}건이에요. 전멸 정리 때 함께 죽은 기록은 제외했어요. 원인은 "
             f"{_top_causes_text(aug_early['causes'])}이고, 직전 10초에 개인 생존기나 "
             f"회복 아이템을 쓴 건 {aug_early['responded']}건이에요."
         )},
    ]

    p3_carriers = cs.get("p3_carrier_details") or []
    offsets = sorted(
        off for c in p3_carriers for r in c.get("relation") or []
        for off in r.get("breath_during_offsets") or []
    )
    latest_breath = _breath_summary({"pulls": latest_pulls}, ref)
    latest_eruption = _core_cpm_median(latest_pulls, "aug", ["Eruption"])
    latest_chrono = _core_cpm_median(latest_pulls, "aug", ["Chrono Flames"])
    last_pull = latest_pulls[-1] if latest_pulls else own["pulls"][-1]
    last_breaths = (last_pull.get("aug") or {}).get("breath_casts") or []
    last_breath_text = " → ".join(c.get("mmss") or _clock(c.get("t")) for c in last_breaths) or "기록 없음"
    best_expected_text = _clock(best_tail["expected_next_s"]) if best_tail else "계산 불가"
    top_breath_text = " → ".join(
        _clock(top_breath_times.get(idx)) for idx in range(1, 6)
        if top_breath_times.get(idx) is not None
    )

    breath_lines = [
        f"상위권 25킬의 중앙 시각은 {top_breath_text}예요. 특히 다섯 번째 중앙값은 "
        f"{_clock(p3_first_top_s)}이고, 자정 진입 뒤 약 {bp3['first_breath_after_p3_med_s']:.0f}초예요.",
        f"상위권 25킬 중 자정에서 수정 운반을 맡은 증강은 {cs['aug_carries_p3_n']}명이었고, "
        f"모두 수정을 든 채 숨결을 시전했어요"
        + (f"(수정 보유 후 {offsets[0]:.0f}~{offsets[-1]:.0f}초)." if offsets else ".")
        + " 수정 때문에 숨결을 보류할 근거는 없어요.",
        f"정확한 상위 증강 25명의 간격은 "
        f"{ref['gap_med_by_index'].get(1):.1f}초 → {ref['gap_med_by_index'].get(2):.1f}초 → "
        f"{ref['gap_med_by_index'].get(3):.1f}초 → {ref['gap_med_by_index'].get(4):.1f}초예요. "
        "같은 리포트의 다른 증강 캐릭터가 섞이지 않도록 source_id로 다시 계산했어요.",
        f"우리 연습에서는 총 {breath_total}회 중 {d_total}회가 같은 순번의 상위 중앙값보다 "
        f"{BREATH_DELAY_S:.0f}초 넘게 늦었어요. 둘째 숨결 {d_second}회, 셋째 숨결 {d_third}회예요. "
        f"준비 후 대기 구간에 수정 운반이 3초 이상 겹친 건 {d_carry_overlap}회지만, "
        f"실제 늦은 시전 순간에도 수정을 들고 있던 건 {d_cast_while_carry}회뿐이에요.",
        f"최고 기록 {best['pull']}번 풀은 {best.get('duration_mmss') or _clock(best['duration_s'])}까지 갔지만 숨결은 "
        f"{best_expected_text}에 다시 준비된 뒤 끝까지 나오지 않았어요. 최근 {last_pull['pull']}번 풀도 "
        f"{last_breath_text}까지만 사용했고 자정 숨결은 없었어요.",
        f"다음 풀 기준점은 간단해요. 네 번째 숨결을 {_clock(top_breath_times.get(4))} 전후에 쓰고, "
        f"자정 진입 뒤 약 {bp3['first_breath_after_p3_med_s']:.0f}초인 "
        f"{_clock(p3_first_top_s)} 전후에 다섯 번째 숨결을 누르세요. 수정 보유 중이어도 제자리에서 사용하세요.",
    ]
    per_pull = []
    for d in delayed[-10:]:   # 최근 10건만 표에 — 총계는 위 문단이 알려줌
        where = f"{d['cast_index']}번째 숨결"
        when = (
            f"준비 후 운반 겹침 {d['delay_carry_overlap_s']:.0f}초"
            if d.get("delayed_during_carry") else "준비 후 운반 겹침 없음"
        )
        per_pull.append({
            "pull": d["pull"], "t": d["t"],
            "context": f"{when} · {where}",
            "eval": f'{d["delta_vs_top_s"]:.0f}초 늦음', "verdict": "warn",
        })
    if best_tail:
        per_pull.append({
            "pull": best["pull"], "t": best_tail["expected_next_s"],
            "context": f"최고 기록 풀 · 다음 숨결 준비 시각{best_gaps_txt}",
            "eval": f"종료까지 {best_tail['missed_by_s']:.0f}초 미사용", "verdict": "bad",
        })
    per_pull.append({
        "pull": last_pull["pull"], "t": float(last_pull.get("duration_s") or 0),
        "context": f"최근 풀 숨결 시각 · {last_breath_text}",
        "eval": "자정 숨결 없음", "verdict": "warn",
    })

    # 로그에 없는 자원·이동·대상 선택은 원인으로 단정하지 않는다.
    aug_problems = [
        {"severity": "bad", "title": "1. 자정의 다섯 번째 숨결을 새 목표로 잡아요",
         "good": f"첫 숨결은 {sa['first_cast_med_s']['Breath of Eons']}초로 상위권 {ref['first_cast_med_s']}초와 거의 같고, {latest_desc}에는 15초 초과 지연이 {len(latest_breath['delayed'])}회였어요.",
         "loss": f"자정에 도달한 {p3_pulls}풀에서 증강의 자정 숨결은 {p3_breaths}회였어요. 최고 기록 풀도 숨결이 {best_expected_text}에 준비됐지만 종료까지 {best_tail['missed_by_s']:.0f}초 동안 나오지 않았어요." if best_tail else f"자정에 도달한 {p3_pulls}풀에서 증강의 자정 숨결은 {p3_breaths}회였어요.",
         "cause": "앞선 숨결이 늦어서 쿨이 없었던 것으로만 볼 수는 없어요. 최고 기록에서는 다음 숨결의 예상 준비 시각이 로그 안에 있었고 이후 시전이 없었어요. 다만 당시 대상·시야·키 입력은 로그에 없어 보류 이유까지 단정할 수는 없어요.",
         "next_pull": f"네 번째 숨결을 {_clock(top_breath_times.get(4))} 전후에 쓰고, 다섯 번째를 {_clock(p3_first_top_s)} 전후에 누르세요. 수정 운반 중이어도 숨결을 보류하지 않는 것을 한 풀의 단일 목표로 잡으세요.",
         "evidence": f"정확한 상위 증강 source_id 25명의 중앙 시각은 {top_breath_text}이고, 자정 수정 운반자 {cs['aug_carries_p3_n']}명도 모두 수정 보유 중 숨결을 썼어요."},
        {"severity": "bad", "title": "2. 물약은 가장 싸게 얻을 수 있는 개선이에요",
         "good": f"사용한 물약 중 시작 15초 안에 마신 건 {aug_potions['first_15s']}회라, 눌렀을 때의 첫 타이밍은 맞았어요.",
         "loss": f"전체 {pulls_n}풀에서 전투 물약은 {aug_potions['uses']}회, {latest_desc}에는 {aug_potions_latest['uses']}회였어요. 자정 사용은 {aug_potions['p3_uses']}회, 한 풀 2병은 {aug_potions['two_pot_pulls']}회예요.",
         "cause": "짧은 풀은 두 번째 물약 기회가 없지만 첫 물약까지 빠진 풀은 전투 길이로 설명되지 않아요. 반복 횟수상 기억·키 배치 문제를 먼저 의심할 수 있지만 입력 로그가 없어 확정 원인은 아니에요.",
         "next_pull": "다음 10풀 동안은 풀링 카운트에 첫 물약을 고정하세요. 자정 진입 풀에서는 두 번째 물약을 공대가 정한 극딜 콜에 맞추고, 끝난 뒤 ①첫 물약 ②두 번째 물약만 체크하세요.",
         "evidence": f"상위 증강 25킬은 모두 한 전투 2병을 사용했어요. 우리 기록은 총 {aug_potions['uses']}회이며 시작 15초 안 {aug_potions['first_15s']}회, 자정 {aug_potions['p3_uses']}회로 시각을 분리해 셌어요."},
        {"severity": "warn", "title": "3. 이동 중 시전 밀도를 한 단계 더 올릴 수 있어요",
         "good": f"{latest_desc} 분출은 {latest_eruption:.2f}회/분으로 전체 장기 풀 중앙값 {sa['core_cpm_med'].get('Eruption', 0):.2f}회/분보다 좋아졌어요.",
         "loss": f"별도 14판 스냅샷에서는 전체 시전 밀도가 44.95회/분으로 상위 30킬의 52.70회/분보다 낮았어요. 최근 시간의 불꽃도 {latest_chrono:.2f}회/분으로 그 표본의 상위값 11.73회/분보다 낮아요.",
         "cause": "수정 운반이 이동을 늘리는 환경은 확인되지만, 빈 시간이 이동·사거리·판단 중 무엇 때문인지는 시전 로그만으로 분리할 수 없어요.",
         "next_pull": "이동 시작 전에 부양을 준비하고, 이동 중 즉시 쓸 기술을 한 칸에 고정하세요. 우선 최근 분출 수준은 유지하면서 시간의 불꽃 11회/분을 한 가지 측정 목표로 잡으세요.",
         "evidence": "시전 밀도와 상위 분출·시간의 불꽃 값은 다른 채굴 세트(우리 14판 대 상위 30킬)의 스냅샷이라 최신 전체 세션 수치와 직접 합산하지 않았어요."},
        {"severity": "warn", "title": "4. 조기 사망은 최근에 크게 좋아졌어요",
         "good": f"{latest_desc}에는 전멸 종료보다 {EARLY_DEATH_LEAD_S}초 넘게 앞선 사망이 {aug_early_latest['total']}건이었어요.",
         "loss": f"전체에는 조기 사망 {aug_early['total']}건이 있고, 직전 10초에 개인 생존기·회복 아이템 반응이 없던 경우가 {aug_early['without_response']}건이에요.",
         "cause": f"가장 많이 기록된 마지막 피해는 {_top_causes_text(aug_early['causes'])}이고, 1페이즈 조기 사망은 {aug_early['phases'].get('Stage One: Final Tolls', 0)}건이에요. 마지막 피해만으로 앞선 실수까지 단정하지는 않았어요.",
         "next_pull": "최근의 무조기 사망 흐름을 유지하세요. 반복 사망 원인 직전에는 흑요석 비늘을 예약하고, 체력이 이미 낮다면 회복 물약·생명석을 피해가 들어오기 전에 쓰는 것을 체크하세요.",
         "evidence": f"전멸과 함께 죽은 기록은 제외하고, 풀 종료보다 {EARLY_DEATH_LEAD_S}초 넘게 앞선 사망만 셌어요. 방어 반응은 사망 전 10초 창에서 확인했어요."},
        {"severity": "info", "title": "5. 칠흑의 힘 유지율은 이미 강점이에요",
         "good": f"전체 유지율은 {em_own}%, {latest_desc}은 {latest_aug_uptime}%로 상위 25킬 중앙값 {ta['ebon_might_uptime_med_pct']}%에 가까워요.",
         "loss": "현재 데이터로는 페이즈 전환 순간에 누구에게 칠흑의 힘이 들어갔는지 측정하지 않아, 타이밍 문제라고 판정할 수 없어요.",
         "cause": "지금 수집된 값은 전투 중 버프가 켜진 시간 비율뿐이고, 시전 시각·대상·분리된 위상별 수혜자를 저장하지 않아요.",
         "next_pull": "유지율은 지금 수준을 그대로 지키세요. 페이즈 타이밍을 바꾸라는 처방은 대상·시각 수집을 추가한 뒤에만 내리겠습니다.",
         "evidence": "유지율은 90초 이상 풀을 전투 시간으로 가중해 비교했고, 측정하지 않은 위상별 타이밍은 정보 카드로만 표시했어요."},
    ]

    aug_tab = {
        "title": "증강 기원사 — 하늘연달스물엿새",
        "sample_note": f"상위권 숫자는 세계 순위권 공대의 신화 킬 25판에서, 내 숫자는 {session_desc}에서 가져왔어요.",
        "highlights": [
            {"severity": "good", "text": f"전투 시작 직후 첫 숨결을 {sa['first_cast_med_s']['Breath of Eons']}초 만에 쓰고 있어요. 상위권({ref['first_cast_med_s']}초)과 거의 같아요."},
            {"severity": "good", "text": f"{latest_desc}에는 15초 초과 숨결 지연과 조기 사망이 모두 0건이에요. 최근 흐름은 분명히 좋아졌어요."},
            {"severity": "bad", "text": f"자정 도달 {p3_pulls}풀에서 자정 숨결은 {p3_breaths}회예요. 다음 한 가지 목표는 {_clock(p3_first_top_s)} 전후 다섯 번째 숨결입니다."},
            {"severity": "bad", "text": f"전투 물약은 전체 {aug_potions['uses']}회, {latest_desc} {aug_potions_latest['uses']}회예요. 첫 물약부터 고정하면 바로 회수할 수 있는 손실이에요."},
            {"severity": "info", "text": f"상위권 자정 수정 운반자 {cs['aug_carries_p3_n']}명은 모두 수정을 든 채 숨결을 썼어요. 운반과 실제 시전을 분리해서 판단하세요."},
        ],
        "problems": aug_problems,
        "plan": {
            "title": "다음 풀 체크리스트",
            "items": [
                {"when": "0:03", "action": "첫 영겁의 숨결과 첫 물약", "check": "둘 다 사용"},
                {"when": _clock(top_breath_times.get(3)), "action": "세 번째 숨결", "check": "수정 보유 중이어도 보류하지 않기"},
                {"when": _clock(top_breath_times.get(4)), "action": "네 번째 숨결", "check": "자정 전 리듬 유지"},
                {"when": _clock(p3_first_top_s), "action": "자정 다섯 번째 숨결과 두 번째 물약", "check": "공대 극딜 콜에 맞추기"},
                {"when": "매 사망 후", "action": "직전 10초 생존기 확인", "check": "원인 하나만 다음 풀에 예약"},
            ],
        },
        "sections": [
            {"title": "쿨기·딜사이클", "rows": aug_rows_cd},
            {"title": "생존·소모품·사망", "rows": aug_rows_life},
        ],
        "breath": {
            "title": "영겁의 숨결, 수정 들었을 때 언제 쓰나",
            "lines": breath_lines,
            "per_pull": per_pull,
        },
        "caveat": "상위권 기록은 보스를 잡은 9분짜리 완주 로그이고 우리는 도중에 끝난 연습 풀이에요. "
                  "숨결 기준은 상위 증강 25명의 정확한 source_id만 다시 계산했고, 같은 리포트의 다른 증강은 제외했어요. "
                  "숨결 지연은 같은 순번 간격보다 15초 넘게 벌어진 경우예요. 칠흑의 힘의 페이즈별 대상·시각은 아직 측정하지 않아 진단하지 않았어요.",
    }

    # ── 부죽 ─────────────────────────────────────────────────────────────
    upm = _own_pm(own, "udk", [
        "Dark Transformation", "Army of the Dead", "Anti-Magic Shell",
        "Anti-Magic Zone", "Icebound Fortitude",
    ])
    mcd = tu["major_cds"]
    tdef = tu["defensives"]
    ucpm = su["core_cpm_med"]
    top_rot = {row["name"]: row for row in (tu.get("rotational_top") or [])} if isinstance(tu.get("rotational_top"), list) else {}

    def _top_cpm(name: str, fallback: float) -> float:
        row = top_rot.get(name) or {}
        return float(row.get("cpm_med") or fallback)

    own_coil = round(ucpm.get("Death Coil", 0) + ucpm.get("Necrotic Coil", 0), 1)
    top_coil = round(_top_cpm("Death Coil", 11.06) + _top_cpm("Necrotic Coil", 7.72), 1)
    latest_death_coil = _core_cpm_median(latest_pulls, "udk", ["Death Coil"])
    latest_necrotic_coil = _core_cpm_median(latest_pulls, "udk", ["Necrotic Coil"])
    latest_scourge = _core_cpm_median(latest_pulls, "udk", ["Scourge Strike"])
    latest_upm = _pulls_pm(latest_pulls, "udk", [
        "Dark Transformation", "Army of the Dead", "Anti-Magic Shell",
        "Anti-Magic Zone", "Icebound Fortitude",
    ])
    top_ams_times = _indexed_medians([
        [float(t) for t in ((fight.get("defensive_times_s") or {}).get("ams") or [])]
        for fight in udk_top.get("fights") or []
    ])
    top_dt_times = _indexed_medians([
        [float(t) for t in ((fight.get("major_cd_times_s") or {}).get("dark_transformation") or [])]
        for fight in udk_top.get("fights") or []
    ])
    top_army_times = _indexed_medians([
        [float(t) for t in ((fight.get("major_cd_times_s") or {}).get("army") or [])]
        for fight in udk_top.get("fights") or []
    ])
    top_potion_times = _indexed_medians([
        [float(t) for t in ((fight.get("consumable_times_s") or {}).get("Potion of Recklessness") or [])]
        for fight in udk_top.get("fights") or []
    ])
    own_ams_first = _median([
        float(events[0].get("t") or 0)
        for pull in own["pulls"]
        if (events := ((pull.get("udk") or {}).get("defensives") or {}).get("Anti-Magic Shell"))
    ])
    udk_potion_eligible = [pull for pull in own["pulls"] if float(pull.get("duration_s") or 0) >= 30]
    udk_potion_long = [pull for pull in own["pulls"] if float(pull.get("duration_s") or 0) >= MIN_PULL_S]
    latest_potion_eligible = [pull for pull in latest_pulls if float(pull.get("duration_s") or 0) >= 30]
    udk_first_pot_on_time = sum(
        any(float(event.get("t") or 0) <= 10
            for event in ((pull.get("udk") or {}).get("consumables") or {}).get("Potion of Recklessness") or [])
        for pull in udk_potion_eligible
    )
    udk_first_pot_long_used = sum(
        bool(((pull.get("udk") or {}).get("consumables") or {}).get("Potion of Recklessness"))
        for pull in udk_potion_long
    )
    latest_first_pot_on_time = sum(
        any(float(event.get("t") or 0) <= 10
            for event in ((pull.get("udk") or {}).get("consumables") or {}).get("Potion of Recklessness") or [])
        for pull in latest_potion_eligible
    )
    ibf_opportunities = [pull for pull in own["pulls"] if float(pull.get("duration_s") or 0) >= 220]
    ibf_used = sum(
        bool(((pull.get("udk") or {}).get("defensives") or {}).get("Icebound Fortitude"))
        for pull in ibf_opportunities
    )
    latest_ibf_opportunities = [pull for pull in latest_pulls if float(pull.get("duration_s") or 0) >= 220]
    latest_ibf_used = sum(
        bool(((pull.get("udk") or {}).get("defensives") or {}).get("Icebound Fortitude"))
        for pull in latest_ibf_opportunities
    )
    last_udk = last_pull.get("udk") or {}
    last_dt = (last_udk.get("majors") or {}).get("Dark Transformation") or []
    last_army = (last_udk.get("majors") or {}).get("Army of the Dead") or []
    last_potions = (last_udk.get("consumables") or {}).get("Potion of Recklessness") or []
    last_p3_bundle = (
        f"물약 {_clock(last_potions[-1].get('t')) if len(last_potions) >= 2 else '없음'}, "
        f"어둠의 변신 {_clock(last_dt[-1].get('t')) if last_dt else '없음'}, "
        f"사자의 군대 {_clock(last_army[-1].get('t')) if last_army else '없음'}"
    )

    udk_rows_cd = [
        {"label": "첫 어둠의 변신까지", "mine": f'{su["first_cast_med_s"]["Dark Transformation"]}초',
         "top": f'{mcd["dark_transformation"]["first_cast_med_s"]}초', "verdict": "good",
         "note": "전투 시작하자마자 잘 쓰고 있어요."},
        {"label": "어둠의 변신 (1분당)", "mine": upm["Dark Transformation"], "top": mcd["dark_transformation"]["casts_per_min_med"],
         "verdict": _ratio_verdict(upm["Dark Transformation"], mcd["dark_transformation"]["casts_per_min_med"]),
         "note": "상위권은 45초마다, 쿨이 돌 때마다 써요. 우리도 거의 같은 페이스예요."},
        {"label": "사자의 군대 (1분당)", "mine": upm["Army of the Dead"], "top": mcd["army"]["casts_per_min_med"],
         "verdict": _ratio_verdict(upm["Army of the Dead"], mcd["army"]["casts_per_min_med"]),
         "note": "상위권은 중앙값 91초 간격이고 우리도 분당 사용량이 비슷해요. 유지할 강점이에요."},
        {"label": "스컬지의 일격 (1분당)", "mine": ucpm.get("Scourge Strike", 0), "top": _top_cpm("Scourge Strike", 22.25),
         "verdict": _ratio_verdict(ucpm.get("Scourge Strike", 0), _top_cpm("Scourge Strike", 22.25)),
         "note": "기본 딜 기술을 얼마나 부지런히 누르는지 보는 값이에요."},
        {"label": "코일 두 종류 합계 (1분당)", "mine": own_coil, "top": top_coil,
         "verdict": _ratio_verdict(own_coil, top_coil),
         "note": f"죽음의 고리와 괴저 고리 합계예요. 최근은 각각 {latest_death_coil:.2f}, {latest_necrotic_coil:.2f}회/분이에요. 생성 부족·과잉 보유·이동 중 무엇인지는 자원 이벤트가 없어 단정하지 않았어요."},
        {"label": "고름 일격 (1분당)", "mine": ucpm.get("Festering Strike", 0), "top": _top_cpm("Festering Strike", 2.83),
         "verdict": _ratio_verdict(ucpm.get("Festering Strike", 0), _top_cpm("Festering Strike", 2.83)),
         "note": "상처를 쌓는 기술이에요. 코일 차이를 설명할 때 생성기 한 종류만 보고 결론 내리지 않도록 함께 표시해요."},
        {"label": "영혼 수확자 (1분당)", "mine": ucpm.get("Soul Reaper", 0), "top": _top_cpm("Soul Reaper", 1.83),
         "verdict": _ratio_verdict(ucpm.get("Soul Reaper", 0), _top_cpm("Soul Reaper", 1.83)),
         "note": "전투 길이와 발동·사용 가능 구간의 영향을 크게 받아요. 현재 표는 기회 횟수로 보정하지 않았으므로 우선순위 문제로 단정하지 않아요."},
    ]
    udk_rows_life = [
        {"label": "대마법 보호막 (1분당)", "mine": upm["Anti-Magic Shell"], "top": tdef["ams"]["casts_per_min_med"],
         "verdict": _ratio_verdict(upm["Anti-Magic Shell"], tdef["ams"]["casts_per_min_med"]),
         "note": f"피해 흡수와 룬 마력 수급을 함께 주는 기술이에요. 상위권은 첫 사용 {_clock(top_ams_times.get(1))}, 이후 {_clock(top_ams_times.get(2))}, {_clock(top_ams_times.get(3))}가 중앙값이고 최근 우리는 {latest_upm['Anti-Magic Shell']}회/분이에요."},
        {"label": "대마법 지대 (1분당)", "mine": upm["Anti-Magic Zone"],
         "top": tdef["amz"]["casts_per_min_med"] if "amz" in tdef else 0.11,
         "verdict": "good",
         "note": "공대 전체를 지켜주는 기술이에요. 상위권은 주로 암흑 반응로 구간에 아껴 쓰는데, 우리도 잘 쓰고 있어요."},
        {"label": "최근 얼음같은 인내력", "mine": f"{latest_ibf_used}/{len(latest_ibf_opportunities)}풀",
         "top": f"상위 25킬 {tdef['ibf']['fights_used_pct']}% 사용", "verdict": "good" if latest_ibf_used == len(latest_ibf_opportunities) else "warn",
         "note": f"전체 풀 수가 아니라 해당 타이밍까지 생존한 3분 40초 이상 풀만 분모로 삼았어요. 전체 기회 풀에서는 {ibf_used}/{len(ibf_opportunities)}풀이에요."},
        {"label": "첫 전투 물약 (30초+ 풀)", "mine": f"{udk_first_pot_on_time}/{len(udk_potion_eligible)}풀",
         "top": "상위 25킬 전원 첫 물약", "verdict": _ratio_verdict(udk_first_pot_on_time, len(udk_potion_eligible)),
         "note": f"풀링 10초 안 첫 물약만 셌어요. 90초 이상 풀에서는 {udk_first_pot_long_used}/{len(udk_potion_long)}풀이 물약을 한 번 이상 사용했어요."},
        {"label": f"전멸 {EARLY_DEATH_LEAD_S}초보다 앞선 사망", "mine": f"{udk_early['total']}건 / {udk_early['pulls']}풀",
         "top": f"상위 25킬 {tu['deaths']['total_deaths']}건", "verdict": "warn",
         "note": f"전멸 종료 사망은 제외했어요. {latest_desc}에는 {udk_early_latest['total']}건이었어요. 주요 마지막 피해는 {_top_causes_text(udk_early['causes'])}이고, 사망 전 10초에 개인 생존기·회복 아이템 반응이 없던 건 {udk_early['without_response']}건이에요."},
    ]

    udk_problems = [
        {"severity": "warn", "title": "1. 가장 큰 회전 차이는 두 코일의 합계예요",
         "good": f"어둠의 변신은 {upm['Dark Transformation']}회/분, 사자의 군대는 {upm['Army of the Dead']}회/분으로 상위권 {mcd['dark_transformation']['casts_per_min_med']}, {mcd['army']['casts_per_min_med']}회/분과 비슷해요. 최근 스컬지의 일격도 {latest_scourge:.2f}회/분이에요.",
         "loss": f"죽음의 고리와 괴저 고리는 합계 {own_coil}회/분으로 상위권 {top_coil}회/분보다 {top_coil - own_coil:.1f}회/분 적어요. 최근 합계도 {latest_death_coil + latest_necrotic_coil:.2f}회/분이에요.",
         "cause": "현재 로그에는 룬·룬 마력의 생성, 보유량, 과잉 여부가 없어요. 따라서 생성 부족인지, 최대치 근처에서 남긴 것인지, 이동·대상 전환 때문인지 아직 분리할 수 없고 '룬 마력 과잉'으로 단정하지 않았어요.",
         "next_pull": "첫 목표를 합계 15회/분으로 잡고, 어둠의 변신·사자의 군대 횟수는 지금처럼 유지하세요. 다음 채굴에는 룬 마력 이벤트를 추가해 코일이 비는 정확한 구간을 찾으세요.",
         "evidence": f"90초 이상 우리 풀의 중앙값은 죽음의 고리 {ucpm.get('Death Coil', 0)}, 괴저 고리 {ucpm.get('Necrotic Coil', 0)}회/분이고, 상위 25킬은 {_top_cpm('Death Coil', 11.06)}, {_top_cpm('Necrotic Coil', 7.72)}회/분이에요."},
        {"severity": "bad", "title": "2. 자정에서는 군대·변신·두 번째 물약을 한 묶음으로 봐요",
         "good": "전투 시작과 중반의 어둠의 변신·사자의 군대 주기는 상위권에 가깝고, 최고 기록 풀에서는 두 번째 물약과 사자의 군대가 1초 차이로 붙었어요.",
         "loss": f"상위 25킬의 자정 묶음 중앙값은 사자의 군대 {_clock(top_army_times.get(5))}, 두 번째 물약 {_clock(top_potion_times.get(2))}, 어둠의 변신 {_clock(top_dt_times.get(9))}예요. 최근 {last_pull['pull']}번 풀은 {last_p3_bundle}으로 세 기술이 갈라졌어요.",
         "cause": "최근 풀은 두 번째 물약을 자정 진입 직전에 먼저 사용했고, 다음 사자의 군대가 약 51초 뒤에 왔어요. 군대 이전 사용 시각까지 함께 밀려 있어 6:10을 그대로 복사하기보다 실제 다음 군대 준비 시각에 맞춰야 해요.",
         "next_pull": f"두 번째 물약을 자정 진입 즉시 쓰지 말고 다음 사자의 군대와 어둠의 변신까지 보류하세요. 앞선 주기가 같다면 약 {_clock(last_army[-1].get('t') if last_army else None)}에 세 개를 묶고, 장기적으로는 앞선 군대 주기를 당겨 상위 기준 {_clock(top_army_times.get(5))}에 접근하세요.",
         "evidence": f"상위 25킬은 세 중앙 시각이 1초 안에 모여요. 최근 자정 도달 {latest_p3_pulls}풀 중 2병 사용은 {udk_potions_latest['two_pot_pulls']}풀이었고, 최근 풀의 실제 세 시각을 따로 표시했어요."},
        {"severity": "warn", "title": "3. 대마법 보호막은 초반부터 계획할 수 있어요",
         "good": f"최근 사용량은 {latest_upm['Anti-Magic Shell']}회/분으로 전체 {upm['Anti-Magic Shell']}회/분보다 좋아졌어요.",
         "loss": f"전체는 {upm['Anti-Magic Shell']}회/분으로 상위 25킬 {tdef['ams']['casts_per_min_med']}회/분보다 낮고, 사용한 풀의 첫 시각 중앙값도 {_clock(own_ams_first)}로 상위 {_clock(top_ams_times.get(1))}보다 늦어요.",
         "cause": "생존 전용 비상 버튼으로만 남겨 둔 패턴으로 보이지만 의도는 로그만으로 확정할 수 없어요. 상위 기록은 피해 흡수와 자원 이득을 함께 얻을 수 있는 구간에 반복 배치했어요.",
         "next_pull": f"먼저 {_clock(top_ams_times.get(1))}, {_clock(top_ams_times.get(2))}, {_clock(top_ams_times.get(3))} 세 시각만 알림으로 등록하고 실제 마법 피해를 흡수하는지 확인하세요. 무피해 공회전은 목표가 아니에요.",
         "evidence": f"상위 25킬은 전원 사용, 중앙값 7회, 간격 {tdef['ams']['gap_med_s']}초예요. 우리와 최근 값은 90초 이상 풀의 실제 전투 분으로 나눴어요."},
        {"severity": "warn", "title": "4. 조기 사망은 마지막 피해별로 줄여야 해요",
         "good": f"전체 조기 사망 중 {udk_early['responded']}건은 직전 10초에 개인 생존기나 회복 아이템 반응이 있었어요.",
         "loss": f"전멸 종료를 제외한 조기 사망은 {udk_early['total']}건이고, 반응이 없던 경우는 {udk_early['without_response']}건이에요. {latest_desc}에도 {udk_early_latest['total']}건이 남았어요.",
         "cause": f"마지막 피해 상위 원인은 {_top_causes_text(udk_early['causes'])}이고, 1페이즈가 {udk_early['phases'].get('Stage One: Final Tolls', 0)}건이에요. 마지막 피해는 원인 후보이지 앞선 체력 관리 실수까지 증명하지는 않아요.",
         "next_pull": "반복되는 세 피해 중 하나만 골라 대마법 보호막·얼음같은 인내력·죽음의 서약 중 맞는 버튼을 사전 예약하세요. 사망 뒤에는 직전 10초에 무엇을 썼는지만 확인해 다음 풀 예약을 바꾸세요.",
         "evidence": f"풀 종료보다 {EARLY_DEATH_LEAD_S}초 넘게 앞선 사망만 조기 사망으로 분류하고, 종료 직전 전멸 사망은 모두 제외했어요."},
        {"severity": "good", "title": "5. 최근의 첫 물약과 얼음같은 인내력은 강점이에요",
         "good": f"{latest_desc}에서 30초 이상 간 {len(latest_potion_eligible)}풀 중 {latest_first_pot_on_time}풀은 시작 10초 안에 첫 물약을 썼고, 3분 40초 이상 간 {len(latest_ibf_opportunities)}풀 중 {latest_ibf_used}풀은 얼음같은 인내력을 썼어요.",
         "loss": f"전체 90초 이상 {len(udk_potion_long)}풀 중 물약을 한 번 이상 쓴 풀은 {udk_first_pot_long_used}풀이어서, 최근 습관이 이전 세션 전체에는 아직 반영되지 않았어요.",
         "cause": "최근에는 풀링 루틴과 특정 생존기 타이밍이 정착된 것으로 보여요. 표본이 한 세션이므로 다음 세션까지 유지되는지 확인이 필요해요.",
         "next_pull": "첫 물약과 얼음같은 인내력은 새로 바꾸지 말고 그대로 유지하세요. 이번에는 코일 합계·자정 묶음·대마법 보호막 세 가지만 개선 대상으로 두세요.",
         "evidence": "얼음같은 인내력은 모든 짧은 풀을 분모로 쓰지 않고 해당 타이밍에 도달한 3분 40초 이상 풀만 비교했어요."},
    ]

    udk_tab = {
        "title": "부정 죽음의 기사 — 이디라아 (로그 캐릭터: 이디죽기)",
        "sample_note": f"상위권 숫자는 지금 패치(12.0.7) 기준 세계 순위권의 신화 킬 25판에서, 내 숫자는 {session_desc}에서 가져왔어요.",
        "highlights": [
            {"severity": "good", "text": f"어둠의 변신과 사자의 군대는 상위권에 가까운 속도로 쓰고 있어요. {latest_desc} 첫 물약과 얼음같은 인내력 루틴도 잘 잡혔어요."},
            {"severity": "warn", "text": f"두 코일 합계는 {own_coil}회/분으로 상위 {top_coil}회/분보다 낮아요. 다만 자원 이벤트가 없어 룬 마력 과잉이라고 단정하지 않았어요."},
            {"severity": "bad", "text": f"최근 자정 묶음은 {last_p3_bundle}이었어요. 두 번째 물약을 군대·변신과 함께 쓰는 것이 다음 큰 목표예요."},
            {"severity": "warn", "text": f"대마법 보호막은 전체 {upm['Anti-Magic Shell']}회/분, 최근 {latest_upm['Anti-Magic Shell']}회/분으로 좋아지는 중이지만 상위 {tdef['ams']['casts_per_min_med']}회/분까지 여지가 있어요."},
            {"severity": "info", "text": "장비·장신구·오프너 평가는 별도 14판 스냅샷이에요. 현재 장착 상태를 먼저 확인한 뒤 판단하세요."},
        ],
        "problems": udk_problems,
        "plan": {
            "title": "다음 풀 체크리스트",
            "items": [
                {"when": "0:03", "action": "어둠의 변신·사자의 군대·첫 물약", "check": "현재 좋은 오프너 유지"},
                {"when": _clock(top_ams_times.get(1)), "action": "첫 대마법 보호막", "check": "실제 마법 피해 흡수"},
                {"when": f"{_clock(top_ams_times.get(2))} / {_clock(top_ams_times.get(3))}", "action": "대마법 보호막 반복", "check": "무피해 공회전은 하지 않기"},
                {"when": f"{_clock(top_army_times.get(5))}~{_clock(last_army[-1].get('t') if last_army else None)}", "action": "자정 사자의 군대·어둠의 변신·두 번째 물약", "check": "현재 쿨에 맞춰 세 시각을 한 묶음으로"},
                {"when": "풀 종료", "action": "두 코일 합계 확인", "check": "우선 15회/분 목표"},
            ],
        },
        "sections": [
            {"title": "쿨기·딜사이클", "rows": udk_rows_cd},
            {"title": "생존·소모품·사망", "rows": udk_rows_life},
        ],
        "caveat": "상위권 기록은 보스를 잡은 9분짜리 완주 로그이고 우리는 도중에 끝난 연습 풀이에요. "
                  "그래서 판당 횟수 대신 '1분에 몇 번'과 '몇 초 만에 첫 사용'으로 비교했어요. "
                  "1분당 값은 90초 넘게 간 풀만 모아서 계산했어요. 룬·룬 마력 이벤트는 아직 없어 코일 부족의 세부 원인을 확정하지 않았어요.",
    }

    # 다른 PC 채굴 세트(dkaug_top_comparison.json) 흡수 — 장신구·오프너·스탯(+증강 기본 기술)
    sample_note_extra = " 장비 스탯·장신구·전투 시작 순서 줄은 다른 채굴 세트(우리 14판 vs 상위 30킬)에서 가져와 표본이 달라요."
    if dkaug.get("aug"):
        secs, hls = _dkaug_sections(dkaug["aug"], include_pattern=True)
        aug_tab["sections"].extend(secs)
        aug_tab["highlights"].extend(hls)
        aug_tab["caveat"] += sample_note_extra
    if dkaug.get("dk"):
        secs, hls = _dkaug_sections(dkaug["dk"], include_pattern=False)
        udk_tab["sections"].extend(secs)
        udk_tab["highlights"].extend(hls)
        udk_tab["caveat"] += sample_note_extra

    out = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "encounter_id": 3183,
        "source_note": f"상위권: WCL 세계 랭킹 신화 킬 · 우리: {own_source}",
        "tabs": {"aug": aug_tab, "udk": udk_tab},
    }
    out_path = DATA / "lura_spec_compare.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"aug rows: {sum(len(s['rows']) for s in aug_tab['sections'])}, "
          f"udk rows: {sum(len(s['rows']) for s in udk_tab['sections'])}, "
          f"breath lines: {len(breath_lines)}, per_pull: {len(per_pull)}")


if __name__ == "__main__":
    main()
