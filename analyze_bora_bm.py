"""보라시우스(3177) BM 무리인도자 상위 파스 — 치명/가속/특화 vs raw DPS 실측 분석."""
import csv, json, math, statistics
from collections import Counter
from pathlib import Path
from wcl_v2_data import V2Data

DR_MARKER = 466930  # 검은 화살 = 어둠순찰자 표식 (없으면 무리인도자)

rows = [r for r in csv.DictReader(open('data/rankings_zone46_mythic_dps_top100.csv', encoding='utf-8'))
        if r['encounter_id'] == '3177' and r['spec'] == 'Beast Mastery' and (r['dps'] or '').strip()]
rows.sort(key=lambda r: float(r['dps']), reverse=True)
print('BM 보라시우스 파스:', len(rows))

v2 = V2Data(data_dir=Path('data'))
res = []
for i, r in enumerate(rows):
    try:
        pf = v2.player_fight(r['report_id'], int(r['fight_id']), r['character'])
    except Exception as e:
        print('  fail', i, str(e)[:40]); continue
    if not isinstance(pf, dict):
        continue
    st = pf.get('stats') or {}
    tal = set(pf.get('talents') or [])
    res.append({'char': r['character'], 'dps': float(r['dps']), 'ilvl': int(r['item_level'] or 0),
                'hero': 'DarkRanger' if DR_MARKER in tal else 'PackLeader',
                'crit': st.get('Crit', 0), 'haste': st.get('Haste', 0),
                'mastery': st.get('Mastery', 0), 'vers': st.get('Versatility', 0)})
    if i % 10 == 0:
        print('  progress', i, '/', len(rows))

json.dump(res, open('_bora_bm.json', 'w'), indent=1)
print('=== DONE 페치 성공:', len(res), '/', len(rows))
print('영웅 분포:', dict(Counter(x['hero'] for x in res)))


def pearson(xs, ys):
    n = len(xs)
    if n < 3: return 0
    mx, my = sum(xs)/n, sum(ys)/n
    cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x-mx)**2 for x in xs)); sy = math.sqrt(sum((y-my)**2 for y in ys))
    return cov/(sx*sy) if sx*sy else 0


for hero in ('PackLeader', 'DarkRanger'):
    g = [x for x in res if x['hero'] == hero]
    if len(g) < 3:
        print(f'--- {hero}: {len(g)}개 (적음, 생략)'); continue
    print(f'\n=== {hero} ({len(g)}개) ===')
    for k in ('crit', 'haste', 'mastery', 'vers'):
        vs = [x[k] for x in g]
        print(f'  {k:8s} mean {statistics.mean(vs):6.0f}  median {statistics.median(vs):6.0f}  '
              f'min {min(vs):5d} max {max(vs):5d}  | corr vs dps {pearson([x[k] for x in g],[x["dps"] for x in g]):+.3f}')
    print(f'  ilvl corr vs dps: {pearson([x["ilvl"] for x in g],[x["dps"] for x in g]):+.3f}')
    gs = sorted(g, key=lambda x: -x['dps'])
    n = max(5, len(g)//4)
    top, bot = gs[:n], gs[-n:]
    print(f'  -- 상위{n} vs 하위{n} 파스 평균 스탯 --')
    for k in ('crit', 'haste', 'mastery', 'vers'):
        print(f'     {k:8s} 상위 {statistics.mean([x[k] for x in top]):6.0f}  하위 {statistics.mean([x[k] for x in bot]):6.0f}')
    print(f'     dps    상위 {statistics.mean([x["dps"] for x in top]):8.0f}  하위 {statistics.mean([x["dps"] for x in bot]):8.0f}')
