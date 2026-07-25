"""시즌2 유튜브 13영상 자막+메타 페이싱 다운로드 — yt-dlp 직접 + vtt→txt.

tmp_fetch_yt_warrior.py 패턴 (429 회피: 영상 간 GAP + 실패 시 지수 백오프).
--write-info-json 으로 업로드 날짜·채널·제목까지 한 호출에 수집 →
data/transcripts/s2v_meta.json 에 취합 (밸런스 패치 시점 추적용).
"""
from __future__ import annotations
import json, sys, time, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_youtube_transcript import parse_vtt

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

OUT = Path(__file__).parent / "data" / "transcripts"
VIDS = [
    "wa60mXTVPxY", "pBdUsrqwHeM", "WrO_2ES59qk", "ayJrRKgwX0A",
    "yBJ0VxLGktM", "jIybDBkRPzU", "u0zItxdOygk", "EHcmWpa4AKc",
    "Ux9DoFKaddY", "wNrlXXG-zaM", "8K1OWj2V-sI", "FbwkB5J-NCA",
    "iTvUMfwY764",
]
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


def info_of(tag):
    p = OUT / f"{tag}.info.json"
    if not p.exists():
        return None
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return {"id": j.get("id"), "title": j.get("title"),
            "channel": j.get("channel") or j.get("uploader"),
            "upload_date": j.get("upload_date"),
            "duration": j.get("duration")}


def main():
    ok, fail = [], []
    time.sleep(10)
    for vid in VIDS:
        tag = f"s2v_{vid}"
        if txt_ok(tag) and info_of(tag):
            print(f"{tag} 있음 skip", flush=True); ok.append(tag); continue
        (OUT / f"{tag}.txt").unlink(missing_ok=True)
        for attempt in range(4):
            if not vtt_of(tag):
                cmd = ["yt-dlp", "--skip-download", "--write-auto-sub",
                       "--write-info-json", "--no-write-playlist-metafiles",
                       "--sub-lang", "en,en-US,ko", "--sub-format", "vtt",
                       "--sleep-requests", "3", "--retries", "5", "--retry-sleep", "30",
                       "-o", str(OUT / f"{tag}.%(ext)s"),
                       f"https://www.youtube.com/watch?v={vid}"]
                subprocess.run(cmd, capture_output=True, text=True)
            v = vtt_of(tag)
            if v:
                txt = parse_vtt(v)
                (OUT / f"{tag}.txt").write_text(txt, encoding="utf-8")
                mi = info_of(tag) or {}
                print(f"{tag} ✓ {len(txt)} chars | {mi.get('upload_date')} {mi.get('channel')} | {str(mi.get('title'))[:60]}", flush=True)
                ok.append(tag)
                break
            w = 90 * (attempt + 1)
            print(f"{tag} 시도 {attempt+1} 실패 — {w}s 대기", flush=True)
            time.sleep(w)
        else:
            print(f"{tag} 포기", flush=True); fail.append(tag)
        time.sleep(GAP)

    metas = {}
    for vid in VIDS:
        mi = info_of(f"s2v_{vid}")
        if mi:
            metas[vid] = mi
    (OUT / "s2v_meta.json").write_text(
        json.dumps(metas, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n완료 {len(ok)} / 실패 {len(fail)}: {fail}", flush=True)


if __name__ == "__main__":
    main()
