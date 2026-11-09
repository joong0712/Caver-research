"""Compare Agent D's reproduced final report with the lead's committed one (c7ee94a)."""
import csv
import json
import sys

LEAD_DIR = sys.argv[1]
MINE = 'reports/v010/agent_d/final_repro'
mine = json.load(open(f'{MINE}/report.json'))
lead = json.load(open(f'{LEAD_DIR}/report.json'))
print('top-level keys mine:', sorted(mine))
print('top-level keys lead:', sorted(lead))

mc, lc = mine['criteria'], lead['criteria']
print('verdict mine / lead:', mc['verdict'], '/', lc['verdict'])
print('adopt mine / lead:', mc['adopt'], '/', lc['adopt'])
print('failed mine / lead:', mc['failed'], '/', lc['failed'])
nchk = nfail = ndiff = 0
for k in mc['criteria']:
    a, b = mc['criteria'][k]['checks'], lc['criteria'][k]['checks']
    if len(a) != len(b):
        print('  check count differs in', k, len(a), len(b))
    for x, y in zip(a, b):
        nchk += 1
        nfail += not x['pass']
        if x != y:
            ndiff += 1
            print('  check differs', k, x, y)
print(f'checks: {nchk}; failed (mine): {nfail}; differing from lead: {ndiff}')
print('criteria block identical:', mc == lc)
print('holm identical:', mine.get('holm') == lead.get('holm'))
print('manifest_sha256 mine / lead:', mine.get('manifest_sha256'), '/', lead.get('manifest_sha256'))

# stats: every scenario x policy, excluding cpu fields
def strip(x):
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if 'cpu' not in k}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x

ms, ls = mine['stats'], lead['stats']
cells = diffcells = 0
fields = {'ufp_mean': 0, 'ufp_ci': 0, 'diff_ci': 0, 'boot_ci': 0, 'p': 0, 'rec_rmst': 0, 'km_median': 0,
          'censored': 0, 'fa': 0}
for sc in ms:
    for pol in ms[sc]:
        cells += 1
        a, b = strip(ms[sc][pol]), strip(ls[sc][pol])
        if a != b:
            diffcells += 1
            print('  stats differ', sc, pol, [k for k in set(a) | set(b) if a.get(k) != b.get(k)])
        fields['ufp_mean'] += a['unique_false_pass'] == b['unique_false_pass']
        fields['ufp_ci'] += a['unique_false_pass_ci'] == b['unique_false_pass_ci']
        fields['rec_rmst'] += a.get('recovery_rmst') == b.get('recovery_rmst')
        fields['censored'] += a.get('recovery_censored_rate') == b.get('recovery_censored_rate')
        fields['km_median'] += [e.get('km_median') for e in (a.get('recovery_events_km') or [])] == \
                               [e.get('km_median') for e in (b.get('recovery_events_km') or [])]
        fields['fa'] += a.get('false_alarm_rate') == b.get('false_alarm_rate')
        dd = all(a['diff'][r][m].get('ci') == b['diff'][r][m].get('ci') for r in a['diff'] for m in a['diff'][r])
        fields['diff_ci'] += dd
        fields['boot_ci'] += all(a['diff'][r][m].get('boot_ci') == b['diff'][r][m].get('boot_ci')
                                 for r in a['diff'] for m in a['diff'][r])
        fields['p'] += all(a['diff'][r][m].get('p') == b['diff'][r][m].get('p') for r in a['diff'] for m in a['diff'][r])
print(f'stats cells (scenario x policy): {cells}; differing (cpu fields excluded): {diffcells}')
print('cells with identical field:', fields)
other = [k for k in mine if k not in ('stats', 'criteria', 'holm', 'meta')]
for k in other:
    print(f'key {k!r} identical:', strip(mine[k]) == strip(lead.get(k)))
mm, lm = mine.get('meta', {}), lead.get('meta', {})
print('meta keys differing:', sorted(k for k in set(mm) | set(lm) if mm.get(k) != lm.get(k)))
for k in sorted(k for k in set(mm) | set(lm) if mm.get(k) != lm.get(k)):
    print('   meta', k, 'mine=', json.dumps(mm.get(k), default=str)[:200], ' lead=', json.dumps(lm.get(k), default=str)[:200])


def load(p):
    with open(p) as f:
        return list(csv.DictReader(f))


mr, lr = load(f'{MINE}/runs.csv'), load(f'{LEAD_DIR}/runs.csv')
key = lambda r: (r['salt'], r['scenario'], r['policy'], int(r['seed']))
md, ld = {key(r): r for r in mr}, {key(r): r for r in lr}
print('runs mine / lead:', len(mr), '/', len(lr), ' same keys:', set(md) == set(ld))
bad = sum(1 for k in md if {x: y for x, y in md[k].items() if 'cpu' not in x} !=
          {x: y for x, y in ld[k].items() if 'cpu' not in x})
print('runs differing in any non-cpu field:', bad)
print('runs differing in cpu field:', sum(1 for k in md if md[k].get('cpu_us_per_probe') != ld[k].get('cpu_us_per_probe')))
