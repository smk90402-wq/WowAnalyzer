"""르우라 스펙 비교 합성 — 채굴 3종 JSON → data/lura_spec_compare.json.

입력 (먼저 실행돼 있어야 함):
  tmp_mine_lura_top_aug.py  → data/lura_top_aug_mining.json   (상위 증강 25킬)
  tmp_mine_lura_top_udk.py  → data/lura_top_udk_mining.json   (상위 부죽 25킬)
  tmp_mine_lura_own_pair.py → data/lura_own_pair_mining.json  (우리 07-19 27풀)
  tmp_mine_lura_own_em.py   → 위 own JSON 에 칠흑의 힘 유지율 병합

출력은 리플레이 분석 패널의 증강/죽기 탭(main.js _luraCompareCard)이 그대로 렌더.
문구 규칙(사용자 확정): 완전한 문장으로 — 무엇이 몇 번 있었고, 그게 무슨 뜻이고,
뭘 하면 되는지 순서. 대시 이어붙인 전보체·"N회/M시전" 분수 표기 금지.
상위권은 킬 로그(9분대 완주), 우리는 전멸 풀 — 판당 횟수 대신 분당·간격·첫 시전 비교.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data"
KST = timezone(timedelta(hours=9))
MIN_PULL_S = 90   # 분당 지표 계산에 쓰는 최소 풀 길이 (채굴 쪽 core_cpm 기준과 동일)


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _casts(value) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return int(value.get("count") or 0)
    return int(value or 0)


def _own_pm(own: dict, player: str, names: list[str]) -> dict[str, float]:
    """>=90s 풀들의 (총 시전 수 / 총 전투 분)."""
    total_min = 0.0
    counts = {n: 0 for n in names}
    for pull in own["pulls"]:
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


def _ratio_verdict(mine: float, top: float, good=0.9, warn=0.7) -> str:
    if not top:
        return "info"
    r = mine / top
    return "good" if r >= good else ("warn" if r >= warn else "bad")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    aug_top = _load("lura_top_aug_mining.json")
    udk_top = _load("lura_top_udk_mining.json")
    own = _load("lura_own_pair_mining.json")

    ta = aug_top["aggregates"]
    bp3 = aug_top["breath_vs_p3"]
    cs = aug_top["crystal_summary"]
    tu = udk_top["aggregates"]
    sa = own["session_aggregates"]["aug"]
    su = own["session_aggregates"]["udk"]
    carry = own["session_aggregates"]["aug_crystal_carry"]
    ref = own["breath_cd_reference_top_logs"]
    pulls_n = own["report"]["pulls"]
    best = own["best_pull"]

    # ── 증강: 분당 지표 (우리 로그, >=90s 풀) ────────────────────────────
    apm = _own_pm(own, "aug", [
        "Breath of Eons", "Fire Breath", "Upheaval", "Prescience", "Time Skip",
        "Obsidian Scales",
    ])
    aug_potion_uses = sum((sa.get("consumable_uses_total") or {}).get(k, 0)
                          for k in ("Potion of Recklessness", "Light's Potential"))
    aug_death_per_pull = round(sa["deaths_total"] / pulls_n, 2)
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
        {"label": "숨결이 늦어진 횟수", "mine": f'65번 중 {carry["breath_delayed_total"]}번',
         "top": "0번이 목표",
         "verdict": "warn" if carry["breath_delayed_total"] else "good",
         "note": "상위권 리듬보다 15초 넘게 늦게 쓴 경우를 셌어요. 늦은 7번이 모두 수정을 옮기던 중에 나왔어요."},
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
         "note": "상위권 25명 전원이 이 특성을 써요. 전투 시작 10초쯤에 한 번, 2분 30초쯤에 또 한 번이 표준이에요."},
        {"label": "칠흑의 힘 켜져 있던 비율",
         "mine": f'{em_own}%' if em_own else "잰 값 없음",
         "top": f'{ta["ebon_might_uptime_med_pct"]}%',
         "verdict": _ratio_verdict(float(em_own or 0), ta["ebon_might_uptime_med_pct"], good=0.95, warn=0.85),
         "note": "전투 시간 중에 칠흑의 힘 버프가 켜져 있던 비율이에요. 높을수록 좋아요. 90초 넘게 간 풀만 모아서 상위권과 같은 방법으로 쟀어요."},
    ]
    aug_rows_life = [
        {"label": "전투 물약", "mine": f'{pulls_n}풀 중 {aug_potion_uses}번',
         "top": "매 판 2병 (전원)", "verdict": "bad",
         "note": "상위권은 '빛의 잠재력' 물약을 전투 시작 직후에 1병, 자정 페이즈 무렵에 2병째를 마셔요. 지금 바로 고칠 수 있는 가장 쉬운 부분이에요."},
        {"label": "흑요석 비늘 (1분당)", "mine": apm["Obsidian Scales"], "top": top_scales_pm,
         "verdict": _ratio_verdict(apm["Obsidian Scales"], top_scales_pm),
         "note": "받는 피해를 줄여주는 방어 기술이에요. 상위권은 보스 잡는 동안 4번씩 써요."},
        {"label": "죽은 횟수 (풀마다)", "mine": aug_death_per_pull,
         "top": f'{round(ta["deaths_total"] / ta["n_fights"], 2)} (25킬에 3번)',
         "verdict": "bad" if aug_death_per_pull >= 0.5 else "warn",
         "note": "주로 어둠샘(7번), 불협화음(4번), 광휘(4번)에 죽었어요. 연습 중이라 죽음이 많은 건 자연스럽지만, 덜 죽을수록 한 판을 더 길게 연습할 수 있어요."},
    ]

    p3_carriers = cs.get("p3_carrier_details") or []
    offsets = sorted(
        off for c in p3_carriers for r in c.get("relation") or []
        for off in r.get("breath_during_offsets") or []
    )
    breath_lines = [
        f"상위권 25번의 킬 중 {cs['aug_carries_p3_n']}명의 증강이 자정 페이즈에서 수정을 들었어요. "
        f"{cs['aug_carries_p3_n']}명 모두 수정을 든 채로 영겁의 숨결을 제자리에서 그냥 썼어요"
        f"(수정을 들고 나서 {offsets[0]:.0f}초에서 {offsets[-1]:.0f}초 사이). "
        "수정을 들었다고 숨결을 아낄 필요가 없다는 뜻이에요.",
        f"상위권의 공통 리듬은 이래요. 자정에 들어가기 1분쯤 전(약 4분 34초)에 한 번 쓰고, "
        f"자정에 들어가고 30초쯤 지나서(약 6분) 다음 숨결을 써요. 25명 전원이 자정 진입 후 1분 안에 썼어요.",
        "왜 이 타이밍이냐면: 자정에 들어가고 12초쯤에 르우라가 둘로 갈라져서, 둘 다 때릴 수 있는 "
        "구간이 열려요(상위권 킬 5판 전부 동일). 상위권은 여기에 두 번째 블러드(진입 38초쯤)와 "
        "물약을 맞추고, 숨결을 진입 30초쯤에 써서 숨결의 폭발 피해가 그 몰아치기에 겹치게 해요. "
        "보스가 약해지는 디버프가 따로 있는 건 아니에요.",
        "쿨 계산도 중요해요. 숨결 쿨은 2분 고정이 아니라, 시간 건너뛰기 덕분에 실제로는 "
        "74초 → 80초 → 118초 → 88초 간격으로 돌아와요. 이 리듬대로만 쓰면 자정에 들어갈 때 "
        "숨결이 자연스럽게 준비돼 있어요.",
        f"고칠 곳은 사실상 한 자리예요. 늦어진 숨결 7번 중 6번이 같은 자리였어요. "
        f"1페이즈가 끝나갈 무렵(2분 58초에서 3분 10초 사이), 수정을 오래 들고 있는 동안 "
        f"세 번째 숨결이 17~25초씩 늦었어요. 제일 멀리 갔던 판({best['pull']}번째 풀, "
        f"보스 체력을 {best['boss_remaining_pct']:.0f}%까지 깎았던 판)에서는 한 번도 안 늦었으니, "
        "그 판에서 하던 대로 하면 돼요.",
        "정리하면: 수정을 들고 있어도 숨결은 제때, 제자리에서 쓰세요. 정면만 짧게 잡으면 돼요. "
        "자정에서는 들어가고 30초쯤을 기준으로 잡으면 돼요.",
    ]
    per_pull = []
    for d in (carry.get("delayed_casts_detail") or []):
        where = "1페이즈 후반, 세 번째 숨결" if d["t"] < 200 else "암흑 반응로 구간"
        when = "수정을 옮기던 중" if d.get("during_carry") else "수정을 옮긴 직후"
        per_pull.append({
            "pull": d["pull"], "t": d["t"],
            "context": f"{when} · {where}",
            "eval": f'{d["delta_vs_top_s"]:.0f}초 늦음', "verdict": "warn",
        })
    per_pull.append({
        "pull": best["pull"], "t": 0,
        "context": "최고 기록 풀은 숨결이 한 번도 안 늦었어요 (75초 → 91초 → 116초 간격)",
        "eval": "이 리듬이 정답", "verdict": "good",
    })

    aug_tab = {
        "title": "증강 기원사 — 하늘연달스물엿새",
        "sample_note": "상위권 숫자는 세계 순위권 공대의 신화 킬 25판에서, 내 숫자는 7월 19일 우리 공대의 신화 연습 27풀에서 가져왔어요.",
        "highlights": [
            {"severity": "info", "text": "자정 페이즈에서 수정을 든 상위권 증강 6명이 전부 제자리에서 영겁의 숨결을 그대로 썼어요. 수정을 들었다고 숨결을 아낄 필요가 없다는 뜻이니, 들고 있어도 그냥 쓰면 돼요."},
            {"severity": "bad", "text": f"전투 물약을 {pulls_n}풀 중 {aug_potion_uses}번만 마셨어요. 상위권은 한 판에 2병씩 꼭 마셔요. 가장 쉽게 고칠 수 있는 부분이에요."},
            {"severity": "warn", "text": "숨결이 늦어진 7번이 모두 수정을 옮기던 중이었어요. 특히 1페이즈가 끝나갈 무렵(3분 전후)의 세 번째 숨결이 반복해서 늦어요."},
            {"severity": "good", "text": f"전투 시작 직후 첫 숨결을 {sa['first_cast_med_s']['Breath of Eons']}초 만에 쓰고 있어요. 상위권({ref['first_cast_med_s']}초)과 거의 같아요."},
        ],
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
                  "그래서 판당 횟수 대신 '1분에 몇 번'과 '몇 초 만에 첫 사용'으로 비교했어요. "
                  "숨결이 '늦었다'는 판정은 상위권의 같은 순번 간격보다 15초 넘게 벌어진 경우예요.",
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
    udk_death_per_pull = round(su["deaths_total"] / pulls_n, 2)
    udk_potion = (su.get("consumable_uses_total") or {}).get("Potion of Recklessness", 0)

    udk_rows_cd = [
        {"label": "첫 어둠의 변신까지", "mine": f'{su["first_cast_med_s"]["Dark Transformation"]}초',
         "top": f'{mcd["dark_transformation"]["first_cast_med_s"]}초', "verdict": "good",
         "note": "전투 시작하자마자 잘 쓰고 있어요."},
        {"label": "어둠의 변신 (1분당)", "mine": upm["Dark Transformation"], "top": mcd["dark_transformation"]["casts_per_min_med"],
         "verdict": _ratio_verdict(upm["Dark Transformation"], mcd["dark_transformation"]["casts_per_min_med"]),
         "note": "상위권은 45초마다, 쿨이 돌 때마다 써요. 우리도 거의 같은 페이스예요."},
        {"label": "죽음의 군대 (1분당)", "mine": upm["Army of the Dead"], "top": mcd["army"]["casts_per_min_med"],
         "verdict": _ratio_verdict(upm["Army of the Dead"], mcd["army"]["casts_per_min_med"]),
         "note": "상위권은 91초 간격으로 쓰고 우리는 95초 간격이라 좋아요. '돌격!'은 군대를 쓰면 자동으로 따라 나가니 따로 신경 안 써도 돼요."},
        {"label": "스컬지의 일격 (1분당)", "mine": ucpm.get("Scourge Strike", 0), "top": _top_cpm("Scourge Strike", 22.25),
         "verdict": _ratio_verdict(ucpm.get("Scourge Strike", 0), _top_cpm("Scourge Strike", 22.25)),
         "note": "기본 딜 기술을 얼마나 부지런히 누르는지 보는 값이에요."},
        {"label": "코일 두 종류 합계 (1분당)", "mine": own_coil, "top": top_coil,
         "verdict": _ratio_verdict(own_coil, top_coil),
         "note": "죽음의 고리와 괴사 코일을 합친 값이에요. 룬 마력을 쓰는 기술이라, 이게 낮으면 룬 마력이 남아서 버려지고 있다는 뜻이에요."},
        {"label": "고름 일격 (1분당)", "mine": ucpm.get("Festering Strike", 0), "top": _top_cpm("Festering Strike", 2.83),
         "verdict": _ratio_verdict(ucpm.get("Festering Strike", 0), _top_cpm("Festering Strike", 2.83)),
         "note": "상처를 쌓는 기술이에요. 상위권과 거의 같아요."},
        {"label": "영혼 수확자 (1분당)", "mine": ucpm.get("Soul Reaper", 0), "top": _top_cpm("Soul Reaper", 1.83),
         "verdict": _ratio_verdict(ucpm.get("Soul Reaper", 0), _top_cpm("Soul Reaper", 1.83)),
         "note": "보스 체력이 35% 아래일 때 계속 눌러야 하는 마무리 기술이에요. 후반 페이즈에서 잊지 않는 게 포인트예요."},
    ]
    udk_rows_life = [
        {"label": "대마법 보호막 (1분당)", "mine": upm["Anti-Magic Shell"], "top": tdef["ams"]["casts_per_min_med"],
         "verdict": _ratio_verdict(upm["Anti-Magic Shell"], tdef["ams"]["casts_per_min_med"]),
         "note": "상위권은 이걸 피해 막기용이 아니라 룬 마력 충전용으로 62초마다, 한 판에 7번씩 써요. 지금 딜 차이가 가장 크게 나는 부분이에요."},
        {"label": "대마법 지대 (1분당)", "mine": upm["Anti-Magic Zone"],
         "top": tdef["amz"]["casts_per_min_med"] if "amz" in tdef else 0.11,
         "verdict": "good",
         "note": "공대 전체를 지켜주는 기술이에요. 상위권은 주로 암흑 반응로 구간에 아껴 쓰는데, 우리도 잘 쓰고 있어요."},
        {"label": "얼음같은 인내력", "mine": f'{pulls_n}풀 중 {(su.get("defensive_uses_total") or {}).get("Icebound Fortitude", 0)}번',
         "top": "거의 매 판 1번", "verdict": "warn",
         "note": "큰 피해가 예고된 구간에서 한 번씩 쓰는 습관을 들이면 좋아요."},
        {"label": "전투 물약", "mine": f'{pulls_n}풀 중 {udk_potion}번', "top": "매 판 2병 (전원)",
         "verdict": "good",
         "note": "1병째는 잘 챙기고 있어요. 2병째는 자정 페이즈까지 가야 마실 수 있어서 지금은 이 정도면 충분해요."},
        {"label": "죽은 횟수 (풀마다)", "mine": udk_death_per_pull,
         "top": f'{round(tu["deaths"]["total"] / tu["n_fights"], 2) if isinstance(tu.get("deaths"), dict) and "total" in tu["deaths"] else 0.08} (25킬에 2번)',
         "verdict": "bad" if udk_death_per_pull >= 0.5 else "warn",
         "note": "주로 어둠샘(8번), 불협화음(5번), 광휘(4번)에 죽었어요."},
    ]

    udk_tab = {
        "title": "부정 죽음의 기사 — 이디죽기",
        "sample_note": "상위권 숫자는 지금 패치(12.0.7) 기준 세계 순위권의 신화 킬 25판에서, 내 숫자는 7월 19일 우리 공대의 신화 연습 27풀에서 가져왔어요.",
        "highlights": [
            {"severity": "bad", "text": f"대마법 보호막을 {pulls_n}풀 동안 9번밖에 안 썼어요. 상위권은 막기용이 아니라 룬 마력을 채우는 용도로 1분마다, 한 판에 7번씩 써요. 딜 차이가 가장 크게 나는 부분이에요."},
            {"severity": "warn", "text": f"죽음의 고리와 괴사 코일을 1분에 {own_coil}번 쓰는데, 상위권은 {top_coil}번 가까이 써요. 룬 마력이 남아돌고 있다는 신호예요."},
            {"severity": "good", "text": "어둠의 변신과 죽음의 군대는 쿨이 돌 때마다 잘 쓰고 있어요. 전투 시작 반응도 3.3초로 빨라요."},
            {"severity": "info", "text": "이번 패치(12.0.7) 부정 죽기에는 대재앙·가고일·부정 폭행이 아예 없어요. 상위 25명도 전부 0번이니 빌드는 정상이에요."},
        ],
        "sections": [
            {"title": "쿨기·딜사이클", "rows": udk_rows_cd},
            {"title": "생존·소모품·사망", "rows": udk_rows_life},
        ],
        "caveat": "상위권 기록은 보스를 잡은 9분짜리 완주 로그이고 우리는 도중에 끝난 연습 풀이에요. "
                  "그래서 판당 횟수 대신 '1분에 몇 번'과 '몇 초 만에 첫 사용'으로 비교했어요. "
                  "1분당 값은 90초 넘게 간 풀만 모아서 계산했어요.",
    }

    out = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "encounter_id": 3183,
        "source_note": "상위권: WCL 세계 랭킹 신화 킬 · 우리: CPA42mqBHXMyca86 (07-19)",
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
