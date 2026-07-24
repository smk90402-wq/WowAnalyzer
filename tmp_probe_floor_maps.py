# 인스턴스 2912/2913의 UiMap 층 목록 + 각 UiMapAssignment 영역 크기
# → 살라다르 bbox(4039~4132, 351~452)를 담는 최소 영역 맵 찾기
from app.replay_map import _csv_rows, _to_int, _to_float

BBOX = (4039.0, 4132.8, 351.1, 452.3)   # (minX, maxX, minY, maxY)

for map_id in (2912, 2913):
    rows = [r for r in _csv_rows("UiMapAssignment", "MapID", map_id)
            if _to_int(r.get("MapID")) == map_id]
    print(f"=== MapID {map_id}: UiMapAssignment {len(rows)}건 ===")
    for r in rows:
        ui = _to_int(r.get("UiMapID"))
        reg = [_to_float(r.get(f"Region_{i}")) for i in range(6)]
        # Region: [minY?, minX?, minZ, maxY?, maxX?, maxZ] 순서 확인용 원본 출력
        area_w = abs(reg[3] - reg[0]); area_h = abs(reg[4] - reg[1])
        print(f"  UiMapID {ui} Order {r.get('OrderIndex')} Region {[round(v,1) for v in reg]} (≈{area_w:.0f}x{area_h:.0f})")
    # 이 UiMapID들의 이름
    uids = sorted({_to_int(r.get("UiMapID")) for r in rows})
    for uid in uids:
        urows = [r for r in _csv_rows("UiMap", "ID", uid) if _to_int(r.get("ID")) == uid]
        if urows:
            print(f"  UiMap {uid}: {urows[0].get('Name_lang')!r} Type={urows[0].get('Type')} Parent={urows[0].get('ParentUiMapID')}")
