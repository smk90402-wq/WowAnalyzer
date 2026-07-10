"""종족 대표 모델 → three.js용 JSON 메시 + PNG 텍스처 (리플레이 3D 유닛용).

사용:
  python fetch_race_models.py           # 플레이어블 전 종족×성별 (있는 건 skip) + manifest
  python fetch_race_models.py 1 0       # 단일 (race 1 인간, sex 0 남성)

⚠ 산출물(data/models/)은 게임 에셋 추출물 — git 커밋 금지(gitignore), R2 로만 동기화.

체인 (2026-07-11 실증):
  CreatureDisplayInfoExtra(DisplayRaceID, DisplaySexID, BakeMaterialResourcesID)
  → CreatureDisplayInfo(ExtendedDisplayInfoID) → ModelID
  → CreatureModelData → M2 FileDataID
  → TextureFileData(MaterialResourcesID=Bake…) → BLP FileDataID

M2 는 MD21 청크(내부는 레거시 MD20 헤더, 오프셋은 MD20 기준).
스킨(.skin)은 SFID 청크의 첫 fdid (LOD0).
지오셋: id==0(몸) 전부 + 그룹별 최소 id 1개, 단 헤어/수염(그룹 1~3)과 망토(15)는 제외.
출력: data/models/race_{race}_{sex}.json / .png
"""
from __future__ import annotations
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, ".")
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from app import replay_map as rm

MODELS = Path("data/models")
SKIP_GROUPS = {1, 2, 3, 15}  # 헤어·수염류(텍스처 별도라 오염), 망토


def fetch(fdid: int) -> bytes:
    MODELS.mkdir(parents=True, exist_ok=True)
    p = MODELS / f"fdid_{fdid}.bin"
    if p.exists() and p.stat().st_size > 0:
        return p.read_bytes()
    data = rm._get(f"{rm.WAGO}/api/casc/{fdid}")
    p.write_bytes(data)
    return data


def resolve(race: int, sex: int) -> tuple[int, int]:
    """(m2_fdid, bake_blp_fdid)"""
    extras = [r for r in rm._csv_rows("CreatureDisplayInfoExtra", "DisplayRaceID", race)
              if r.get("DisplayRaceID") == str(race) and r.get("DisplaySexID") == str(sex)
              and r.get("BakeMaterialResourcesID") not in (None, "", "0")]
    if not extras:
        raise RuntimeError(f"race {race} sex {sex}: bake extra 없음")
    last_err = None
    for ex in extras[:20]:
        try:
            cdis = [r for r in rm._csv_rows("CreatureDisplayInfo", "ExtendedDisplayInfoID", int(ex["ID"]))
                    if r.get("ExtendedDisplayInfoID") == ex["ID"]]
            if not cdis:
                continue
            model_id = int(cdis[0]["ModelID"])
            cmd = [r for r in rm._csv_rows("CreatureModelData", "ID", model_id)
                   if r.get("ID") == str(model_id)]
            m2_fdid = int(cmd[0]["FileDataID"])
            bake = ex["BakeMaterialResourcesID"]
            tfd = [r for r in rm._csv_rows("TextureFileData", "MaterialResourcesID", int(bake))
                   if r.get("MaterialResourcesID") == bake]
            blp_fdid = int(tfd[0]["FileDataID"])
            return m2_fdid, blp_fdid
        except Exception as e:  # 개별 extra 실패 → 다음 후보
            last_err = e
    raise RuntimeError(f"race {race} sex {sex}: 체인 실패 ({last_err})")


def find_chunk(data: bytes, magic: bytes) -> tuple[int, int]:
    off = 0
    while off + 8 <= len(data):
        m = data[off:off + 4]
        size = struct.unpack_from("<I", data, off + 4)[0]
        if m == magic:
            return off + 8, size
        off += 8 + size
    raise RuntimeError(f"청크 {magic!r} 없음")


def parse_m2(m2: bytes):
    base, _ = find_chunk(m2, b"12DM"[::-1] if False else b"MD21")
    hdr = m2[base:]
    if hdr[:4] != b"MD20":
        raise RuntimeError("MD20 아님")
    n_vert, ofs_vert = struct.unpack_from("<II", hdr, 0x3C)
    n_skin = struct.unpack_from("<I", hdr, 0x44)[0]
    verts = []
    for i in range(n_vert):
        o = ofs_vert + i * 48
        px, py, pz = struct.unpack_from("<3f", hdr, o)
        nx, ny, nz = struct.unpack_from("<3f", hdr, o + 20)
        u, v = struct.unpack_from("<2f", hdr, o + 32)
        verts.append((px, py, pz, nx, ny, nz, u, v))
    sfid_ofs, sfid_size = find_chunk(m2, b"SFID")
    skin_fdids = struct.unpack_from(f"<{sfid_size // 4}I", m2, sfid_ofs)
    return verts, n_skin, skin_fdids


def parse_skin(skin: bytes):
    if skin[:4] != b"SKIN":
        raise RuntimeError("SKIN 아님")
    def arr(ofs):
        return struct.unpack_from("<II", skin, ofs)
    n_v, o_v = arr(0x04)      # 로컬 → 글로벌 정점 인덱스 (u16)
    n_i, o_i = arr(0x0C)      # 삼각형 인덱스 (로컬, u16)
    n_sub, o_sub = arr(0x1C)  # 서브메시 48B
    local2global = struct.unpack_from(f"<{n_v}H", skin, o_v)
    tri_local = struct.unpack_from(f"<{n_i}H", skin, o_i)
    subs = []
    for i in range(n_sub):
        o = o_sub + i * 48
        sid, level, v_start, v_cnt, i_start, i_cnt = struct.unpack_from("<6H", skin, o)
        subs.append({"id": sid, "level": level,
                     "i_start": i_start + (level << 16), "i_cnt": i_cnt})
    return local2global, tri_local, subs


def pick_geosets(subs):
    keep = [s for s in subs if s["id"] == 0]
    groups: dict[int, dict] = {}
    for s in subs:
        if s["id"] == 0:
            continue
        g = s["id"] // 100
        if g in SKIP_GROUPS:
            continue
        if g not in groups or s["id"] < groups[g]["id"]:
            groups[g] = s
    keep.extend(groups.values())
    return keep


def build(race: int, sex: int, out_tag: str):
    m2_fdid, blp_fdid = resolve(race, sex)
    print(f"race {race} sex {sex}: m2={m2_fdid} blp={blp_fdid}")
    m2 = fetch(m2_fdid)
    verts, n_skin, skin_fdids = parse_m2(m2)
    print(f"  verts={len(verts)} skins={n_skin} fdids={skin_fdids[:4]}")
    skin = fetch(skin_fdids[0])
    l2g, tri, subs = parse_skin(skin)
    keep = pick_geosets(subs)
    print(f"  submeshes total={len(subs)} keep={len(keep)} ids={sorted(s['id'] for s in keep)[:20]}")
    # 삼각형 수집 (글로벌 정점 id) → 컴팩트 리인덱스
    used: dict[int, int] = {}
    positions, normals, uvs, indices = [], [], [], []
    for s in keep:
        for k in range(s["i_start"], s["i_start"] + s["i_cnt"]):
            g = l2g[tri[k]]
            if g not in used:
                used[g] = len(used)
                px, py, pz, nx, ny, nz, u, v = verts[g]
                positions += [round(px, 3), round(py, 3), round(pz, 3)]
                normals += [round(nx, 3), round(ny, 3), round(nz, 3)]
                uvs += [round(u, 4), round(v, 4)]
            indices.append(used[g])
    print(f"  out verts={len(used)} tris={len(indices)//3}")
    # BLP → PNG
    from PIL import Image
    import io
    blp = fetch(blp_fdid)
    img = Image.open(io.BytesIO(blp))
    img.save(MODELS / f"{out_tag}.png")
    print(f"  tex {img.size} -> {out_tag}.png")
    json.dump({"positions": positions, "normals": normals, "uvs": uvs,
               "indices": indices, "tex": f"{out_tag}.png"},
              open(MODELS / f"{out_tag}.json", "w"))
    kb = (MODELS / f"{out_tag}.json").stat().st_size // 1024
    print(f"  -> {out_tag}.json ({kb} KB)")


def playable_races() -> list[tuple[int, str]]:
    """ChrRaces 전체에서 PlayableRaceBit >= 0 인 (ID, 영문명)."""
    import csv as csvmod
    import io
    text = rm._get(f"{rm.WAGO}/db2/ChrRaces/csv", timeout=60).decode("utf-8-sig", "replace")
    out = []
    for r in csvmod.DictReader(io.StringIO(text)):
        try:
            if int(r.get("PlayableRaceBit") or -1) >= 0:
                out.append((int(r["ID"]), r.get("Name_lang", "")))
        except ValueError:
            pass
    return out


def build_all() -> None:
    import time
    races = playable_races()
    print(f"플레이어블 종족 {len(races)}개")
    manifest, fails = {}, []
    for rid, name in races:
        for sex in (0, 1):
            tag = f"race_{rid}_{sex}"
            if (MODELS / f"{tag}.json").exists():
                manifest[f"{rid}:{sex}"] = tag
                continue
            try:
                build(rid, sex, tag)
                manifest[f"{rid}:{sex}"] = tag
            except Exception as e:
                print(f"{tag} 실패 ({name}): {e}")
                fails.append((tag, name, str(e)))
            time.sleep(1.0)
    json.dump(manifest, open(MODELS / "manifest.json", "w", encoding="utf-8"))
    print(f"완료 {len(manifest)} / 실패 {len(fails)}")
    for t, n, e in fails:
        print("  -", t, n, e[:80])


if __name__ == "__main__":
    if len(sys.argv) > 1:
        race = int(sys.argv[1])
        sex = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        build(race, sex, f"race_{race}_{sex}")
    else:
        build_all()
