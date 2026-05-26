"""데이터 갱신 history — PC 간 sync (LFS 아닌 일반 git).

매 데이터 스크립트 (fetch_rankings_v2, backfill_v2, enrich_spell_ko 등) 가
끝날 때 record() 호출. 다른 PC 에서 `git pull` 후 "언제/어디서 뭐 갱신됐는지"
한 눈에 봄.

스키마 (data/update_log.json):
    {
      "entries": [
        {
          "ts":     "2026-05-27T00:35:52",
          "host":   "SmkDesktop",
          "action": "fetch_rankings_v2",
          "params": {...},   # 자유 형식
          "result": {...},   # 자유 형식 (rows, api_pts, ...)
          "files":  ["data/rankings_zone46_heroic_dps_top100.csv"]
        }, ...
      ]
    }

오래된 entry 는 MAX_ENTRIES 만큼만 유지.

CLI:
    python update_log.py show       # 최근 20 entries
    python update_log.py show 50    # 최근 50

데이터 스크립트 사용:
    from update_log import record
    record(
        action="fetch_rankings_v2",
        params={"difficulty": 5, "label": "mythic"},
        result={"rows": 22948, "api_pts": 247},
        files=["data/rankings_zone46_mythic_dps_top100.csv"],
    )
"""
from __future__ import annotations

import json
import socket
import sys
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).parent / "data" / "update_log.json"
MAX_ENTRIES = 500


def _load() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    try:
        data = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        entries = data.get("entries") if isinstance(data, dict) else None
        return entries if isinstance(entries, list) else []
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"entries": entries[-MAX_ENTRIES:]}
    LOG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record(action: str, params: dict | None = None,
           result: dict | None = None,
           files: list[str] | None = None) -> None:
    """update_log.json 에 한 entry append. 예외 발생해도 silently skip
    (스크립트 본 작업이 끝난 후 호출되므로 logging 만 실패해도 무시)."""
    try:
        entries = _load()
        entries.append({
            "ts":     datetime.now().isoformat(timespec="seconds"),
            "host":   socket.gethostname(),
            "action": action,
            "params": params or {},
            "result": result or {},
            "files":  files or [],
        })
        _save(entries)
    except Exception as e:
        print(f"[update_log] record 실패 (무시): {e}", file=sys.stderr)


def recent(n: int = 20) -> list[dict]:
    return _load()[-n:]


def _cli() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) >= 2 and sys.argv[1] == "show":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        entries = recent(n)
        if not entries:
            print("(no entries yet)")
            return
        for e in entries:
            params = e.get("params") or {}
            result = e.get("result") or {}
            files = e.get("files") or []
            params_s = json.dumps(params, ensure_ascii=False) if params else ""
            result_s = json.dumps(result, ensure_ascii=False) if result else ""
            print(f"{e['ts']} [{e['host']:>12}] {e['action']}")
            if params_s: print(f"  params: {params_s}")
            if result_s: print(f"  result: {result_s}")
            if files:    print(f"  files:  {files}")
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
