"""uiMapID → 맵 이미지 + 월드좌표→픽셀 변환 계수.

wago.tools 체인 (REPLAY3D_PLAN.md §3 검증 완료):
  1) UiMapXMapArt   : uiMapID → UiMapArtID
  2) UiMapArtTile   : UiMapArtID → 타일 격자 (FileDataID)
  3) UiMapArt/UiMapArtStyleLayer : 최종 크롭 크기 (예: 1002×668)
  4) api/casc/{fdid}: BLP 타일 바이너리 (Pillow 가 BLP 네이티브 지원)
  5) UiMapAssignment: 월드좌표 Region 박스 → world_to_px 계수

캐시: data/maps/{uiMapID}.png + {uiMapID}.json (있으면 인터넷 없이 재사용).
주의: wago.tools 의 filter 는 부분일치(fuzzy)라 응답 행을 반드시 다시 걸러야 함.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

# main.py 와 같은 규칙 — exe 로 얼리면 exe 옆 data/, 개발 중엔 저장소 data/
if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).parent / "data"
else:
    DATA_DIR = Path(__file__).parent.parent / "data"
MAPS_DIR = DATA_DIR / "maps"

WAGO = "https://wago.tools"
_HEADERS = {"User-Agent": "LogAnalyze/1.0 (local replay map fetch)"}

# 실패 네거티브 캐시: uiMapID → (실패 시각 monotonic, 사유).
# 한 번 실패한 맵은 TTL 동안 wago 체인 재시도 없이 즉시 MapError.
_FAIL_TTL_S = 600
_fail_cache: dict[int, tuple[float, str]] = {}


class MapError(RuntimeError):
    """맵을 만들 수 없는 이유를 담아서 404 사유로 그대로 노출."""


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get(url: str, timeout: int = 60) -> bytes:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise MapError(f"wago.tools 접속 실패({type(exc).__name__}): {url}")
    if resp.status_code != 200:
        raise MapError(f"wago.tools HTTP {resp.status_code}: {url}")
    return resp.content


def _csv_rows(table: str, filter_field: str, filter_value: int) -> list[dict[str, str]]:
    """db2 CSV 를 받아 dict 행으로. filter 가 부분일치라 호출부에서 재필터 필수."""
    url = f"{WAGO}/db2/{table}/csv?filter[{filter_field}]={filter_value}"
    text = _get(url, timeout=30).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _layer_dims(art_id: int) -> tuple[int, int, int, int]:
    """UiMapArt → UiMapArtStyleLayer 로 최종 크기/타일 크기. 실패하면 표준값."""
    try:
        art_rows = [r for r in _csv_rows("UiMapArt", "ID", art_id)
                    if _to_int(r.get("ID")) == art_id]
        style_id = _to_int(art_rows[0].get("UiMapArtStyleID")) if art_rows else 0
        layer_rows = [r for r in _csv_rows("UiMapArtStyleLayer", "UiMapArtStyleID", style_id)
                      if _to_int(r.get("UiMapArtStyleID")) == style_id
                      and _to_int(r.get("LayerIndex")) == 0]
        if layer_rows:
            row = layer_rows[0]
            return (
                _to_int(row.get("LayerWidth"), 1002),
                _to_int(row.get("LayerHeight"), 668),
                _to_int(row.get("TileWidth"), 256),
                _to_int(row.get("TileHeight"), 256),
            )
    except MapError:
        pass
    # 던전/레이드 지도의 사실상 표준 크기
    return 1002, 668, 256, 256


def _build_map(ui_map_id: int) -> dict[str, Any]:
    """wago.tools 체인 전부 수행 → PNG 스티칭 + 메타 json 저장."""
    from PIL import Image  # 지연 import — 서버 기동 시 필수 의존 아님

    MAPS_DIR.mkdir(parents=True, exist_ok=True)

    # 1) uiMapID → UiMapArtID (PhaseID 0 우선)
    xrows = [r for r in _csv_rows("UiMapXMapArt", "UiMapID", ui_map_id)
             if _to_int(r.get("UiMapID")) == ui_map_id]
    if not xrows:
        raise MapError(f"UiMapXMapArt 에 uiMapID {ui_map_id} 없음")
    xrows.sort(key=lambda r: _to_int(r.get("PhaseID")))
    art_id = _to_int(xrows[0].get("UiMapArtID"))

    # 2) 타일 격자 (LayerIndex 최소 = 기본 줌 레벨)
    trows = [r for r in _csv_rows("UiMapArtTile", "UiMapArtID", art_id)
             if _to_int(r.get("UiMapArtID")) == art_id]
    if not trows:
        raise MapError(f"UiMapArtTile 에 UiMapArtID {art_id} 타일 없음")
    base_layer = min(_to_int(r.get("LayerIndex")) for r in trows)
    tiles = {(_to_int(r.get("RowIndex")), _to_int(r.get("ColIndex"))): _to_int(r.get("FileDataID"))
             for r in trows if _to_int(r.get("LayerIndex")) == base_layer}

    # 3) 최종 크롭 크기
    layer_w, layer_h, tile_w, tile_h = _layer_dims(art_id)

    # 4) 타일 다운로드 + 스티칭 + 크롭
    n_rows = max(r for r, _ in tiles) + 1
    n_cols = max(c for _, c in tiles) + 1
    canvas = Image.new("RGB", (n_cols * tile_w, n_rows * tile_h), (0, 0, 0))
    for (row, col), fdid in sorted(tiles.items()):
        blp = _get(f"{WAGO}/api/casc/{fdid}")
        tile = Image.open(io.BytesIO(blp)).convert("RGB")
        canvas.paste(tile, (col * tile_w, row * tile_h))
    canvas = canvas.crop((0, 0, min(layer_w, canvas.width), min(layer_h, canvas.height)))

    # 5) 월드좌표 Region (OrderIndex 최소 행 하나면 충분 — 플랜 §3-2)
    arows = [r for r in _csv_rows("UiMapAssignment", "UiMapID", ui_map_id)
             if _to_int(r.get("UiMapID")) == ui_map_id]
    if not arows:
        raise MapError(f"UiMapAssignment 에 uiMapID {ui_map_id} 없음")
    arows.sort(key=lambda r: _to_int(r.get("OrderIndex")))
    a = arows[0]
    region = [_to_float(a.get(f"Region_{i}")) for i in range(6)]
    ui_min = [_to_float(a.get("UiMin_0")), _to_float(a.get("UiMin_1"))]
    ui_max = [_to_float(a.get("UiMax_0"), 1.0), _to_float(a.get("UiMax_1"), 1.0)]

    png_path = MAPS_DIR / f"{ui_map_id}.png"
    canvas.save(png_path, format="PNG")
    meta = {
        "ui_map_id": ui_map_id,
        "px_w": canvas.width,
        "px_h": canvas.height,
        "region": region,          # UiMapAssignment Region_0..5 원본 그대로
        "ui_min": ui_min,
        "ui_max": ui_max,
        # wago.tools 응답에서 쓴 값들 (재현/디버그용 캐시)
        "wago": {"art_id": art_id, "layer": base_layer,
                 "tiles": {f"{r},{c}": f for (r, c), f in sorted(tiles.items())},
                 "layer_dims": [layer_w, layer_h, tile_w, tile_h]},
    }
    (MAPS_DIR / f"{ui_map_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def map_meta(ui_map_id: int) -> dict[str, Any]:
    """캐시 우선 — png+json 둘 다 있으면 인터넷 없이 반환."""
    png_path = MAPS_DIR / f"{ui_map_id}.png"
    json_path = MAPS_DIR / f"{ui_map_id}.json"
    if png_path.exists() and json_path.exists():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            pass  # 캐시 손상 → 다시 빌드
    # 최근 실패한 맵이면 즉시 실패 (wago 체인 재시도 안 함)
    failed = _fail_cache.get(ui_map_id)
    if failed and time.monotonic() - failed[0] < _FAIL_TTL_S:
        raise MapError(f"최근 실패 캐시(10분): {failed[1]}")
    try:
        meta = _build_map(ui_map_id)
    except MapError as exc:
        _fail_cache[ui_map_id] = (time.monotonic(), str(exc))
        raise
    _fail_cache.pop(ui_map_id, None)  # 성공하면 실패 기록 제거
    return meta


def map_png_path(ui_map_id: int) -> Path:
    map_meta(ui_map_id)  # 없으면 빌드
    png_path = MAPS_DIR / f"{ui_map_id}.png"
    if not png_path.exists():
        raise MapError(f"맵 PNG 생성 실패: {ui_map_id}")
    return png_path


def world_to_px(meta: dict[str, Any], samples: list[tuple[float, float]] | None = None) -> dict[str, float]:
    """월드좌표→픽셀 1차 계수. px_x = a*wx + b*wy + c, px_y = d*wx + e*wy + f.

    좌표계 (플랜 §2-2): +X=북(지도 위), +Y=서(지도 왼쪽).
    Region_0..5 의 X/Y 라벨이 뒤집혀 기록된 맵이 있어(위키 전통),
    두 축 배치 후보를 실제 샘플 좌표로 검증해 맞는 쪽을 고른다.
    """
    region = meta["region"]
    w, h = float(meta["px_w"]), float(meta["px_h"])
    ui_min = meta.get("ui_min") or [0.0, 0.0]
    ui_max = meta.get("ui_max") or [1.0, 1.0]

    def coeffs(min_x: float, max_x: float, min_y: float, max_y: float) -> dict[str, float]:
        # 가로: u = (max_y - wy)/(max_y - min_y) → px_x = (ui_min0 + u*(ui_max0-ui_min0)) * w
        span_u = (ui_max[0] - ui_min[0]) * w
        b = -span_u / (max_y - min_y)
        c = ui_min[0] * w + span_u * max_y / (max_y - min_y)
        # 세로: v = (max_x - wx)/(max_x - min_x) → px_y = (ui_min1 + v*(ui_max1-ui_min1)) * h
        span_v = (ui_max[1] - ui_min[1]) * h
        d = -span_v / (max_x - min_x)
        f = ui_min[1] * h + span_v * max_x / (max_x - min_x)
        return {"a": 0.0, "b": b, "c": c, "d": d, "e": 0.0, "f": f}

    # 후보 A: Region_0/3 = 월드X(북) 범위, Region_1/4 = 월드Y(서) 범위 (라벨 그대로)
    # 후보 B: 라벨 뒤집힘 (X↔Y 스왑)
    cand_a = (region[0], region[3], region[1], region[4])
    cand_b = (region[1], region[4], region[0], region[3])

    def degenerate(cand: tuple[float, float, float, float]) -> bool:
        """Region 스팬이 0 이면 계수를 만들 수 없음 (0 나누기)."""
        min_x, max_x, min_y, max_y = cand
        return max_x == min_x or max_y == min_y

    valid = [c for c in (cand_a, cand_b) if not degenerate(c)]
    if not valid:
        # 두 후보 모두 퇴화 — ZeroDivisionError 대신 명시적으로 실패
        raise MapError(f"UiMapAssignment Region 퇴화(스팬 0): {region}")
    if len(valid) == 1:
        return coeffs(*valid[0])

    def score(cand: tuple[float, float, float, float]) -> float:
        """샘플이 맵 픽셀 박스 안에 들어오는 비율 (5% 여유). 샘플 없으면 종횡비로 판정."""
        min_x, max_x, min_y, max_y = cand
        if samples:
            k = coeffs(min_x, max_x, min_y, max_y)
            inside = 0
            for wx, wy in samples:
                px = k["a"] * wx + k["b"] * wy + k["c"]
                py = k["d"] * wx + k["e"] * wy + k["f"]
                if -0.05 * w <= px <= 1.05 * w and -0.05 * h <= py <= 1.05 * h:
                    inside += 1
            return inside / len(samples)
        # 샘플이 없으면: Y스팬/X스팬 비율이 픽셀 종횡비(w/h)와 가까운 쪽
        ratio = abs((max_y - min_y) / (max_x - min_x))
        return -abs(ratio - w / h)

    def spread_penalty(cand: tuple[float, float, float, float]) -> float:
        """동점 타이브레이크: 궤적을 픽셀로 옮겨 가로/세로 퍼짐 비율이
        맵 픽셀 비율(w/h)에 얼마나 가까운지 (작을수록 좋음)."""
        k = coeffs(*cand)
        pxs = [k["a"] * wx + k["b"] * wy + k["c"] for wx, wy in samples]
        pys = [k["d"] * wx + k["e"] * wy + k["f"] for wx, wy in samples]
        sx = max(pxs) - min(pxs)
        sy = max(pys) - min(pys)
        if sx <= 0 or sy <= 0:
            return float("inf")  # 한 축으로만 움직임 → 판정 불가
        return abs(sx / sy - w / h)

    sa, sb = score(cand_a), score(cand_b)
    if sa > sb:
        chosen = cand_a
    elif sb > sa:
        chosen = cand_b
    elif samples:
        # 점수 동점 → 퍼짐 비율이 맵 비율에 더 가까운 쪽
        chosen = cand_a if spread_penalty(cand_a) <= spread_penalty(cand_b) else cand_b
    else:
        chosen = cand_a
    return coeffs(*chosen)
