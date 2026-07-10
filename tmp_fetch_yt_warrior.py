"""전사(분노/무기) 유튜브 12영상 자막 페이싱 다운로드 — yt-dlp 직접 + vtt→txt.

429 회피: 초기 쿨다운 + 영상 간 GAP + 실패 시 지수 백오프 (fetch_yt_fury.py 패턴).
"""
from __future__ import annotations
import sys, time, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_youtube_transcript import parse_vtt

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

OUT = Path(__file__).parent / "data" / "transcripts"
VIDS = [
    ("warr_J0fFP6UQ5RI", "J0fFP6UQ5RI"),
    ("warr_GVQfTXok804", "GVQfTXok804"),
    ("warr_dqBUr6sr24Q", "dqBUr6sr24Q"),
    ("warr_iT8yXy9kpzk", "iT8yXy9kpzk"),
    ("warr_4Qj0qHVoClc", "4Qj0qHVoClc"),
    ("warr_o-VIlXdW4wg", "o-VIlXdW4wg"),
    ("warr_jKPoWzu4ICg", "jKPoWzu4ICg"),
    ("warr_G6y-3KUsQvE", "G6y-3KUsQvE"),
    ("warr_CvlX_b46cuo", "CvlX_b46cuo"),
    ("warr_Ut2t5DfMggM", "Ut2t5DfMggM"),
    ("warr_Z2EfigYttyc", "Z2EfigYttyc"),
    ("warr_jsCiMCFdkfA", "jsCiMCFdkfA"),
]
COOLDOWN = 180
GAP = 90


def vtt_of(tag):
    for lang in ("en", "en-US", "en-GB", "ko"):
        p = OUT / f"{tag}.{lang}.vtt"
        if p.exists() and p.stat().st_size > 1024:
            return p
    return None


def txt_ok(tag):
    p = OUT / f"{tag}.txt"
    return p.exists() and p.stat().st_size > 1024


def main():
    ok, fail = [], []
    time.sleep(COOLDOWN)
    for tag, vid in VIDS:
        if txt_ok(tag):
            print(f"{tag} 있음 skip", flush=True); ok.append(tag); continue
        (OUT / f"{tag}.txt").unlink(missing_ok=True)  # 0바이트 잔재 제거
        for attempt in range(4):
            if not vtt_of(tag):
                cmd = ["yt-dlp", "--skip-download", "--write-auto-sub",
                       "--sub-lang", "en,en-US,ko", "--sub-format", "vtt",
                       "--sleep-requests", "3", "--retries", "5", "--retry-sleep", "30",
                       "-o", str(OUT / f"{tag}.%(ext)s"),
                       f"https://www.youtube.com/watch?v={vid}"]
                subprocess.run(cmd, capture_output=True, text=True)
            v = vtt_of(tag)
            if v:
                txt = parse_vtt(v)
                (OUT / f"{tag}.txt").write_text(txt, encoding="utf-8")
                print(f"{tag} ✓ {len(txt)} chars", flush=True)
                ok.append(tag)
                break
            w = 90 * (attempt + 1)
            print(f"{tag} 시도 {attempt+1} 실패 — {w}s 대기", flush=True)
            time.sleep(w)
        else:
            print(f"{tag} 포기", flush=True); fail.append(tag)
        time.sleep(GAP)
    print(f"\n완료 {len(ok)} / 실패 {len(fail)}: {fail}", flush=True)


if __name__ == "__main__":
    main()
