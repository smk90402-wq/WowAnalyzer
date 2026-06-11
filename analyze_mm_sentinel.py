import json, sys, csv
from pathlib import Path
from collections import Counter
DATA = Path(__file__).resolve().parent / 'data'
import os; TMP = Path(os.environ.get('BM_TMP','/tmp'))
def load_wanted():
    rows = list(csv.DictReader(open(DATA/'rankings_zone46_mythic_dps_top100.csv', encoding='utf-8')))
    mm = [r for r in rows if r['class']=='Hunter' and r['spec'].replace(' ','')=='Marksmanship']
    pf = json.load(open(DATA/'v2_cache_player_fight.json', encoding='utf-8'))
    meta = json.load(open(DATA/'v2_cache_report_meta.json', encoding='utf-8'))
    w = {}
    for r in mm:
        rid, fid, ch = r['report_id'], int(r['fight_id']), r['character']
        p = pf.get(f'{rid}:{fid}:{ch}')
        if not isinstance(p, dict): continue
        sid = p.get('sourceID'); m = meta.get(rid)
        if sid is None or not m: continue
        f = next((x for x in (m.get('fights') or []) if x.get('id')==fid), None)
        if not f: continue
        w[f'{rid}:{fid}:{sid}'] = {'boss': r['encounter_name'], 'rank': int(r['rank']),
            'char': ch, 't0': f['startTime'], 't1': f['endTime'], 'nodes': p.get('nodes') or []}
    return w
def main():
    w = load_wanted()
    print('MM wanted:', len(w), flush=True)
    json.dump(w, open(TMP/'mm_wanted.json','w'))
    cache = TMP/'mm_events.json'
    if not cache.exists():
        print('events read...', flush=True)
        s = open(DATA/'v2_cache_events.json', encoding='utf-8').read()
        print(f'read {len(s)/1e6:.0f}MB, parse...', flush=True)
        dec = json.JSONDecoder(); out, i, n, seen = {}, 1, len(s), 0
        while i < n:
            while i < n and s[i] in ' \t\r\n,': i += 1
            if i >= n or s[i]=='}': break
            key, j = dec.raw_decode(s, i); i = j
            while s[i] in ' \t\r\n:': i += 1
            val, j = dec.raw_decode(s, i); i = j
            seen += 1
            if seen % 400 == 0: print(f'  scan {seen}, hit {len(out)}', flush=True)
            if key in w: out[key] = val
        json.dump(out, open(cache,'w'))
        print(f'done: {len(out)}/{len(w)}', flush=True)
    ev = json.load(open(cache))
    cc, bc, nf = Counter(), Counter(), 0
    for k, info in w.items():
        if info['boss'] not in ('Vaelgor & Ezzorak','Lightblinded Vanguard'): continue
        e = ev.get(k)
        if not e: continue
        nf += 1
        for c in e.get('casts', []):
            if len(c)>=3 and c[2]=='cast': cc[c[1]] += 1
        for b in e.get('buffs', []):
            if len(b)>=3 and b[2]=='applybuff': bc[b[1]] += 1
    print('census fights:', nf)
    print('CASTS:', cc.most_common(18))
    print('BUFFS:', bc.most_common(25))
main()
