"""분노 전사 유튜브 4영상 자막 페이싱 다운로드 (429 회피)."""
from __future__ import annotations
import sys, time, subprocess
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

OUT = Path(__file__).parent / "data" / "transcripts"
VIDS = [("fury_easy", "GVQfTXok804"), ("fury_guide", "J0fFP6UQ5RI"),
        ("fury_1205", "NnLtDF7QFG8"), ("fury_procprio", "89jBoPv5wqU")]
COOLDOWN = 30
GAP = 60


def have(tag):
    return any((OUT / f"{tag}.{l}.vtt").exists() for l in ("en", "en-US", "ko"))


def main():
    time.sleep(COOLDOWN)
    for tag, vid in VIDS:
        if have(tag):
            print(f"{tag} 있음 skip", flush=True); continue
        for attempt in range(4):
            cmd = ["yt-dlp", "--skip-download", "--write-auto-sub", "--sub-lang", "en,en-US,ko",
                   "--sub-format", "vtt", "--sleep-requests", "3", "--retries", "5", "--retry-sleep", "30",
                   "-o", str(OUT / f"{tag}.%(ext)s"), f"https://www.youtube.com/watch?v={vid}"]
            subprocess.run(cmd, capture_output=True, text=True)
            if have(tag):
                print(f"{tag} ({vid}) ✓", flush=True); break
            w = 60 * (attempt + 1)
            print(f"{tag} 시도 {attempt+1} 실패 — {w}s", flush=True); time.sleep(w)
        else:
            print(f"{tag} 포기", flush=True)
        time.sleep(GAP)
    print("\n생성:", flush=True)
    for f in sorted(OUT.glob("fury_*.vtt")):
        print(f"  {f.name} ({f.stat().st_size}b)", flush=True)


if __name__ == "__main__":
    main()
