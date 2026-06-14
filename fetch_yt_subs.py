"""유튜브 자막 페이싱 다운로드 — 429 회피용 (초기 쿨다운 + 영상 간 긴 간격).

사용자 요청: 딜레이 관리해서 요청 거부 안 당하게 모든 영상 받기.
auto-sub(en 우선, ko 보조) + 영상당 sleep, --sleep-requests, 재시도.
출력: data/transcripts/demo_N.*.vtt
"""
from __future__ import annotations
import sys, time, subprocess
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

OUT = Path(__file__).parent / "data" / "transcripts"
VIDS = ["6pz0tYRkfm0", "jxPi1Lz_qS0", "6HjN1Uz8F1U", "imU-tzwCQeg", "8iZa8UJb3O8"]
COOLDOWN = 180     # 직전 429 쿨다운
GAP = 75           # 영상 간 간격


def have(i):
    return any((OUT / f"demo_{i}.{lang}.vtt").exists() for lang in ("en", "en-US", "ko"))


def main():
    print(f"초기 쿨다운 {COOLDOWN}s (직전 429 해소 대기)...", flush=True)
    time.sleep(COOLDOWN)
    for i, vid in enumerate(VIDS, 1):
        if have(i):
            print(f"demo_{i} 이미 있음 skip", flush=True)
            continue
        for attempt in range(4):
            cmd = ["yt-dlp", "--skip-download", "--write-auto-sub", "--sub-lang", "en,en-US,ko",
                   "--sub-format", "vtt", "--sleep-requests", "3", "--retries", "5",
                   "--retry-sleep", "30", "-o", str(OUT / f"demo_{i}.%(ext)s"),
                   f"https://www.youtube.com/watch?v={vid}"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            log = (r.stdout + r.stderr)
            if have(i):
                print(f"demo_{i} ({vid}) ✓", flush=True)
                break
            wait = 60 * (attempt + 1)
            tail = " | ".join(l for l in log.splitlines() if "ERROR" in l or "429" in l)[:160]
            print(f"demo_{i} 시도 {attempt+1} 실패 ({tail}) — {wait}s 대기", flush=True)
            time.sleep(wait)
        else:
            print(f"demo_{i} ({vid}) 4회 실패 — 포기", flush=True)
        time.sleep(GAP)
    print("\n생성된 자막:", flush=True)
    for f in sorted(OUT.glob("demo_*.vtt")):
        print(f"  {f.name} ({f.stat().st_size} bytes)", flush=True)


if __name__ == "__main__":
    main()
