"""시즌2 확장 워크플로 결과 병합 — vs_s1·PvP·이슈·추천픽.

입력: scratchpad/s2b_result.json ({extracts, entries, issues, recs} — 검증 이슈 반영 확정본)
출력: data/s2_meta_predictions.json 갱신 + data/s2_pvp_predictions.json 생성
"""
from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
RESULT = Path(sys.argv[1])
DATA = ROOT / "data" / "s2_meta_predictions.json"
PVP = ROOT / "data" / "s2_pvp_predictions.json"
VMETA = ROOT / "data" / "transcripts" / "s2v_meta.json"

res = json.loads(RESULT.read_text(encoding="utf-8"))
data = json.loads(DATA.read_text(encoding="utf-8"))
vmeta = json.loads(VMETA.read_text(encoding="utf-8"))

today = date.today().isoformat()
meta = data["_meta"]
meta["updated"] = today

# ── 출처 추가 (s2_21~s2_29) ────────────────────────────────────────────────
by_ch_date = {}
for vid, m in vmeta.items():
    d = m.get("upload_date") or ""
    key = (m.get("channel"), f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else "")
    by_ch_date.setdefault(key, vid)
have = {s["id"] for s in meta["sources"]}
for ex in res["extracts"]:
    if ex["src"] in have:
        continue
    ch = ex["ch"] if ex["ch"] != "Skill Capped" else "Skill Capped WoW PvP Guides"
    vid = by_ch_date.get((ch, ex["date"])) or by_ch_date.get((ex["ch"], ex["date"])) or ""
    vm = vmeta.get(vid, {})
    meta["sources"].append({
        "id": ex["src"], "channel": ex["ch"], "title": vm.get("title", ""),
        "date": ex["date"], "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
        "credibility": (ex.get("credibility") or {}).get("level", "mid"),
    })

# ── 이슈 + 추천 ────────────────────────────────────────────────────────────
if res.get("issues"):
    meta["issues"] = sorted(res["issues"], key=lambda i: i.get("date", ""), reverse=True)
if res.get("recs"):
    meta["reco"] = {"updated": today, **res["recs"]}

# ── 스펙 병합 (PvE 보강 + vs_s1) ──────────────────────────────────────────
n_vs = n_notes = 0
pvp_specs: dict[str, dict] = {}
for ent in res["entries"]:
    spec = data["specs"].get(ent["key"])
    if not spec:
        print(f"!! 미지 스펙 {ent['key']} — 건너뜀")
        continue
    for track, okey, nkey in (("raid", "raid_outlook", "raid_notes"),
                              ("mplus", "mplus_outlook", "mplus_notes")):
        tr = spec.setdefault(track, {})
        if ent[okey] != "?":
            tr["outlook"] = ent[okey]
        new_notes = [{"src": n["src"], "date": n["date"], "note": n["note"]}
                     for n in ent.get(nkey) or []]
        if new_notes:
            tr["notes"] = new_notes + (tr.get("notes") or [])
            n_notes += len(new_notes)
    if ent.get("changes"):
        seen = {c["note"] for c in spec.get("changes") or []}
        spec["changes"] = (spec.get("changes") or []) + [
            {"src": c["src"], "note": c["note"]} for c in ent["changes"]
            if c["note"] not in seen]
    if ent.get("summary"):
        spec["summary"] = ent["summary"]
    if ent.get("as_of") and ent["as_of"] > (spec.get("as_of") or ""):
        spec["as_of"] = ent["as_of"]
    if ent.get("vs_s1"):
        spec["vs_s1"] = ent["vs_s1"]
        n_vs += 1

    # PvP 분리 수집
    has_pvp = (ent["blitz_outlook"] != "?" or ent["shuffle_outlook"] != "?"
               or (ent.get("pvp_notes") or []))
    if has_pvp:
        notes_b = [{"src": n["src"], "date": n["date"], "note": n["note"]}
                   for n in ent.get("pvp_notes") or [] if n["mode"] == "blitz"]
        notes_s = [{"src": n["src"], "date": n["date"], "note": n["note"]}
                   for n in ent.get("pvp_notes") or [] if n["mode"] == "shuffle"]
        pvp_specs[ent["key"]] = {
            "kr": spec.get("kr") or ent["key"],
            "blitz": {"outlook": ent["blitz_outlook"], "notes": notes_b},
            "shuffle": {"outlook": ent["shuffle_outlook"], "notes": notes_s},
            "changes": [],
            "summary": (notes_b or notes_s) and (notes_b + notes_s)[0]["note"][:60] or "",
            "as_of": max((n["date"] for n in (notes_b + notes_s)), default=""),
        }

DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

pvp = {
    "_meta": {
        "patch": meta.get("patch", "12.1"), "updated": today,
        "note": "PvP(대공세·1인조합전) 예측 자료집 — 실측 아님. 시즌1 기준 티어 자료는 노트에 명시.",
        "latest_patch": meta.get("latest_patch", ""),
        "sources": [s for s in meta["sources"] if s["id"] in
                    {n["src"] for sp in pvp_specs.values()
                     for tr in ("blitz", "shuffle") for n in sp[tr]["notes"]}],
    },
    "specs": pvp_specs,
}
PVP.write_text(json.dumps(pvp, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"병합 완료 — vs_s1 {n_vs}스펙, 신규노트 {n_notes}건, 이슈 {len(res.get('issues') or [])}건,"
      f" PvP {len(pvp_specs)}스펙, 출처 {len(meta['sources'])}건, 추천픽 {'있음' if res.get('recs') else '없음'}")
