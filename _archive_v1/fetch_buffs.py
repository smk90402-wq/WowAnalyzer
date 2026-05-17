"""타깃 3스펙 ranking 들의 버프 apply/remove 이벤트 fetch.

이걸로 잡히는 것 (한 곳에서 다 옴):
  - 대형 쿨다운: 야성의 격노 · 천계 정렬 · 소환 폭군 · 영혼불꽃 등
  - 물약: Tempered Potion of Power, Lightblood Elixir 등 가상의 한밤 물약
  - 개인 생존기: 차원회피, 곰 변신, 황혼방패 등 클래스별 방어기
  - 추적버프 (상태): 일식·스타로드·광폭화·악마 핵 누적 등
  - 프록 (트리거 가능 버프): 별빛섬광, 광폭의 부름 등

API: /v1/report/events/buffs/{rid}?start=&end=&sourceid=&hostility=0
  - sourceid 가 본인 캐릭이면 본인이 받은/터지는 버프
  - 페이지네이션 nextPageTimestamp

캐스트 fetch 와 동일한 패턴 — 같은 source_id 매핑 재사용
(cache_source_ids.json — fetch_casts.py 가 만들어둠).

⚠️ fetch_casts.py 와 같은 WCL API 키를 공유하므로 동시에 돌리면 429 가
세져서 양쪽 다 느려진다. fetch_casts.py 완료 후 단독으로 실행할 것.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()
KEY = os.environ["WCL_V1_KEY"]
BASE = "https://www.warcraftlogs.com/v1"
SLEEP = 0.35

DATA = Path(__file__).parent / "data"
CSV_IN = DATA / "rankings_zone46_mythic_dps_top100.csv"
CACHE_FIGHTS = DATA / "cache_fights.json"
CACHE_SRCIDS = DATA / "cache_source_ids.json"
CACHE_BUFFS = DATA / "cache_buffs.json"
BUFF_DB = DATA / "buff_db_en.json"

TARGETS = {
    ("Warlock", "Demonology"),
    ("Druid",   "Balance"),
    ("Hunter",  "Beast Mastery"),
}


def load_json(p: Path):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_json(p: Path, obj) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


cache_fights: dict = load_json(CACHE_FIGHTS)
cache_srcids: dict = load_json(CACHE_SRCIDS)
cache_buffs: dict = load_json(CACHE_BUFFS)
buff_db: dict = load_json(BUFF_DB)


def api_get(url: str, params: dict) -> dict | None:
    params = dict(params, api_key=KEY)
    for attempt in range(6):
        try:
            r = requests.get(url, params=params, timeout=45)
        except requests.RequestException as e:
            print(f"    req err: {e}")
            time.sleep(4)
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 30))
            print(f"    429, sleep {wait}s")
            time.sleep(wait)
            continue
        if r.status_code in (400, 403, 404):
            return None
        if r.status_code >= 500:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    return None


def absorb_ability(ev: dict) -> None:
    ab = ev.get("ability") or {}
    gid = ab.get("guid")
    if not isinstance(gid, int) or gid <= 0:
        return
    key = str(gid)
    if key in buff_db:
        return
    buff_db[key] = {
        "name": ab.get("name") or "",
        "icon": ab.get("abilityIcon") or "",
    }


def fetch_buffs(rid: str, fid: int, sid: int, start_ms: int, end_ms: int) -> list | None:
    key = f"{rid}:{fid}:{sid}"
    if key in cache_buffs:
        return cache_buffs[key]

    collected: list[list] = []
    cur_start = start_ms
    page = 0
    while True:
        page += 1
        data = api_get(
            f"{BASE}/report/events/buffs/{rid}",
            {"start": cur_start, "end": end_ms,
             "sourceid": sid, "hostility": 0},
        )
        if data is None:
            cache_buffs[key] = None
            return None
        events = data.get("events") or []
        for ev in events:
            ab = ev.get("ability") or {}
            gid = ab.get("guid")
            ts = ev.get("timestamp")
            t = ev.get("type") or ""
            if not isinstance(gid, int) or ts is None:
                continue
            # 누적 스택용 stack 필드도 있으면 같이 저장
            stack = ev.get("stack")
            collected.append([ts, gid, t, stack] if stack is not None else [ts, gid, t])
            absorb_ability(ev)
        nxt = data.get("nextPageTimestamp")
        if not nxt or nxt <= cur_start or page > 20:
            break
        cur_start = nxt
        time.sleep(SLEEP)
    cache_buffs[key] = collected
    return collected


def main(limit: int | None = None) -> None:
    if not cache_srcids:
        sys.exit("cache_source_ids.json 비어있음 — fetch_casts.py 먼저 돌려야 함.")

    df = pd.read_csv(CSV_IN)
    df["report_id"] = df["report_id"].astype(str)
    df["fight_id"] = df["fight_id"].astype(int)
    sub = df[df.apply(lambda r: (r["class"], r["spec"]) in TARGETS, axis=1)].copy()
    sub = sub.sort_values(["encounter_name", "class", "spec", "rank"]).reset_index(drop=True)
    if limit is not None:
        sub = sub.head(limit)
    print(f"Target ranking rows: {len(sub)}")

    todo = []
    skipped_no_window = skipped_no_sid = 0
    for _, row in sub.iterrows():
        rid = row["report_id"]; fid = int(row["fight_id"]); char = row["character"]
        window = (cache_fights.get(rid) or {}).get(str(fid))
        if not window:
            skipped_no_window += 1; continue
        sid_map = cache_srcids.get(rid)
        sid = sid_map.get(char) if isinstance(sid_map, dict) else None
        if sid is None:
            skipped_no_sid += 1; continue
        key = f"{rid}:{fid}:{sid}"
        if key in cache_buffs:
            continue
        todo.append((rid, fid, int(sid), int(window[0]), int(window[1])))

    print(f"buff fetch todo: {len(todo)}  "
          f"(no_window={skipped_no_window}, no_sid={skipped_no_sid})")

    for i, (rid, fid, sid, s, e) in enumerate(todo, 1):
        fetch_buffs(rid, fid, sid, s, e)
        if i % 25 == 0:
            save_json(CACHE_BUFFS, cache_buffs)
            save_json(BUFF_DB, buff_db)
            print(f"    {i}/{len(todo)}   buffs_seen={len(buff_db)}")
        time.sleep(SLEEP)
    save_json(CACHE_BUFFS, cache_buffs)
    save_json(BUFF_DB, buff_db)

    covered = sum(
        1 for _, r in sub.iterrows()
        if (sm := cache_srcids.get(r["report_id"])) and isinstance(sm, dict)
        and r["character"] in sm
        and cache_buffs.get(f"{r['report_id']}:{int(r['fight_id'])}:{sm[r['character']]}") is not None
    )
    print(f"\nDone. {covered}/{len(sub)} rows have buff events.")
    print(f"Distinct buffs captured: {len(buff_db)}")


if __name__ == "__main__":
    lim = None
    if len(sys.argv) > 1:
        try:
            lim = int(sys.argv[1])
        except ValueError:
            sys.exit(f"bad limit arg: {sys.argv[1]}")
    main(lim)
