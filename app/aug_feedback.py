"""증강 기원사(Augmentation Evoker) 피드백 — casts/buffs/gear → KPI + per-cast 위반.

v1 (2026-06-13): 칠흑의 힘 유지율·예지 빈도·영겁 순서·필러비율·장신구.
조합 제외. 측정 불가(칠흑 크리값·버프 대상·위상분할)는 educational note.
검증 ID: 실측 NTydRwMQPC2F7kqp:1:1 핀 (memory/project_aug_feedback.md).
"""
from __future__ import annotations

# ── 검증된 cast/buff ability ID ──────────────────────────────────────────
EBON_MIGHT = 395152                 # 칠흑의 힘 (cast & buff 동일 id)
PRESCIENCE_CAST = {409311}          # 예지 (cast)
PRESCIENCE_BUFF = {410089}          # 예지 (아군 적용 버프)
BREATH_OF_EONS = {442204, 403631}   # 영겁의 숨결
FIRE_BREATH = {357208, 382266}      # 불의 숨결
UPHEAVAL = {396286}                 # 격변
ERUPTION = {395160, 438588}         # 분출
LIVING_FLAME = {361469, 361509}     # 살아있는 불꽃
AZURE_STRIKE = {362969}             # 하늘빛 일격
TIP_THE_SCALES = {370553}           # 전세역전
TIME_SKIP = {404977}                # 시간 도약
HOVER = {358267, 374227}            # 부양 (이동 중 시전)

TRINKET_SLOTS = (12, 13)

# 영겁의 숨결은 칠흑의 힘 직후(N초내)에 써야 복제 버프가 칠흑과 함께 연장됨 (영상 근거)
BREATH_AFTER_EBON_WINDOW_S = 6.0

VID_ROTATION = "https://www.youtube.com/watch?v=Nyz9N14teo4"


def _casts_of(casts, ids):
    """type=='cast' 활성화만 (begincast 제외). [(ts_ms, sid)] 정렬."""
    out = [(c[0], int(c[1])) for c in casts
           if len(c) >= 3 and c[2] == "cast" and int(c[1] or 0) in ids]
    out.sort()
    return out


def _buff_uptime_ms(buffs, ids, start_ms, end_ms):
    """주어진 buff id 집합의 활성 구간 union 길이(ms). prepull 활성/끝까지 미제거 clamp."""
    pts = []
    for b in buffs:
        if len(b) < 3 or int(b[1] or 0) not in ids:
            continue
        typ = b[2]
        if typ == "applybuff":
            pts.append((b[0], +1))
        elif typ == "removebuff":
            pts.append((b[0], -1))
    if not pts:
        return 0
    pts.sort()
    total = 0
    depth = 0
    cur_start = None
    if pts[0][1] < 0:           # 첫 이벤트가 제거 → 전투 시작부터 켜져있던 것
        depth = 1
        cur_start = start_ms
    for t, d in pts:
        prev = depth
        depth = max(0, depth + d)
        if prev == 0 and depth > 0:
            cur_start = t
        elif prev > 0 and depth == 0 and cur_start is not None:
            total += max(0, min(t, end_ms) - max(cur_start, start_ms))
            cur_start = None
    if depth > 0 and cur_start is not None:
        total += max(0, end_ms - max(cur_start, start_ms))
    return total


def compute(casts, buffs, gear, start_ms, end_ms):
    """단일 캐릭 fight 데이터 → KPI + 위반 + 교육노트. start/end = 리포트 기준 ms."""
    span = max(end_ms - start_ms, 1)
    dur_s = span / 1000.0

    ebon_up_ms = _buff_uptime_ms(buffs, {EBON_MIGHT}, start_ms, end_ms)
    ebon_casts = _casts_of(casts, {EBON_MIGHT})
    hover_up_ms = _buff_uptime_ms(buffs, HOVER, start_ms, end_ms)
    hover_casts = _casts_of(casts, HOVER)

    presc_casts = _casts_of(casts, PRESCIENCE_CAST)

    # 영겁의 숨결 순서: 각 Breath cast 직전 N초내 Ebon cast 있어야 OK
    ebon_ts = [t for t, _ in ebon_casts]
    breath_casts = _casts_of(casts, BREATH_OF_EONS)
    violations = []
    breath_after_ebon = 0
    win = BREATH_AFTER_EBON_WINDOW_S * 1000
    for t, sid in breath_casts:
        if any(0 <= (t - et) <= win for et in ebon_ts):
            breath_after_ebon += 1
        else:
            violations.append({
                "ts_rel": round((t - start_ms) / 1000.0, 1),
                "ts_ms": int(t),
                "kind": "red", "sid": sid, "label": "영겁의 숨결",
                "why": "칠흑의 힘 직후에 쓰지 않음 — 복제 버프가 칠흑과 함께 연장되지 못해 손해. 칠흑→영겁 순서.",
                "ref": VID_ROTATION,
            })

    # 강화주문(불숨·격변)은 empowerend 로 찍힘 → 총 시전수에 포함
    all_cast = [int(c[1]) for c in casts
                if len(c) >= 3 and c[2] in ("cast", "empowerend") and int(c[1] or 0)]
    filler = sum(1 for sid in all_cast if sid in (LIVING_FLAME | AZURE_STRIKE))

    trinkets = [{"slot": g.get("slot"), "id": g.get("id")}
                for g in (gear or []) if isinstance(g, dict) and g.get("slot") in TRINKET_SLOTS]

    notes = [
        {"title": "칠흑의 힘 크리값 보호",
         "body": "칠흑의 힘이 치명타로 적용되면 능력치 버프가 훨씬 큼. 비크리면 시간 도약으로 리롤, "
                 "크리면 덮어쓰지 말고 유지. (로그에 버프 수치가 없어 자동판정 불가 — 직접 확인)"},
        {"title": "버프 대상 = 최고 딜러",
         "body": "예지·칠흑은 그 전투 최고 딜러에게 갈수록 효율 최대. (남의 딜 데이터 없어 자동판정 불가)"},
        {"title": "위상 분할 악용",
         "body": "라이드가 갈리는 보스(예: 카이메루스 1조/2조)는 내 조 인원이 적을 때 칠흑을 재시전해 "
                 "소수에 집중하면 1인당 버프가 폭증. (페이즈 데이터 없어 자동판정 불가)"},
    ]

    return {
        "is_aug": bool(ebon_casts or presc_casts or breath_casts),
        "duration_s": round(dur_s, 1),
        "kpis": {
            "ebon_uptime_pct": round(100.0 * ebon_up_ms / span, 1),
            "ebon_casts": len(ebon_casts),
            "prescience_casts": len(presc_casts),
            "prescience_per_min": round(len(presc_casts) / (dur_s / 60.0), 1),
            "breath_casts": len(breath_casts),
            "breath_after_ebon": breath_after_ebon,
            "filler_ratio": round(filler / len(all_cast), 2) if all_cast else 0.0,
            "total_casts": len(all_cast),
            "hover_casts": len(hover_casts),
            "hover_uptime_pct": round(100.0 * hover_up_ms / span, 1),
        },
        "violations": violations,
        "trinkets": trinkets,
        "notes": notes,
    }
