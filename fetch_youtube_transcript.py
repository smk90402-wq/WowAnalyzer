"""유튜브 자막 추출 — yt-dlp + watch-page captionTracks 백업.

사용: python fetch_youtube_transcript.py <url> [out_name]
  → data/transcripts/<name>.txt (타임스탬프·중복 제거된 순수 텍스트)

yt-dlp가 YouTube 429에 걸리면 watch page HTML의 captionTracks를 직접 읽는다.
라이브 스트림 자동자막 없는 영상은 실패 가능 (그건 자막 자체가 없음).
"""
from __future__ import annotations
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import xml.etree.ElementTree as ET

import requests
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

OUT = Path(__file__).parent / "data" / "transcripts"
YOUTUBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def parse_vtt(path: Path) -> str:
    """VTT → 순수 텍스트 (타임스탬프·인라인태그·중복줄 제거)."""
    out, seen = [], set()
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or "-->" in ln or ln.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        ln = re.sub(r"<[^>]+>", "", ln)        # 인라인 타임태그
        ln = re.sub(r"&\w+;", "", ln)          # HTML 엔티티
        if ln and ln not in seen:
            seen.add(ln)
            out.append(ln)
    return " ".join(out)


def clean_caption_lines(lines: list[str]) -> str:
    out, seen = [], set()
    for ln in lines:
        ln = re.sub(r"<[^>]+>", "", ln).strip()
        ln = html.unescape(ln)
        if ln and ln not in seen:
            seen.add(ln)
            out.append(ln)
    return " ".join(out)


def parse_vtt_text(raw: str) -> str:
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln or "-->" in ln or ln.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        lines.append(ln)
    return clean_caption_lines(lines)


def parse_timedtext_xml(raw: str) -> str:
    root = ET.fromstring(raw)
    return clean_caption_lines([node.text or "" for node in root.findall(".//text")])


def extract_json_object(text: str, marker: str) -> dict | None:
    start = text.find(marker)
    if start < 0:
        return None
    brace_start = text.find("{", start)
    if brace_start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(brace_start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[brace_start:idx + 1])
    return None


def with_query_param(url: str, key: str, value: str) -> str:
    parts = urlparse(html.unescape(url))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[key] = value
    return urlunparse(parts._replace(query=urlencode(query)))


def pick_caption_track(tracks: list[dict]) -> dict | None:
    for prefix in ("ko", "en"):
        for track in tracks:
            if str(track.get("languageCode", "")).lower().startswith(prefix):
                return track
    return tracks[0] if tracks else None


def fetch_from_watch_page(url: str, name: str) -> str | None:
    resp = requests.get(url, headers=YOUTUBE_HEADERS, timeout=25)
    resp.raise_for_status()
    player = (
        extract_json_object(resp.text, "ytInitialPlayerResponse =")
        or extract_json_object(resp.text, "ytInitialPlayerResponse=")
    )
    tracks = player.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", []) if player else []
    track = pick_caption_track(tracks)
    if not track:
        return None
    caption_url = with_query_param(track["baseUrl"], "fmt", "vtt")
    cap = requests.get(caption_url, headers=YOUTUBE_HEADERS, timeout=25)
    cap.raise_for_status()
    raw = cap.text
    (OUT / f"{name}.{track.get('languageCode', 'caption')}.vtt").write_text(raw, encoding="utf-8")
    if raw.lstrip().startswith("<?xml") or "<transcript" in raw[:200]:
        text = parse_timedtext_xml(raw)
    else:
        text = parse_vtt_text(raw)
    dest = OUT / f"{name}.txt"
    dest.write_text(text, encoding="utf-8")
    label = track.get("name", {}).get("simpleText") or track.get("languageCode", "caption")
    print(f"✓ {name}: {len(text)} chars → {dest} (watch-page captionTracks: {label})")
    return text


def fetch_with_ytdlp(url: str, name: str) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        tmpl = os.path.join(tmp, "sub.%(ext)s")
        r = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--skip-download",
             "--write-auto-sub", "--write-sub", "--sub-lang", "ko.*,ko,en.*,en",
             "--sub-format", "vtt", "-o", tmpl, url],
            capture_output=True, text=True)
        vtts = list(Path(tmp).glob("*.vtt"))
        if not vtts:
            print(f"yt-dlp 자막 실패, watch-page captionTracks로 재시도합니다.\n{r.stderr[-300:]}")
            return None
        # ko 우선, 없으면 en, 그래도 없으면 첫번째
        pick = next((v for v in vtts if ".ko" in v.name), None)
        pick = pick or next((v for v in vtts if ".en" in v.name), None) or vtts[0]
        text = parse_vtt(pick)
        dest = OUT / f"{name}.txt"
        dest.write_text(text, encoding="utf-8")
        print(f"✓ {name}: {len(text)} chars → {dest}")
        return text


def fetch(url: str, name: str) -> str | None:
    OUT.mkdir(parents=True, exist_ok=True)
    text = fetch_with_ytdlp(url, name)
    if text:
        return text
    text = fetch_from_watch_page(url, name)
    if not text:
        print(f"✗ 자막 없음: {url}")
    return text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python fetch_youtube_transcript.py <url> [out_name]")
        sys.exit(1)
    url = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else re.sub(r"\W+", "_", url)[-20:]
    fetch(url, name)
