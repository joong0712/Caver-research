"""Extended table composition and R2/R3 agreement with the stored real outcomes (read-only)."""
import json
from collections import Counter, defaultdict

t = json.load(open('reports/v010/outcome_table_extended_real.json'))
base = json.load(open('reports/v09/outcome_table_real_2reps.json'))
r1 = json.load(open('reports/v010/real/R1_new_variants.json'))
brows = base['rows'] if isinstance(base, dict) else base
print('base rows:', len(brows), ' base configs:', len({r["config"] for r in brows}))
tr = {r['trial'] for r in t['rows']}
print('table trials == base trials + R1 trials:', tr == {r['trial'] for r in brows} | {r['trial'] for r in r1['rows']},
      ' (|table|=%d, |base|=%d, |R1|=%d)' % (len(tr), len(brows), len(r1['rows'])))
R1cfg = {r['config'] for r in r1['rows']}
print('R1 configs: new variants', len(R1cfg & set(t['meta']['new_variants'])),
      ' healthy', len([c for c in R1cfg if c.endswith('/healthy')]))

stat = defaultdict(set)
outc = defaultdict(set)
for r in t['rows']:
    stat[r['config']].add(r['status'])
    outc[r['config']].add((r['false_pass'], r['contract_violated']))
for name in ('R2_alt_prompt', 'R3_cli_2_1_300'):
    d = json.load(open(f'reports/v010/real/{name}.json'))
    agree = dis = 0
    out = []
    for r in d['rows']:
        same = (r['false_pass'], r['contract_violated']) in outc[r['config']] and len(outc[r['config']]) == 1
        if same:
            agree += 1
        else:
            dis += 1
            out.append((r['config'], r['status'], sorted(stat[r['config']])))
    cfgs = {r['config'] for r in d['rows']}
    print(f'{name}: {len(d["rows"])} runs, configs all old:', cfgs <= set(t['meta']['old_configs']),
          f' agree with table outcome {agree}, differ {dis}')
    for o in out:
        print('   differs:', o)
