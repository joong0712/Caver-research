"""Independent statistics spot-checks (reproduction verifier).

Recomputes from runs.csv.gz ONLY (stdlib; does not import caver10.stats or any caver module):
  1. pooled case-level difference C-B vs CAVER-v0.6 (unique_false_pass): per seed, mean over the
     scenarios of the paired difference; mean, normal 95% CI, two-sided p;
  2. Kaplan-Meier medians of recovery time per (scenario with shift events, policy, event);
  3. the whole Holm family (per scenario x reference: unique FP, recovery steps, variant-level FP,
     duplicate rate; pooled x reference: unique FP, variant-level FP), raw p and Holm-adjusted p.
Then compares each recomputed value with the saved report.json.

Usage: python3 reports/v011/repro/stats_spotcheck.py <dir with report.json and runs.csv.gz>
"""
import csv
import gzip
import io
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

CAND = 'C11C-PopBUCB-Div'
V06 = 'CAVER-v0.6'
ND = NormalDist()
Z = ND.inv_cdf(0.975)


def num(x):
    if x in ('', 'None', None):
        return None
    if x in ('True', 'False'):
        return x == 'True'
    try:
        return int(x)
    except ValueError:
        return float(x)


def load(d):
    raw = gzip.decompress((Path(d) / 'runs.csv.gz').read_bytes()).decode()
    rows = list(csv.DictReader(io.StringIO(raw)))
    return rows, json.loads((Path(d) / 'report.json').read_text(encoding='utf-8'))


def normal_paired(a, b):
    d = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    n = len(d)
    m = sum(d) / n
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    se = math.sqrt(var / n)
    p = (1.0 if m == 0 else 0.0) if se == 0 else math.erfc(abs(m) / se / math.sqrt(2))  # = 2*(1-Phi(abs z)); erfc keeps tail precision (NormalDist.cdf underflows below ~1e-17)
    return {'n': n, 'mean': m, 'ci': [m - Z * se, m + Z * se], 'se': se, 'p': p}


def km_median(times, cens):
    """Own product-limit estimator: median = first event time where S(t) <= 0.5."""
    s = 1.0
    for t in sorted({t for t, c in zip(times, cens) if not c}):
        risk = sum(u >= t for u in times)
        dead = sum(u == t and not c for u, c in zip(times, cens))
        s *= (risk - dead) / risk
        if s <= 0.5 + 1e-12:
            return t
    return None


def holm(p):
    keys = sorted(p, key=lambda k: (p[k], k))
    m, run, out = len(keys), 0.0, {}
    for i, k in enumerate(keys):
        run = max(run, min(1.0, (m - i) * p[k]))
        out[k] = run
    return out


def main(d):
    rows, rep = load(d)
    by = defaultdict(dict)            # (scenario, policy) -> {seed: row}
    for r in rows:
        by[(r['scenario'], r['policy'])][int(r['seed'])] = r
    scen = list(rep['stats'])
    pols = rep['meta']['policies']
    refs = [r for r in rep['meta']['references'] if r != CAND]
    seeds = sorted(by[(scen[0], CAND)])

    def col(sc, pol, k):
        return [num(by[(sc, pol)][s][k]) for s in seeds]

    out = {'n_rows': len(rows), 'scenarios': scen, 'policies': pols, 'n_seeds': len(seeds)}
    # 1. pooled
    def pooled(pol, k):
        return [sum(num(by[(sc, pol)][s][k]) for sc in scen) / len(scen) for s in seeds]
    mine = normal_paired(pooled(CAND, 'unique_false_pass'), pooled(V06, 'unique_false_pass'))
    saved = rep['pooled'][CAND]['diff'][V06]['unique_false_pass']
    out['pooled_vs_v06'] = {'recomputed': mine, 'saved': saved,
                            'match_4dp': round(mine['mean'], 4) == saved['mean']
                            and [round(x, 4) for x in mine['ci']] == saved['ci']
                            and abs(mine['p'] - saved['p']) <= 1e-9 * max(1.0, saved['p'])}
    # 2. KM medians
    km = []
    for sc in scen:
        for pol in pols:
            ev = [str(by[(sc, pol)][s]['recovery_events'] or '') for s in seeds]
            parsed = []
            for txt in ev:
                parsed.append([(int(x[:-1]) - 1, True) if x.endswith('+') else (int(x), False)
                               for x in txt.split(';') if x])
            n_ev = max((len(p) for p in parsed), default=0)
            saved_ev = (rep['stats'][sc][pol].get('recovery_events_km') or [])
            for i in range(n_ev):
                ts = [p[i][0] for p in parsed if len(p) > i]
                cs = [p[i][1] for p in parsed if len(p) > i]
                med = km_median(ts, cs)
                sv = saved_ev[i]['km_median'] if i < len(saved_ev) else '<missing>'
                km.append({'scenario': sc, 'policy': pol, 'event': i, 'n': len(ts), 'censored': sum(cs),
                           'km_median': med, 'saved': sv, 'match': med == sv})
    out['km'] = {'n': len(km), 'n_match': sum(k['match'] for k in km),
                 'mismatches': [k for k in km if not k['match']],
                 'examples': [k for k in km if k['policy'] in (CAND, V06)][:6]}
    # 3. Holm family
    raw = {}
    for sc in scen:
        has_ev = bool(rep['stats'][sc][CAND].get('recovery_events_km'))
        for ref in refs:
            ks = ['unique_false_pass'] + (['recovery_steps'] if has_ev else []) + \
                 ['unique_variant_false_pass', 'duplicate_rate']
            for k in ks:
                r = normal_paired(col(sc, CAND, k), col(sc, ref, k))
                raw[f'{sc}|{ref}|{k}'] = r['p']
    for ref in refs:
        for k in ('unique_false_pass', 'unique_variant_false_pass'):
            raw[f'pooled|{ref}|{k}'] = normal_paired(pooled(CAND, k), pooled(ref, k))['p']
    adj = holm(raw)
    saved_h = rep['criteria']['holm']
    tol = lambda a, b: abs(a - b) <= 1e-9 * max(1e-300, abs(b)) or abs(a - b) <= 1e-15
    keys_equal = sorted(raw) == sorted(saved_h)
    bad = [k for k in raw if k in saved_h and not (tol(raw[k], saved_h[k]['p']) and tol(adj[k], saved_h[k]['p_holm']))]
    pick = f'{scen[0]}|{V06}|unique_false_pass'
    pick2 = f'pooled|{V06}|unique_false_pass'
    small = min((k for k in raw if adj[k] < 1.0), key=lambda k: -adj[k], default=None)   # largest p_holm < 1
    out['holm'] = {'family_size_recomputed': len(raw), 'family_size_saved': len(saved_h),
                   'same_keys': keys_equal, 'n_mismatch_rel1e-9': len(bad), 'mismatches': bad[:10],
                   'example': {'key': pick, 'raw_p': raw.get(pick), 'p_holm': adj.get(pick),
                               'saved': saved_h.get(pick)},
                   'example_pooled': {'key': pick2, 'raw_p': raw.get(pick2), 'p_holm': adj.get(pick2),
                                      'saved': saved_h.get(pick2)},
                   'example_largest_p_holm_below_1': {'key': small, 'raw_p': raw.get(small), 'p_holm': adj.get(small),
                                                      'saved': saved_h.get(small)},
                   'n_p_holm_below_0_05': sum(v < 0.05 for v in adj.values()),
                   'max_abs_diff_p_holm': max(abs(adj[k] - saved_h[k]['p_holm']) for k in raw if k in saved_h)}
    print(json.dumps(out, indent=1, default=str))


if __name__ == '__main__':
    main(sys.argv[1])
