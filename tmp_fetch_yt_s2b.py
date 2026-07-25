"""시즌2 추가 9영상(PvP 2 + 이슈 7) 자막+메타 페이싱 다운로드.

tmp_fetch_yt_s2.py 패턴 — 자막 1패스 후 info.json 백필 2패스 (한 호출에
--write-info-json 이 안 먹는 현상 회피).
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
    "YbjvOhxVrw0", "OaYpLnFOjzw",                     # PvP 후보
    "6G_Sg4xJol4", "oJ9UHJ3GFIQ", "dEB83B3OpfI",      # 이슈·기타
    "25oNFzR-_qU", "ZAjeE9_d79E", "7UTSF0BXbD4", "Ukez0aqmZ34",
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


def main():
    ok, fail = [], []
    time.sleep(5)
    for vid in VIDS:
        tag = f"s2v_{vid}"
        if txt_ok(tag):
            print(f"{tag} 있음 skip", flush=True); ok.append(tag); continue
        (OUT / f"{tag}.txt").unlink(missing_ok=True)
        for attempt in range(4):
            if not vtt_of(tag):
                subprocess.run(
                    ["yt-dlp", "--skip-download", "--write-auto-sub",
                     "--sub-lang", "en,en-US,ko", "--sub-format", "vtt",
                     "--sleep-requests", "3", "--retries", "5", "--retry-sleep", "30",
                     "-o", str(OUT / f"{tag}.%(ext)s"),
                     f"https://www.youtube.com/watch?v={vid}"],
                    capture_output=True, text=True)
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

    # 2패스 — info.json 백필 (단독 호출은 정상 동작 확인됨)
    for vid in VIDS:
        tag = f"s2v_{vid}"
        p = OUT / f"{tag}.info.json"
        if p.exists() and p.stat().st_size > 1024:
            continue
        subprocess.run(["yt-dlp", "--skip-download", "--write-info-json",
                        "-o", str(OUT / f"{tag}.%(ext)s"),
                        f"https://www.youtube.com/watch?v={vid}"],
                       capture_output=True, text=True)
        print(f"{tag} info {'✓' if p.exists() else '✗'}", flush=True)
        time.sleep(15)

    metas_p = OUT / "s2v_meta.json"
    metas = json.loads(metas_p.read_text(encoding="utf-8")) if metas_p.exists() else {}
    for vid in VIDS:
        p = OUT / f"s2v_{vid}.info.json"
        if not p.exists():
            continue
        j = json.loads(p.read_text(encoding="utf-8"))
        metas[vid] = {"id": j.get("id"), "title": j.get("title"),
                      "channel": j.get("channel") or j.get("uploader"),
                      "upload_date": j.get("upload_date"),
                      "duration": j.get("duration")}
    metas_p.write_text(json.dumps(metas, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n완료 {len(ok)} / 실패 {len(fail)}: {fail} · 메타 {len(metas)}건", flush=True)


if __name__ == "__main__":
    main()
