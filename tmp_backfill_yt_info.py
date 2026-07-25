"""s2 영상 info.json 누락분 백필 — 업로드 날짜/채널/제목 (페이싱 유지)."""
from __future__ import annotations
import json, sys, time, subprocess
from pathlib import Path

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

OUT = Path(__file__).parent / "data" / "transcripts"
VIDS = [
    "wa60mXTVPxY", "pBdUsrqwHeM", "WrO_2ES59qk", "ayJrRKgwX0A",
    "yBJ0VxLGktM", "jIybDBkRPzU", "u0zItxdOygk", "EHcmWpa4AKc",
    "Ux9DoFKaddY", "wNrlXXG-zaM", "8K1OWj2V-sI", "FbwkB5J-NCA",
    "iTvUMfwY764",
]

for vid in VIDS:
    tag = f"s2v_{vid}"
    p = OUT / f"{tag}.info.json"
    if p.exists() and p.stat().st_size > 1024:
        continue
    subprocess.run(["yt-dlp", "--skip-download", "--write-info-json",
                    "-o", str(OUT / f"{tag}.%(ext)s"),
                    f"https://www.youtube.com/watch?v={vid}"],
                   capture_output=True, text=True)
    print(f"{tag} {'✓' if p.exists() else '✗'}", flush=True)
    time.sleep(15)

metas = {}
for vid in VIDS:
    p = OUT / f"s2v_{vid}.info.json"
    if not p.exists():
        continue
    j = json.loads(p.read_text(encoding="utf-8"))
    metas[vid] = {"id": j.get("id"), "title": j.get("title"),
                  "channel": j.get("channel") or j.get("uploader"),
                  "upload_date": j.get("upload_date"),
                  "duration": j.get("duration")}
(OUT / "s2v_meta.json").write_text(
    json.dumps(metas, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"메타 {len(metas)}/13", flush=True)
