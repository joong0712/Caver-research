"""Compare Agent D's L1 dev rerun with the lead's committed dev outputs (fc2c8ae)."""
import csv
import json
import sys

LEAD = sys.argv[1]
MINE = 'reports/v010/agent_d/l1_dev_rerun'
CAND = 'C10-L1-ProfileGated'

sel = json.load(open(f'{MINE}/selection.json'))
lead = json.load(open(f'{LEAD}/selection.json'))
print('selection top-level keys (mine):', sorted(sel))
print('selection top-level keys (lead):', sorted(lead))


def find_checks(s):
    pc = s['per_candidate'][CAND]
    return pc, pc.get('checks')


pc, checks = find_checks(sel)
lpc, lchecks = find_checks(lead)
print('per-candidate keys:', sorted(pc))
print('mine: eligible =', pc.get('eligible'), ' n_checks =', len(checks),
      ' failed =', sum(1 for c in checks if not c['pass']))
print('lead: eligible =', lpc.get('eligible'), ' n_checks =', len(lchecks),
      ' failed =', sum(1 for c in lchecks if not c['pass']))
print('nominated (mine / lead):', sel.get('nominated'), '/', lead.get('nominated'))
print('selection.json identical (JSON-normalised):', json.loads(json.dumps(sel)) == lead)
nd = sum(1 for a, b in zip(checks, lchecks) if a != b)
print('checks differing:', nd)
print('failed checks (mine):')
for c in checks:
    if not c['pass']:
        print('  ', json.dumps(c, default=str))

# summary comparison
ms = json.load(open(f'{MINE}/summary.json'))
ls = json.load(open(f'{LEAD}/summary.json'))
ls = ls.get('summary', ls)
diffs = 0
for sc in ms:
    for pol in ms[sc]:
        a = {k: v for k, v in ms[sc][pol].items() if 'cpu' not in k}
        b = {k: v for k, v in ls[sc][pol].items() if 'cpu' not in k}
        if json.loads(json.dumps(a, default=str)) != b:
            diffs += 1
            ks = [k for k in set(a) | set(b) if json.loads(json.dumps(a.get(k), default=str)) != b.get(k)]
            print('summary diff', sc, pol, ks[:8])
print('summary scenario x policy cells:', sum(len(v) for v in ms.values()), ' differing (excluding cpu):', diffs)


# runs comparison
def load(p):
    with open(p) as f:
        return list(csv.DictReader(f))


mr, lr = load(f'{MINE}/runs.csv'), load(f'{LEAD}/runs.csv')
print('runs: mine', len(mr), 'lead', len(lr))
key = lambda r: (r['salt'], r['scenario'], r['policy'], int(r['seed']))
md = {key(r): r for r in mr}
ld = {key(r): r for r in lr}
print('same run keys:', set(md) == set(ld))
bad = 0
for k in md:
    a = {x: y for x, y in md[k].items() if 'cpu' not in x}
    b = {x: y for x, y in ld[k].items() if 'cpu' not in x}
    if a != b:
        bad += 1
print('runs differing in any non-cpu field:', bad)
