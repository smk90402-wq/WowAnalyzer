"""유튜브 자막 추출 — yt-dlp 기반. 가이드 영상 딜사이클 분석용.

브라우저 자막 추출이 토큰/패널 문제로 불안정 → yt-dlp 가 정답 (안정적).
사용: python fetch_youtube_transcript.py <url> [out_name]
  → data/transcripts/<name>.txt (타임스탬프·중복 제거된 순수 텍스트)

라이브 스트림 자동자막 없는 영상은 실패 가능 (그건 자막 자체가 없음).
"""
from __future__ import annotations
import sys, re, subprocess, tempfile, os
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

OUT = Path(__file__).parent / "data" / "transcripts"


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


def fetch(url: str, name: str) -> str | None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpl = os.path.join(tmp, "sub.%(ext)s")
        r = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--skip-download",
             "--write-auto-sub", "--write-sub", "--sub-lang", "en.*",
             "--sub-format", "vtt", "-o", tmpl, url],
            capture_output=True, text=True)
        vtts = list(Path(tmp).glob("*.vtt"))
        if not vtts:
            print(f"✗ 자막 없음: {url}\n{r.stderr[-300:]}")
            return None
        # en.vtt 우선, 없으면 첫번째
        pick = next((v for v in vtts if v.name.endswith("en.vtt")), vtts[0])
        text = parse_vtt(pick)
        dest = OUT / f"{name}.txt"
        dest.write_text(text, encoding="utf-8")
        print(f"✓ {name}: {len(text)} chars → {dest}")
        return text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python fetch_youtube_transcript.py <url> [out_name]")
        sys.exit(1)
    url = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else re.sub(r"\W+", "_", url)[-20:]
    fetch(url, name)
