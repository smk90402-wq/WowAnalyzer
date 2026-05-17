"""WoWhead 한글 스펠/특성 DB 빌더.

엔드포인트: https://nether.wowhead.com/tooltip/spell/{id}?locale=1   (locale=1 = koKR)
응답: {"name": "<한글>", "icon": "<아이콘파일>", "tooltip": "<HTML>"}
404 도 200으로 와서 비어있는 JSON이 옴 — `name` 비어있으면 "없음" 처리.

입력 스펠 ID 소스 (합집합):
  1) data/spell_db_en.json     — fetch_casts.py 가 누적한 캐스트 스펠
  2) data/cache_talents.json   — 특성 노드의 spell id (와우 특성은 결국 스펠)

출력:
  data/spell_db.json = {
    "<spell_id>": {
      "name_ko":     str,        # 한글명 ("" 면 미존재)
      "name_en":     str,        # spell_db_en.json 에서 (있으면)
      "icon":        str,        # 파일명 (확장자 .jpg 포함)
      "tooltip_ko":  str,        # WoWhead HTML 그대로
      "icon_url":    str,        # https://wow.zamimg.com/images/wow/icons/medium/<icon>
      "wowhead_url": str,        # https://www.wowhead.com/ko/spell={id}
    }
  }

WCL API 와 별개의 호스트라 fetch_casts.py 와 병렬 실행 가능.

CLI:
  python enrich_spell_ko.py             # 캐시 안 된 스펠만
  python enrich_spell_ko.py --refresh   # 캐시된 거 포함 전부 다시 (이름 비어있던 거 재시도용)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
SPELL_EN = DATA / "spell_db_en.json"
TALENTS = DATA / "cache_talents.json"
OUT = DATA / "spell_db.json"

NETHER = "https://nether.wowhead.com/tooltip/spell/{id}?locale=1"
ICON_BASE = "https://wow.zamimg.com/images/wow/icons/medium"
PAGE = "https://www.wowhead.com/ko/spell={id}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

SLEEP = 0.18          # WoWhead 는 WCL 보다 관대. 200ms 정도면 충분.
SAVE_EVERY = 50


def load_json(p: Path, default):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def gather_ids() -> tuple[set[int], dict[str, dict]]:
    """모든 후보 spell id 수집 + 영문 메타 매핑."""
    ids: set[int] = set()
    en_meta: dict[str, dict] = {}

    en = load_json(SPELL_EN, {})
    for sid, meta in en.items():
        try:
            ids.add(int(sid))
            en_meta[str(sid)] = meta
        except (TypeError, ValueError):
            pass

    talents = load_json(TALENTS, {})
    for _, players in talents.items():
        if not isinstance(players, dict):
            continue
        for _, tlist in players.items():
            if not isinstance(tlist, list):
                continue
            for tid in tlist:
                try:
                    ids.add(int(tid))
                except (TypeError, ValueError):
                    pass

    return ids, en_meta


def fetch_one(sid: int) -> dict | None:
    """WoWhead tooltip 한 건 — 재시도 포함."""
    url = NETHER.format(id=sid)
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=15, headers=HEADERS)
        except requests.RequestException as e:
            print(f"    [{sid}] req err: {e}")
            time.sleep(2 + attempt)
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 5))
            print(f"    [{sid}] 429, sleep {wait}s")
            time.sleep(wait)
            continue
        if r.status_code in (404, 400):
            return {"name": "", "icon": "", "tooltip": ""}
        if r.status_code >= 500:
            time.sleep(3 * (attempt + 1))
            continue
        try:
            return r.json()
        except ValueError:
            return None
    return None


def main() -> None:
    refresh = "--refresh" in sys.argv

    ids, en_meta = gather_ids()
    print(f"후보 spell id: {len(ids)}  (캐스트 + 특성)")

    db = load_json(OUT, {})

    todo: list[int] = []
    for sid in sorted(ids):
        key = str(sid)
        if not refresh and key in db and db[key].get("name_ko"):
            continue
        todo.append(sid)
    print(f"가져올 거: {len(todo)}  (캐시됨 사용: {len(ids) - len(todo)})")

    if not todo:
        print("새로 가져올 거 없음.")
        return

    for i, sid in enumerate(todo, 1):
        data = fetch_one(sid)
        key = str(sid)
        en = en_meta.get(key, {})
        en_name = (en.get("name") or "").strip()
        # spell_db_en.json 의 icon 은 보통 ".jpg" 가 붙어있고 WoWhead JSON 은 안 붙어있다.
        en_icon = (en.get("icon") or "").strip()

        if data is None:
            db[key] = {
                "name_ko":     "",
                "name_en":     en_name,
                "icon":        en_icon,
                "tooltip_ko":  "",
                "icon_url":    f"{ICON_BASE}/{en_icon}" if en_icon else "",
                "wowhead_url": PAGE.format(id=sid),
                "error":       "fetch_failed",
            }
        else:
            name_ko = (data.get("name") or "").strip()
            icon = (data.get("icon") or "").strip()
            icon_file = (icon + ".jpg") if icon and not icon.endswith(".jpg") else (icon or en_icon)
            db[key] = {
                "name_ko":     name_ko,
                "name_en":     en_name,
                "icon":        icon_file,
                "tooltip_ko":  data.get("tooltip") or "",
                "icon_url":    f"{ICON_BASE}/{icon_file}" if icon_file else "",
                "wowhead_url": PAGE.format(id=sid),
            }

        if i % SAVE_EVERY == 0:
            save_json(OUT, db)
            kor = sum(1 for v in db.values() if v.get("name_ko"))
            print(f"    {i}/{len(todo)}   korean_named={kor}/{len(db)}")
        time.sleep(SLEEP)

    save_json(OUT, db)

    # 요약
    kor = sum(1 for v in db.values() if v.get("name_ko"))
    no_ko_yes_en = sum(1 for v in db.values() if not v.get("name_ko") and v.get("name_en"))
    print(f"\n완료. 총 {len(db)} spell")
    print(f"  한글 있음: {kor}")
    print(f"  한글 없음(영문만): {no_ko_yes_en}")

    # 샘플 출력
    print("\n샘플 10개:")
    samples = [v for v in db.values() if v.get("name_ko")][:10]
    for s in samples:
        print(f"  {s['name_ko']:<20} / {s['name_en']:<25} / {s['icon']}")


if __name__ == "__main__":
    main()
