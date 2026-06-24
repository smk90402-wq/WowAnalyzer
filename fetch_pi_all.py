"""전 스펙 Power Infusion(10060) 수령 재백필 — fight당 1쿼리 효율 방식.

기존 external_pi_buffs 는 char당 player_fight + PI 쿼리 2번. 여기선:
  1. report_meta 로 actors {name: sourceID} 확보 (report당 1쿼리, 캐시 재사용)
  2. fight당 PI 이벤트를 전체 friendly 로 1쿼리 → PI 받은 targetID 집합
  3. 각 랭킹 행: pi_received = (그 char 의 sourceID ∈ PI targetID 집합)

쿼리 수 = O(유니크 리포트 + 유니크 fight), 행 수 아님.

리줌: data/v2_cache_pi_fight.json 에 fight별 결과 캐시 → 중단 후 재실행 시 skip.

출력: data/rankings_zone46_{label}_dps_top100_pi.csv  (pi_received 컬럼 추가)

CLI:
    python fetch_pi_all.py              # mythic 전체
    python fetch_pi_all.py 4            # heroic
    python fetch_pi_all.py 5 --limit 200   # 파일럿: 유니크 fight 200개만 (비용 측정)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from wcl_v2_data import V2Data

DIFF_LABEL = {3: "normal", 4: "heroic", 5: "mythic"}
DATA = Path(__file__).parent / "data"
PI_FIGHT_CACHE = DATA / "v2_cache_pi_fight.json"
PI_SPELL = 10060

# 전체 friendly 대상 PI 이벤트 (targetID 필터 없음) — fight 전원 한 번에
Q_PI_FIGHT = """
query($code: String!, $start: Float!, $end: Float!) {
  reportData {
    report(code: $code) {
      events(
        dataType: Buffs
        startTime: $start
        endTime: $end
        abilityID: 10060
        hostilityType: Friendlies
      ) { data nextPageTimestamp }
    }
  }
}
"""


def _load(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _flush_v2_cache(d: V2Data) -> None:
    try:
        d.flush()
    except Exception as e:
        print(f"  warn: V2 cache flush skipped: {str(e)[:100]}", flush=True)


def pi_targets_for_fight(d: V2Data, rid: str, start: float, end: float) -> list[int]:
    """fight window 동안 PI(10060) 받은 targetID 집합. apply/refresh 만."""
    targets: set[int] = set()
    cur = float(start)
    for _ in range(10):  # pagination (PI 이벤트는 많지 않음)
        data = d.cli.query(Q_PI_FIGHT, {"code": rid, "start": cur, "end": float(end)})
        obj = (((data or {}).get("reportData") or {}).get("report") or {}).get("events") or {}
        for e in (obj.get("data") or []):
            if not isinstance(e, dict):
                continue
            t = (e.get("type") or "")
            if t.startswith(("apply", "refresh")):
                tid = e.get("targetID")
                if isinstance(tid, int):
                    targets.add(tid)
        nxt = obj.get("nextPageTimestamp")
        if not nxt or nxt <= cur:
            break
        cur = float(nxt)
    return sorted(targets)


def main(difficulty: int = 5, limit: int | None = None) -> None:
    label = DIFF_LABEL.get(difficulty, f"diff{difficulty}")
    src = DATA / f"rankings_zone46_{label}_dps_top100.csv"
    if not src.exists():
        sys.exit(f"랭킹 CSV 없음: {src.name} — fetch_rankings_v2.py {difficulty} 먼저")
    out = DATA / f"rankings_zone46_{label}_dps_top100_pi.csv"

    df = pd.read_csv(src)
    df = df[df["report_id"].notna() & df["fight_id"].notna()].copy()
    df["fid"] = df["fight_id"].astype(int)

    d = V2Data(data_dir=DATA)
    pi_fight = _load(PI_FIGHT_CACHE)  # {"rid:fid": [targetIDs]}

    # 유니크 fight 목록 (캐시 미스만)
    uniq = (df[["report_id", "fid"]].drop_duplicates()
            .itertuples(index=False, name=None))
    todo = [(rid, fid) for rid, fid in uniq
            if f"{rid}:{fid}" not in pi_fight]
    if limit:
        todo = todo[:limit]

    rate0 = d.cli.points_left() or {}
    t0 = time.time()
    print(f"=== PI 재백필 {label} ===")
    print(f"  유니크 fight todo: {len(todo):,}  (캐시됨 {len(pi_fight):,})")
    print(f"  rate start: {rate0.get('pointsSpentThisHour','?')}/{rate0.get('limitPerHour','?')}")

    done = 0
    fail = 0
    for rid, fid in todo:
        # report_meta 로 fight window 확보
        meta = d.report_meta(rid)
        fights = (meta or {}).get("fights") or []
        f = next((x for x in fights if x.get("id") == fid), None)
        if not f:
            pi_fight[f"{rid}:{fid}"] = []
            fail += 1
        else:
            try:
                tgts = pi_targets_for_fight(d, rid, f["startTime"], f["endTime"])
                pi_fight[f"{rid}:{fid}"] = tgts
            except Exception as e:
                print(f"    fail {rid}:{fid}: {str(e)[:80]}")
                fail += 1
                pi_fight[f"{rid}:{fid}"] = []
        done += 1
        if done % 50 == 0:
            _save(PI_FIGHT_CACHE, pi_fight)
            _flush_v2_cache(d)  # report_meta cache best-effort
            rate = d.cli.points_left() or {}
            spent = (rate.get("pointsSpentThisHour", 0) - rate0.get("pointsSpentThisHour", 0))
            el = time.time() - t0
            rps = done / el if el > 0 else 0
            print(f"  {done}/{len(todo)}  fail={fail}  "
                  f"점수소비={spent:.0f}  {rps:.1f}fight/s  "
                  f"rate={rate.get('pointsSpentThisHour','?')}/18000")
        time.sleep(0.03)

    _save(PI_FIGHT_CACHE, pi_fight)
    _flush_v2_cache(d)
    rate1 = d.cli.points_left() or {}
    spent = (rate1.get("pointsSpentThisHour", 0) - rate0.get("pointsSpentThisHour", 0))
    el = time.time() - t0
    print(f"\nfight 페치 완료: {done} done, {fail} fail, {el:.0f}s, 점수 {spent:.0f}")

    # ── pi_received 컬럼 빌드 (전체 행, limit 무관하게 캐시된 것으로) ─────
    pi_vals = []
    matched = 0
    no_src = 0
    no_fight = 0
    for _, r in df.iterrows():
        rid = str(r["report_id"]); fid = int(r["fid"]); char = str(r["character"])
        key = f"{rid}:{fid}"
        if key not in pi_fight:
            pi_vals.append(None); no_fight += 1; continue
        meta = d.meta.get(rid)
        actors = (meta or {}).get("actors") or {}
        sid = actors.get(char)
        if not isinstance(sid, int):
            pi_vals.append(None); no_src += 1; continue
        pi_vals.append(sid in set(pi_fight[key])); matched += 1
    df["pi_received"] = pi_vals
    df.drop(columns=["fid"]).to_csv(out, index=False, encoding="utf-8")
    print(f"\nCSV: {out.name}")
    print(f"  pi_received 매칭: {matched:,}  (sourceID 없음 {no_src:,}, fight 미페치 {no_fight:,})")
    got = sum(1 for v in pi_vals if v is True)
    print(f"  PI 받음: {got:,} / {matched:,}  ({100*got/max(1,matched):.1f}%)")

    try:
        from update_log import record
        record(
            action="fetch_pi_all",
            params={"difficulty": difficulty, "label": label, "limit": limit},
            result={"fights_done": done, "fights_fail": fail,
                    "rows_matched": matched, "pi_received": got,
                    "points": round(spent, 0)},
            files=[f"data/{out.name}", "data/v2_cache_pi_fight.json"],
        )
    except Exception as e:
        print(f"[update_log] skip: {e}")


if __name__ == "__main__":
    diff = 5
    limit = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--limit":
            limit = int(args[i + 1]); i += 2
        else:
            diff = int(args[i]); i += 1
    main(difficulty=diff, limit=limit)
