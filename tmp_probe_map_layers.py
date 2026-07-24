# 르우라(2534)·우주의 왕관 등 지도의 고해상도 레이어 존재 여부 프로브
from app.replay_map import _csv_rows, _to_int

for ui_map_id in (2534, 2532, 2530, 2529):
    xrows = [r for r in _csv_rows("UiMapXMapArt", "UiMapID", ui_map_id)
             if _to_int(r.get("UiMapID")) == ui_map_id]
    if not xrows:
        print(ui_map_id, "no art")
        continue
    xrows.sort(key=lambda r: _to_int(r.get("PhaseID")))
    art_id = _to_int(xrows[0].get("UiMapArtID"))
    trows = [r for r in _csv_rows("UiMapArtTile", "UiMapArtID", art_id)
             if _to_int(r.get("UiMapArtID")) == art_id]
    layers = {}
    for r in trows:
        li = _to_int(r.get("LayerIndex"))
        layers.setdefault(li, []).append((_to_int(r.get("RowIndex")), _to_int(r.get("ColIndex"))))
    print(f"uiMap {ui_map_id} art {art_id}:")
    for li, tl in sorted(layers.items()):
        rows_ = max(r for r, _ in tl) + 1
        cols = max(c for _, c in tl) + 1
        print(f"  Layer {li}: {len(tl)}타일 ({rows_}x{cols} 격자 = {cols*256}x{rows_*256}px 근사)")
    # 스타일 레이어 치수
    art_rows = [r for r in _csv_rows("UiMapArt", "ID", art_id)
                if _to_int(r.get("ID")) == art_id]
    style_id = _to_int(art_rows[0].get("UiMapArtStyleID")) if art_rows else 0
    lrows = [r for r in _csv_rows("UiMapArtStyleLayer", "UiMapArtStyleID", style_id)
             if _to_int(r.get("UiMapArtStyleID")) == style_id]
    for r in sorted(lrows, key=lambda x: _to_int(x.get("LayerIndex"))):
        print(f"  StyleLayer {_to_int(r.get('LayerIndex'))}: {r.get('LayerWidth')}x{r.get('LayerHeight')} tile {r.get('TileWidth')}x{r.get('TileHeight')} MinScale={r.get('MinScale')} MaxScale={r.get('MaxScale')}")
