"""WoWhead 가이드 페이지에서 추천 talent build 추출.

각 가이드 페이지의 BBCode 마크다운에서 다음 패턴 매칭:
  [symbol=wow-hero-talent-{hero}] [b][color=...]{scenario}[/color][/b] [copy="..."]CODE[/copy]

타깃 5스펙. 출력: data/wowhead_builds.json
  {
    "Warlock/Demonology": [
      {"hero": "diabolist", "scenario": "Raid", "is_best": true, "code": "C..."},
      ...
    ],
    ...
  }
"""
from __future__ import annotations
import json, re, sys, time
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = Path(__file__).parent / "data"
OUT = DATA / "wowhead_builds.json"
URL = "https://www.wowhead.com/guide/classes/{cls}/{spec}/talent-builds-pve-dps"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# (display class key, display spec key, url-class, url-spec)
TARGETS = [
    ("Warlock", "Demonology",    "warlock",     "demonology"),
    ("Druid",   "Balance",       "druid",       "balance"),
    ("Hunter",  "Beast Mastery", "hunter",      "beast-mastery"),
    ("Warrior", "Arms",          "warrior",     "arms"),
    ("Warrior", "Fury",          "warrior",     "fury"),
]


def parse_builds(html: str) -> list[dict]:
    """페이지 HTML 에서 추천 빌드 추출."""
    # BBCode 가 JS 문자열에 임베드돼서 escape 됨 (\\/ → /, \\" → ")
    text = html.replace(r"\/", "/").replace(r'\"', '"')

    # 모든 [copy="..."]CODE[/copy] 찾기, hero forward-fill
    builds: list[dict] = []
    pattern = re.compile(
        r'\[copy="(?P<label>[^"]*)"\](?P<code>C[A-Za-z0-9_\-/+]{60,200})\[/copy\]'
    )
    # 페이지 전체에서 hero symbol 위치 미리 인덱싱
    hero_positions = [(m.start(), m.group(1)) for m in
                      re.finditer(r'\[symbol=wow-hero-talent-([\w-]+)\]', text)]

    for m in pattern.finditer(text):
        code = m.group("code")
        label = m.group("label")
        # 가장 가까운 (가장 큰) hero pos < m.start()
        hero = None
        for hpos, hname in reversed(hero_positions):
            if hpos < m.start():
                hero = hname
                break
        # scenario: 가장 가까운 [color=...]X[/color] (앞 400자 내)
        back = text[max(0, m.start() - 400):m.start()]
        scn_m = list(re.finditer(r'\[color=[^\]]+\]([^\[]+)\[/color\]', back))
        scenario = scn_m[-1].group(1).strip() if scn_m else label
        is_best = "(Best)" in back[-300:]
        builds.append({
            "hero": hero,
            "scenario": scenario,
            "is_best": is_best,
            "code": code,
        })
    return builds


def fetch_spec(cls_url: str, spec_url: str) -> list[dict]:
    url = URL.format(cls=cls_url, spec=spec_url)
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}: {url}")
        return []
    return parse_builds(r.text)


def main() -> None:
    out: dict[str, list[dict]] = {}
    for cls_disp, spec_disp, cls_u, spec_u in TARGETS:
        key = f"{cls_disp}/{spec_disp}"
        print(f"\n=== {key} ===")
        builds = fetch_spec(cls_u, spec_u)
        print(f"  builds: {len(builds)}")
        for b in builds:
            best = " (BEST)" if b["is_best"] else ""
            hero = b.get("hero") or "?"
            scn = b.get("scenario") or "?"
            print(f"    {hero:<20} {scn:<14}{best}  code={b['code'][:40]}...")
        out[key] = builds
        time.sleep(1.0)  # WoWhead 친화적

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {OUT}")


if __name__ == "__main__":
    main()
