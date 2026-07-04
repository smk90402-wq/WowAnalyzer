"""instanceID(+전투 좌표 bbox) → 보스방 지형 높이 그리드.

wago.tools 체인 (REPLAY3D_TERRAIN_RESEARCH.md §1 — 이 PC에서 실증 완료):
  1) Map.db2 CSV : instanceID(ENCOUNTER_START 5번째 필드) → WdtFileDataID
  2) WDT MAID    : 타일(col,row)별 rootADT FileDataID (엔트리 32B = uint32×8)
  3) rootADT     : MCNK×256 → MCVT(145 float) 높이 → 월드좌표 정점
  4) 전투 bbox + 20% 마진 구간을 ~4.17yd 그리드로 바이리니어 샘플링

출력 포맷 (API 계약):
  {"grid_w","grid_h","world_rect":{minX,minY,maxX,maxY},"heights":[...]}
  heights 는 행우선 float(yd) — heights[row*grid_w + col],
  row: X = minX→maxX (grid_h 행), col: Y = minY→maxY (grid_w 열).
  지형이 없는 칸(구멍/타일 밖)은 null.

캐시: data/maps/terrain_{instanceID}_{bbox해시}.json
      + 받은 원본(WDT/ADT)은 data/maps/fdid_{fdid}.bin 으로 재사용.
실패는 replay_map 과 같은 패턴의 네거티브 캐시 (10분 TTL).

주의 (연구 문서 실측):
  - wago.tools 는 파이썬 기본 UA 를 403 차단 → replay_map._get(UA 헤더) 재사용.
  - 미드나잇 신규 청크(MPY2 등)가 있어도 "모르는 청크는 스킵" 이라 영향 없음.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import time
from typing import Any, Iterator

from app import replay_map
from app.replay_map import MapError

MAPS_DIR = replay_map.MAPS_DIR

TILE_SIZE = 533.33333          # ADT 타일 한 변 (yd)
CHUNK_SIZE = TILE_SIZE / 16    # MCNK 한 변 (33.33yd)
UNIT = CHUNK_SIZE / 8          # MCVT 외곽 정점 간격 (4.1667yd)
MAX_ORIGIN = 32 * TILE_SIZE    # 월드 좌표 원점 오프셋 (17066.667)

MARGIN = 0.2                   # bbox 각 변 마진 비율 (긴 변 기준)
MIN_PAD = 10.0                 # 마진 최소값 (yd) — 제자리 전투 대비
MAX_GRID = 128                 # 한 축 최대 샘플 수 (~128×128 이하 계약)

# 실패 네거티브 캐시 (replay_map 과 동일 패턴): key → (실패 시각, 사유)
_FAIL_TTL_S = 600
_fail_cache: dict[str, tuple[float, str]] = {}


class TerrainError(MapError):
    """지형 그리드를 만들 수 없는 이유 — 404 사유로 그대로 노출."""


def _chunks(data: bytes, start: int = 0, end: int | None = None) -> Iterator[tuple[str, int, int]]:
    """IFF 청크 순회 → (매직 4글자, 본문 오프셋, 본문 크기). 모르는 청크는 호출부가 스킵."""
    off = start
    stop = len(data) if end is None else end
    while off + 8 <= stop:
        magic = data[off:off + 4][::-1].decode("ascii", "replace")
        size = struct.unpack_from("<I", data, off + 4)[0]
        yield magic, off + 8, size
        off += 8 + size


def _fetch_fdid(fdid: int) -> bytes:
    """wago.tools casc 파일 다운로드 + fdid_*.bin 디스크 캐시 (같은 타일 재다운 방지)."""
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    path = MAPS_DIR / f"fdid_{fdid}.bin"
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    data = replay_map._get(f"{replay_map.WAGO}/api/casc/{fdid}")
    path.write_bytes(data)
    return data


def _wdt_fdid(instance_id: int) -> int:
    """Map.db2 에서 instanceID 행의 WdtFileDataID. (filter 는 부분일치라 재필터)"""
    rows = [r for r in replay_map._csv_rows("Map", "ID", instance_id)
            if replay_map._to_int(r.get("ID")) == instance_id]
    if not rows:
        raise TerrainError(f"Map.db2 에 instanceID {instance_id} 없음")
    fdid = replay_map._to_int(rows[0].get("WdtFileDataID"))
    if not fdid:
        raise TerrainError(f"instanceID {instance_id} 의 WdtFileDataID 가 0")
    return fdid


def _maid_root_fdid(wdt: bytes, col: int, row: int) -> int:
    """WDT MAID 에서 타일(col,row)의 rootADT fdid. 타일에 지형 없으면 0."""
    for magic, off, size in _chunks(wdt):
        if magic != "MAID":
            continue
        entry = size // 4096   # 실측 32B (root,obj0,obj1,tex0,lod,mapTex,mapTexN,minimap)
        if entry < 4:
            raise TerrainError(f"WDT MAID 엔트리 크기 이상: {entry}B")
        return struct.unpack_from("<I", wdt, off + (row * 64 + col) * entry)[0]
    raise TerrainError("WDT 에 MAID 청크 없음 — 지형 fdid 를 찾을 수 없음")


def _parse_root_adt(data: bytes,
                    chunk_map: dict[tuple[int, int], tuple[float, float, float, tuple]]) -> int:
    """rootADT 의 MCNK/MCVT 를 전역 청크 사전에 적재. 반환: 적재한 청크 수.

    MCNK 헤더 0x68 의 (posx,posy,posz) 가 청크 북서(최대 X/Y) 모서리 월드좌표.
    전역 키 = 모서리 좌표를 청크 단위로 나눈 정수 인덱스 (타일 경계 무관하게 유일).
    """
    n = 0
    for magic, off, size in _chunks(data):
        if magic != "MCNK" or size < 128:
            continue
        posx, posy, posz = struct.unpack_from("<3f", data, off + 0x68)
        heights: tuple | None = None
        for smagic, soff, ssize in _chunks(data, off + 128, off + size):
            if smagic == "MCVT" and ssize >= 145 * 4:
                heights = struct.unpack_from("<145f", data, soff)
                break
        if heights is None:
            continue
        key = (round((MAX_ORIGIN - posx) / CHUNK_SIZE),
               round((MAX_ORIGIN - posy) / CHUNK_SIZE))
        chunk_map[key] = (posx, posy, posz, heights)
        n += 1
    return n


def sample_height(chunk_map: dict[tuple[int, int], tuple[float, float, float, tuple]],
                  x: float, y: float) -> float | None:
    """월드 (x,y)의 지형 표면 높이 — MCVT 외곽 9×9 정점 바이리니어 보간.

    MCVT 145 float = 외곽 9행(각 9개) + 내부 8행(각 8개) 인터리브,
    외곽 행 i 의 시작 인덱스 = i*17. 정점 (i,j) 월드좌표:
      wx = posx − i*4.1667 (북→남), wy = posy − j*4.1667 (서→동).
    """
    kx = math.floor((MAX_ORIGIN - x) / CHUNK_SIZE)
    ky = math.floor((MAX_ORIGIN - y) / CHUNK_SIZE)
    chunk = chunk_map.get((kx, ky))
    if chunk is None:
        return None
    posx, posy, posz, hs = chunk
    fi = min(max((posx - x) / UNIT, 0.0), 8.0)
    fj = min(max((posy - y) / UNIT, 0.0), 8.0)
    i0 = min(int(fi), 7)
    j0 = min(int(fj), 7)
    di = fi - i0
    dj = fj - j0
    h00 = hs[i0 * 17 + j0]
    h01 = hs[i0 * 17 + j0 + 1]
    h10 = hs[(i0 + 1) * 17 + j0]
    h11 = hs[(i0 + 1) * 17 + j0 + 1]
    top = h00 * (1 - dj) + h01 * dj
    bot = h10 * (1 - dj) + h11 * dj
    return posz + top * (1 - di) + bot * di


def _load_chunks(instance_id: int, rect: tuple[float, float, float, float],
                 ) -> dict[tuple[int, int], tuple[float, float, float, tuple]]:
    """rect 를 덮는 타일들의 MCNK 높이 데이터를 전역 사전으로."""
    min_x, max_x, min_y, max_y = rect
    wdt = _fetch_fdid(_wdt_fdid(instance_id))
    # 타일 공식 (연구 문서 §1-4): col = floor(32 − y/533.33), row = floor(32 − x/533.33)
    col_lo = math.floor(32 - max_y / TILE_SIZE)
    col_hi = math.floor(32 - min_y / TILE_SIZE)
    row_lo = math.floor(32 - max_x / TILE_SIZE)
    row_hi = math.floor(32 - min_x / TILE_SIZE)
    chunk_map: dict[tuple[int, int], tuple[float, float, float, tuple]] = {}
    loaded = 0
    for row in range(row_lo, row_hi + 1):
        for col in range(col_lo, col_hi + 1):
            if not (0 <= row < 64 and 0 <= col < 64):
                continue
            fdid = _maid_root_fdid(wdt, col, row)
            if not fdid:
                continue  # 이 타일엔 지형 없음
            loaded += _parse_root_adt(_fetch_fdid(fdid), chunk_map)
    if not loaded:
        raise TerrainError(
            f"instanceID {instance_id} 의 전투 구역 타일(row {row_lo}..{row_hi}, "
            f"col {col_lo}..{col_hi})에 지형(ADT) 없음 — WMO 전용 맵일 수 있음")
    return chunk_map


def _build_grid(instance_id: int, rect: tuple[int, int, int, int]) -> dict[str, Any]:
    """rect(정수 yd) 구간 높이 그리드 생성 — 해상도 ~4.17yd, 한 축 최대 128."""
    min_x, max_x, min_y, max_y = rect
    chunk_map = _load_chunks(instance_id, rect)

    def axis_n(span: float) -> int:
        return max(2, min(MAX_GRID, int(math.ceil(span / UNIT)) + 1))

    grid_h = axis_n(max_x - min_x)   # 행 = X 축
    grid_w = axis_n(max_y - min_y)   # 열 = Y 축
    heights: list[float | None] = []
    holes = 0
    for r in range(grid_h):
        x = min_x + (max_x - min_x) * r / (grid_h - 1)
        for c in range(grid_w):
            y = min_y + (max_y - min_y) * c / (grid_w - 1)
            h = sample_height(chunk_map, x, y)
            if h is None:
                holes += 1
                heights.append(None)
            else:
                heights.append(round(h, 2))
    if holes == grid_w * grid_h:
        raise TerrainError("bbox 구간 전체가 지형 구멍 — 높이 그리드 생성 실패")
    return {
        "grid_w": grid_w,
        "grid_h": grid_h,
        "world_rect": {"minX": min_x, "minY": min_y, "maxX": max_x, "maxY": max_y},
        "heights": heights,
    }


def terrain_grid(instance_id: int, bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    """캐시 우선 진입점. bbox = (min_x, max_x, min_y, max_y) — frames 플레이어 좌표 기준.

    bbox 에 20% 마진(최소 10yd)을 붙이고 1yd 정수로 스냅 — 풀마다 bbox 가
    미세하게 달라도 캐시 키가 흔들리지 않게 하려는 목적.
    """
    if not instance_id:
        raise TerrainError("instanceID 없음 (ENCOUNTER_START 5번째 필드)")
    min_x, max_x, min_y, max_y = bbox
    if max_x < min_x or max_y < min_y:
        raise TerrainError(f"bbox 이상: {bbox}")
    pad = max(MIN_PAD, (max_x - min_x) * MARGIN, (max_y - min_y) * MARGIN)
    rect = (math.floor(min_x - pad), math.ceil(max_x + pad),
            math.floor(min_y - pad), math.ceil(max_y + pad))
    key = hashlib.sha1(("%d_%d_%d_%d" % rect).encode()).hexdigest()[:10]

    cache_path = MAPS_DIR / f"terrain_{instance_id}_{key}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass  # 캐시 손상 → 다시 빌드

    fail_key = f"{instance_id}_{key}"
    failed = _fail_cache.get(fail_key)
    if failed and time.monotonic() - failed[0] < _FAIL_TTL_S:
        raise TerrainError(f"최근 실패 캐시(10분): {failed[1]}")
    try:
        grid = _build_grid(instance_id, rect)
    except MapError as exc:
        _fail_cache[fail_key] = (time.monotonic(), str(exc))
        raise
    _fail_cache.pop(fail_key, None)

    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(grid, ensure_ascii=False), encoding="utf-8")
    return grid
