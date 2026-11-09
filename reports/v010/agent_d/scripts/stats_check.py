"""Independent re-derivation (no caver10.stats) of the criteria checks, Holm and IUT from runs.csv."""
import csv
import json
import math
from statistics import mean, stdev

D = 'reports/v010/agent_d/final_repro'
rep = json.load(open(f'{D}/report.json'))
runs = list(csv.DictReader(open(f'{D}/runs.csv')))
CAND, V06, C2 = 'C10-L1-ProfileGated', 'CAVER-v0.6', 'C9-UCBMean'
Z = 1.959963984540054


def vals(sc, pol, k):
    rs = sorted((r for r in runs if r['scenario'] == sc and r['policy'] == pol), key=lambda r: int(r['seed']))
    return [float(r[k]) for r in rs]


def ci(sc, ref, k):
    d = [a - b for a, b in zip(vals(sc, CAND, k), vals(sc, ref, k))]
    m = mean(d)
    se = stdev(d) / math.sqrt(len(d))
    return m, (m - Z * se, m + Z * se), math.erfc(abs(m / se) / math.sqrt(2)) if se else (1.0 if m == 0 else 0.0)


b = rep['criteria']['bindings']
print('bindings:', json.dumps(b))
stat = b['stationary'] + b['flat_shift']
checks = []
for sc in stat:
    checks.append(('S1', sc, ci(sc, V06, 'unique_false_pass')[1][0] > -0.25, ci(sc, V06, 'unique_false_pass')[1][0]))
    checks.append(('S2', sc, ci(sc, C2, 'unique_false_pass')[1][0] > 0, ci(sc, C2, 'unique_false_pass')[1][0]))
for sc in b['abrupt']:
    checks.append(('K1', sc, ci(sc, C2, 'unique_false_pass')[1][0] > -0.3, ci(sc, C2, 'unique_false_pass')[1][0]))
    checks.append(('K1', sc, ci(sc, V06, 'unique_false_pass')[1][0] > 0, ci(sc, V06, 'unique_false_pass')[1][0]))
    checks.append(('K2', sc, ci(sc, V06, 'recovery_steps')[1][1] < 0, ci(sc, V06, 'recovery_steps')[1][1]))
    checks.append(('K2', sc, ci(sc, C2, 'recovery_steps')[1][1] < 1.5, ci(sc, C2, 'recovery_steps')[1][1]))
for sc in b['all']:
    for ref in ('Random', 'SW-UCB', 'D-UCB'):
        checks.append(('G', sc, ci(sc, ref, 'unique_false_pass')[1][0] > 0, ci(sc, ref, 'unique_false_pass')[1][0]))
    checks.append(('G', sc, ci(sc, V06, 'unique_false_pass')[1][0] > -0.5, ci(sc, V06, 'unique_false_pass')[1][0]))


def fa(sc, pol):
    rs = [r for r in runs if r['scenario'] == sc and r['policy'] == pol]
    if rs[0]['has_detector'] != 'True':
        return 0.0
    return mean(float(int(r['prechange_alarms'] or 0) > 0) for r in rs)


for sc in b['false_alarm']:
    checks.append(('FA', sc, fa(sc, CAND) <= fa(sc, V06) + 0.05 + 1e-12, fa(sc, CAND)))
rep_checks = [(k, c.get('scenario'), c['pass'], c['value']) for k in ('S1', 'S2', 'K1', 'K2', 'G', 'FA')
              for c in rep['criteria']['criteria'][k]['checks']]
order = ['S1', 'S2', 'K1', 'K2', 'G', 'FA']
checks.sort(key=lambda c: order.index(c[0]))  # stable: report groups checks by criterion
print('independent checks (excluding RV):', len(checks), ' report checks (excluding RV):', len(rep_checks))
agree_pass = all(a[2] == r[2] for a, r in zip(checks, rep_checks))
agree_val = all(abs(a[3] - r[3]) <= 5.0001e-5 and a[1] == r[1] and a[0] == r[0] for a, r in zip(checks, rep_checks))
print('pass/fail agree:', agree_pass, ' values agree (report rounds to 4 dp; tol 5e-5):', agree_val)
failed = sorted({c[0] for c in checks if not c[2]})
print('independent failed criteria:', failed, ' report failed:', rep['criteria']['failed'])
print('IUT verdict: adopt iff no criterion fails ->', 'adopt' if not failed else 'on hold',
      '; report adopt =', rep['criteria']['adopt'])
for c in checks:
    if not c[2]:
        print('  FAILED', c[0], c[1], round(c[3], 4))

# Holm across all reported candidate comparisons, recomputed from scratch
raw = {k: v['p'] for k, v in rep['holm'].items()}
items = sorted(raw.items(), key=lambda kv: (kv[1], kv[0]))
m = len(items)
adj, run = {}, 0.0
for i, (k, p) in enumerate(items):
    run = max(run, min(1.0, (m - i) * p))
    adj[k] = run
print('holm comparisons:', m, ' independent Holm == report p_holm:',
      all(abs(adj[k] - rep['holm'][k]['p_holm']) < 1e-12 for k in adj))
# spot-check one raw p from runs.csv
k0 = 'f_abrupt_boundary|C9-UCBMean|recovery_steps'
print('spot p', k0, 'recomputed', ci('f_abrupt_boundary', C2, 'recovery_steps')[2], 'report', raw[k0])
n_scen = len(rep['stats'])
refs = [p for p in rep['stats']['f_stat_skew'] if p != CAND]
n_ev = sum(1 for sc in rep['stats'] if rep['stats'][sc][CAND].get('recovery_events_km'))
print(f'expected Holm family = {n_scen} scenarios x {len(refs)} refs (FP) + {n_ev} event scenarios x {len(refs)} refs (recovery) =',
      n_scen * len(refs) + n_ev * len(refs))
