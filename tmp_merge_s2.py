"""시즌2 워크플로 결과 → data/s2_meta_predictions.json 병합.

입력: scratchpad/s2_workflow_result.json  ({extracts, entries, ...} — 검증 이슈 반영 후 확정본)
- _meta: sources s2_8~s2_20 추가, updated/latest_patch/patch_events/general 갱신
- specs: outlook/trend/as_of/summary 갱신, 신규 노트 앞쪽 병합, changes 뒤에 추가
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
RESULT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "s2_workflow_result.json"
DATA = ROOT / "data" / "s2_meta_predictions.json"
VMETA = ROOT / "data" / "transcripts" / "s2v_meta.json"

res = json.loads(RESULT.read_text(encoding="utf-8"))
data = json.loads(DATA.read_text(encoding="utf-8"))
vmeta = json.loads(VMETA.read_text(encoding="utf-8"))

by_src = {e["src"]: e for e in res["extracts"]}
srcid_to_vid = {e["src"]: vid for vid, m in vmeta.items()
                for e in res["extracts"] if e["ch"] == m["channel"] and e["date"] == f"{m['upload_date'][:4]}-{m['upload_date'][4:6]}-{m['upload_date'][6:]}"}

meta = data["_meta"]
meta["updated"] = "2026-07-25"
meta["status"] = "12.1 미출시 — PTR 진행 중. 예상: 패치 8/11, 시즌2 시작 8/18경 (공식 미발표)"
meta["latest_patch"] = "2026-07-22"   # 대형 버프 패스 — 카드 ⚠ 신선도 기준
meta["patch_events"] = [
    {"date": "2026-06-18", "note": "첫 12.1 PTR 빌드 — 주요 쿨다운 순폭 너프+평시딜 버프 기조"},
    {"date": "2026-07-01", "note": "혈죽 티어셋 전면 리워크(Blood Debt) 적용"},
    {"date": "2026-07-08", "note": "대형 너프 패스 — DK 전반 너프, Scalecommander(증강·황폐) 쿨감 해체"},
    {"date": "2026-07-15", "note": "야수의 회오리 취소불가 수정, 생존 화염폭탄 버프"},
    {"date": "2026-07-16", "note": "신화 테스트 전 광범위 핫픽스 — 보존 레이드 너프·쐐기 버프"},
    {"date": "2026-07-22", "note": "대형 버프 패스 — 혈죽·부죽 대폭 버프, 야수 광역 55%, 복술 티어 반토막"},
    {"date": "2026-07-23", "note": "사냥꾼·주술사·전사 티어셋 추가 변경"},
    {"date": "2026-07-24", "note": "버그픽스 + 힐러 튜닝(신기 +5%, 운무·회드 너프)"},
]

have = {s["id"] for s in meta["sources"]}
for src_id in sorted(by_src, key=lambda s: int(s.split("_")[1])):
    if src_id in have:
        continue
    ex = by_src[src_id]
    vid = srcid_to_vid.get(src_id, "")
    vm = vmeta.get(vid, {})
    meta["sources"].append({
        "id": src_id, "channel": ex["ch"], "title": vm.get("title", ""),
        "date": ex["date"], "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
        "credibility": (ex.get("credibility") or {}).get("level", "mid"),
    })

general = [
    {"src": e["src"], "date": e["date"], "note": e["season_notes"].strip()}
    for e in res["extracts"] if (e.get("season_notes") or "").strip()
]
if general:
    meta["general"] = sorted(general, key=lambda g: g["date"], reverse=True)

n_updated = 0
for ent in res["entries"]:
    spec = data["specs"].get(ent["key"])
    if not spec:
        print(f"!! 미지 스펙 {ent['key']} — 건너뜀")
        continue
    for track, out_key, notes_key in (("raid", "raid_outlook", "raid_notes"),
                                      ("mplus", "mplus_outlook", "mplus_notes")):
        tr = spec.setdefault(track, {})
        if ent[out_key] != "?":
            tr["outlook"] = ent[out_key]
        new_notes = [{"src": n["src"], "date": n["date"], "note": n["note"]}
                     for n in ent.get(notes_key) or []]
        if new_notes:
            tr["notes"] = new_notes + (tr.get("notes") or [])
    if ent.get("changes"):
        spec["changes"] = (spec.get("changes") or []) + [
            {"src": c["src"], "note": c["note"]} for c in ent["changes"]]
    spec["trend"] = ent["trend"]
    spec["as_of"] = ent["as_of"]
    spec["summary"] = ent["summary"]
    n_updated += 1

DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"병합 완료 — 스펙 {n_updated}개 갱신, 출처 {len(meta['sources'])}건, 일반노트 {len(general)}건")
