"""KR 막공 취업 시장 페치 — 사용자 교정 반영: "많이 보임 ≠ TO".

징벌 사례: 정공마다 팔라딘 1자리 고정 × 징기 인구 폭발 → 고유공대 수는 높지만
실제 취업(TO 뚫기)은 최악. → 공급(지원자 풀) 대비 수요(자리수)로 재측정.

데이터 3종 (전부 KR 서버 = 인벤 막공과 같은 시장):
 1. 신화 KR 전수 랭킹: 27스펙 × 9보스, 페이지 끝까지 (KR은 스펙당 ≤400이라 캡 없음)
    → 유니크 캐릭 = "신화 자리를 실제로 얻은 사람" (수요 실현치)
 2. 영웅 KR 인구: 우주의왕관(3181)+살라다르(3179), 캡 직전(~1900)이라 전수 가능
    → 유니크 캐릭 = 지원자 풀 (사용자: "영웅은 아무나 데려가거든" = 공급)
 3. 신화 공대 로스터: 유니크 (report,fight) 전부 playerDetails (combatantInfo 없이 = 경량)
    → 공대당 스펙별 자리수(TO), 팔라딘 총수(탱힐 포함 — 1팔라 룰 검증), 길드/무길드(막공 프록시)

출력: data/kr_mythic_rankings.json, data/kr_heroic_pop.json,
      data/v2_cache_kr_roster.json(재개가능 캐시), data/kr_pug_market.json(분석 통합)
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from wcl_v2 import WCLV2

DATA = Path(__file__).parent / "data"
PT = 3          # 12.0.7
MAXPAGE = 20    # WCL 하드캡

BOSSES_MYTHIC = [3176, 3177, 3179, 3178, 3180, 3181, 3306, 3182, 3183]
BOSS_KR = {3176: "아베르지안", 3177: "보라시우스", 3179: "살라다르", 3178: "바엘고어",
           3180: "빛눈먼 선봉대", 3181: "우주의 왕관", 3306: "키마이루스", 3182: "벨로렌",
           3183: "한밤의 종막"}
BOSSES_HEROIC = [3181, 3179]   # 캡 직전 확인됨 (~1900) — 첫넴은 2000+ 캡이라 제외

SPECS = [
    ("Mage", "Frost"), ("Mage", "Fire"), ("Mage", "Arcane"),
    ("Hunter", "BeastMastery"), ("Hunter", "Marksmanship"), ("Hunter", "Survival"),
    ("DemonHunter", "Devourer"), ("DemonHunter", "Havoc"),
    ("Warlock", "Demonology"), ("Warlock", "Destruction"), ("Warlock", "Affliction"),
    ("Priest", "Shadow"), ("Druid", "Balance"), ("Druid", "Feral"),
    ("Evoker", "Devastation"), ("Evoker", "Augmentation"),
    ("DeathKnight", "Unholy"), ("DeathKnight", "Frost"),
    ("Shaman", "Elemental"), ("Shaman", "Enhancement"),
    ("Monk", "Windwalker"),
    ("Rogue", "Assassination"), ("Rogue", "Outlaw"), ("Rogue", "Subtlety"),
    ("Paladin", "Retribution"), ("Warrior", "Arms"), ("Warrior", "Fury"),
]

Q_RANK = """query($e:Int!,$d:Int!,$p:Int!,$cn:String!,$sn:String!){worldData{encounter(id:$e){
  characterRankings(metric:dps,className:$cn,specName:$sn,difficulty:$d,partition:%d,page:$p,serverRegion:"KR")}}}""" % PT

# 로스터 — combatantInfo 없이 (경량). guild 는 report 레벨.
Q_ROSTER = """query($code:String!,$fid:[Int]!){reportData{report(code:$code){
  guild{name}
  playerDetails(fightIDs:$fid)
}}}"""


def save_json(path: Path, obj) -> None:
    payload = json.dumps(obj, ensure_ascii=False)
    tmp = path.with_name(f"{path.name}.tmp")
    last_exc = None
    for _ in range(5):
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(0.5)
    if last_exc:
        raise last_exc


def fetch_rank_page(cli, eid, cn, sn, diff, page):
    d = cli.query(Q_RANK, {"e": eid, "d": diff, "p": page, "cn": cn, "sn": sn})
    o = (((d or {}).get("worldData") or {}).get("encounter") or {}).get("characterRankings") or {}
    return bool(o.get("hasMorePages")), o.get("rankings") or []


def fetch_all_pages(cli, eid, cn, sn, diff):
    """페이지 전부. (entries, capped)"""
    out = []
    for p in range(1, MAXPAGE + 1):
        for attempt in range(5):
            try:
                more, rk = fetch_rank_page(cli, eid, cn, sn, diff, p)
                break
            except Exception as ex:
                wait = 30 * (attempt + 1)
                print(f"    재시도 {attempt+1} ({str(ex)[:60]}) — {wait}s 대기", flush=True)
                time.sleep(wait)
        else:
            raise RuntimeError(f"{cn}/{sn} boss{eid} p{p} 5회 실패")
        out.extend(rk)
        time.sleep(0.03)
        if not more:
            return out, False
    return out, True   # MAXPAGE 까지 more=True → 캡


def compact(e, eid):
    rep = e.get("report") or {}
    srv = e.get("server") or {}
    g = e.get("guild")
    return {
        "name": e.get("name"), "server": srv.get("name"),
        "class": e.get("class"), "spec": e.get("spec"), "boss": eid,
        "amount": round(e.get("amount") or 0),
        "guild": (g.get("name") if isinstance(g, dict) else None),
        "rid": rep.get("code"), "fid": rep.get("fightID"),
    }


def step1_mythic(cli):
    path = DATA / "kr_mythic_rankings.json"
    done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if done.get("_partition") != PT:
        done = {"_partition": PT}
    for eid in BOSSES_MYTHIC:
        for cn, sn in SPECS:
            key = f"{eid}|{cn}|{sn}"
            if key in done:
                continue
            entries, capped = fetch_all_pages(cli, eid, cn, sn, 5)
            done[key] = {"entries": [compact(e, eid) for e in entries], "capped": capped}
            save_json(path, done)
        n = sum(len(v["entries"]) for k, v in done.items() if k.startswith(f"{eid}|"))
        print(f"신화 {BOSS_KR[eid]}: 누적 {n}명", flush=True)
    return done


def step2_heroic(cli):
    path = DATA / "kr_heroic_pop.json"
    done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if done.get("_partition") != PT:
        done = {"_partition": PT}
    for eid in BOSSES_HEROIC:
        for cn, sn in SPECS:
            key = f"{eid}|{cn}|{sn}"
            if key in done:
                continue
            entries, capped = fetch_all_pages(cli, eid, cn, sn, 4)
            # 인구만 필요 — 유니크 (name,server) + 캡 여부
            chars = sorted({f'{e.get("name")}@{(e.get("server") or {}).get("name")}' for e in entries})
            done[key] = {"n": len(chars), "chars": chars, "capped": capped}
            save_json(path, done)
            print(f"영웅 {BOSS_KR[eid]} {sn}: {len(chars)}명{' [캡!]' if capped else ''}", flush=True)
    return done


SAMPLE_PER_BOSS = 150   # KR 신화가 예상보다 큼 (첫넴만 ~2만 엔트리) — 전수는 포인트 초과.
                        # TO 평균엔 보스당 150 로스터면 SE~0.06 자리 — 충분.


def step3_rosters(cli, mythic):
    cache_p = DATA / "v2_cache_kr_roster.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else {}
    by_boss: dict[int, set] = {}
    for key, blk in mythic.items():
        if str(key).startswith("_"):
            continue
        for e in blk["entries"]:
            if e["rid"] and e["fid"]:
                by_boss.setdefault(e["boss"], set()).add((e["rid"], e["fid"]))
    # 보스당 결정적 샘플 (정렬 후 균등 간격 — 재실행해도 같은 표본 = 캐시 재개)
    todo = []
    for boss, fset in sorted(by_boss.items()):
        fl = sorted(fset)
        if len(fl) > SAMPLE_PER_BOSS:
            step = len(fl) / SAMPLE_PER_BOSS
            fl = [fl[int(i * step)] for i in range(SAMPLE_PER_BOSS)]
        todo += [(r, f, boss) for r, f in fl]
        print(f"로스터 표본 {BOSS_KR[boss]}: {len(fl)}/{len(fset)}", flush=True)
    todo = [(r, f, b) for r, f, b in todo if f"{r}:{f}" not in cache]
    print(f"로스터 신규 페치: {len(todo)}", flush=True)
    for i, (rid, fid, boss) in enumerate(todo):
        for attempt in range(5):
            try:
                d = cli.query(Q_ROSTER, {"code": rid, "fid": [int(fid)]})
                rep = (((d or {}).get("reportData") or {}).get("report") or {})
                pd_ = rep.get("playerDetails") or {}
                actual = pd_.get("data", {}).get("playerDetails") if isinstance(pd_, dict) and "data" in pd_ else pd_
                roster = {"boss": boss, "guild": (rep.get("guild") or {}).get("name")}
                for role in ("dps", "healers", "tanks"):
                    players = (actual.get(role) or []) if isinstance(actual, dict) else []
                    roster[role] = [{
                        "name": p.get("name"), "class": p.get("type"),
                        "spec": ((p.get("specs") or [{}])[0].get("spec") if p.get("specs") else None),
                    } for p in players]
                cache[f"{rid}:{fid}"] = roster
                break
            except Exception as ex:
                wait = 60 * (attempt + 1)   # 429 = 한도 — 기다려서 통과 (rate limit 정책)
                print(f"  로스터 재시도 {attempt+1} {rid}:{fid} ({str(ex)[:50]}) — {wait}s", flush=True)
                time.sleep(wait)
        if (i + 1) % 20 == 0:
            save_json(cache_p, cache)
            print(f"  로스터 {i+1}/{len(todo)}", flush=True)
        time.sleep(0.05)
    save_json(cache_p, cache)
    return cache


def main():
    cli = WCLV2()
    p0 = (cli.points_left() or {}).get("pointsSpentThisHour", 0)
    mythic = step1_mythic(cli)
    step2_heroic(cli)
    step3_rosters(cli, mythic)
    p1 = (cli.points_left() or {}).get("pointsSpentThisHour", 0)
    print(f"\n페치 완료 · 포인트 {p1 - p0:.0f}", flush=True)


if __name__ == "__main__":
    main()
