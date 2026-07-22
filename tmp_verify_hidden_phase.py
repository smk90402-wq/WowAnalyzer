# WCL 르우라 랭킹이 어떤 구간을 제외하는지 검증
# 랭킹 dps(amount) vs 실총딜/전체시간 — 차이가 있으면 제외 구간 존재 (히든페 가설)
from wcl_v2 import WCLV2
from wcl_v2_data import V2Data, Q_DAMAGE_TABLE

Q_RANK = """
query($code: String!, $fightIDs: [Int]!) {
  reportData { report(code: $code) { rankings(fightIDs: $fightIDs) } }
}
"""

v2 = V2Data()
cli = v2.cli

for code, fid, char in (("8bcN17hKrMtmTGDB", 15, "만터리"),
                        ("BtADGd3RkJy6gb4f", 10, "만터리")):
    meta = v2.report_meta(code)
    f = next(x for x in meta["fights"] if x["id"] == fid)
    dur = (f["endTime"] - f["startTime"]) / 1000.0
    table = v2.damage_table(code, fid, char)
    total = sum(int(e.get("total") or 0) for e in table or [])
    naive = total / dur
    d = cli.query(Q_RANK, {"code": code, "fightIDs": [fid]})
    rk = (((d.get("reportData") or {}).get("report") or {}).get("rankings") or {})
    fight = next((r for r in rk.get("data") or [] if r.get("fightID") == fid), {})
    amount = None
    for role in (fight.get("roles") or {}).values():
        for row in role.get("characters") or []:
            if row.get("name") == char:
                amount = float(row.get("amount") or 0)
                rankp = row.get("rankPercent")
    print(f"{code} fight {fid} ({dur:.0f}s)")
    print(f"  실총딜/전체시간 = {naive:,.0f} dps")
    print(f"  WCL 랭킹 amount = {amount:,.0f} dps (rank {rankp}%)" if amount else "  랭킹 없음")
    if amount:
        implied = total / amount
        print(f"  → 랭킹이 쓰는 유효시간 = {implied:.0f}s (전체 {dur:.0f}s, 차이 {dur - implied:+.0f}s)")
    print()
