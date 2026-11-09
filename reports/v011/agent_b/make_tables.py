"""Render Agent B's dev tables from a devkit output directory (summary.json + runs.csv.gz).

    python3 reports/v011/agent_b/make_tables.py reports/v011/agent_b/dev [more dirs...] > tables.md

Reads only the saved devkit outputs (REPLAY, salt v011dev). Type-level and pooled CIs are paired
normal 95% over seeds of the per-seed mean difference across the scenarios of that type (the same
construction as devkit's pooled CI).
"""
from __future__ import annotations
import csv
import gzip
import json
import sys
from pathlib import Path
from statistics import mean, stdev

V06, C2, L1 = 'CAVER-v0.6', 'C9-UCBMean', 'C10-L1-ProfileGated'
BASE = ('Random', 'UCB1', 'SW-UCB', 'D-UCB', V06, C2, L1)


def ci(d):
    m = mean(d)
    h = 1.96 * stdev(d) / len(d) ** 0.5
    return m, m - h, m + h


def fmt(t):
    return f'{t[0]:+.2f} [{t[1]:+.2f}, {t[2]:+.2f}]'


def load(d):
    d = Path(d)
    s = json.loads((d / 'summary.json').read_text())
    by = {}
    with gzip.open(d / 'runs.csv.gz', 'rt') as f:
        for r in csv.DictReader(f):
            by[(r['scenario'], r['policy'], int(r['seed']))] = r
    return s, by


def num(x):
    return None if x in ('', 'None', None) else float(x)


def main(dirs):
    S, BY, rules = {}, {}, {}
    meta = None
    for d in dirs:
        s, by = load(d)
        meta = meta or s['meta']
        for sc, blk in s['summary'].items():
            S.setdefault(sc, {}).update(blk)
        BY.update(by)
        rules.update(s.get('rules') or {})
    types = meta['scenario_types']
    scen = meta['scenarios']
    seeds = range(meta['seeds'][0], meta['seeds'][1] + 1)
    pols = list(dict.fromkeys(p for sc in scen for p in S[sc]))
    cands = [p for p in pols if p not in BASE]
    out = [f"Evidence: {meta['evidence_type']}; salt {meta['salt']}; seeds {meta['seeds']}; "
           f"budget {meta['budget']}. Sources: {', '.join(map(str, dirs))}.", '']

    def pooled(p, ref, k, scs):
        return ci([mean(num(BY[(sc, p, s)][k]) - num(BY[(sc, ref, s)][k]) for sc in scs) for s in seeds])

    out += ['## Pooled and per-type Δ unique FALSE_PASS (per-seed mean over the scenarios of the type)', '',
            '| policy | pooled vs v0.6 | pooled vs C2 | stable vs v0.6 | stable vs C2 | abrupt vs v0.6 | abrupt vs C2 | other vs v0.6 | other vs C2 | pooled variant-level vs v0.6 | pooled variant-level vs C2 |',
            '|---|---|---|---|---|---|---|---|---|---|---|']
    for p in [L1, 'UCB1'] + cands:
        row = [p]
        for scs in (scen, types['stable'], types['abrupt'], types['other']):
            row += [fmt(pooled(p, V06, 'unique_false_pass', scs)), fmt(pooled(p, C2, 'unique_false_pass', scs))]
        row += [fmt(pooled(p, V06, 'unique_variant_false_pass', scen)), fmt(pooled(p, C2, 'unique_variant_false_pass', scen))]
        out.append('| ' + ' | '.join(row) + ' |')
    out += ['', 'C2 vs v0.6 pooled: ' + fmt(pooled(C2, V06, 'unique_false_pass', scen)), '']

    out += ['## Unique FALSE_PASS per scenario (mean); Δ vs v0.6 and vs C2 (95% CI)', '',
            '| scenario | type | v0.6 | C2 | L1 | UCB1 | ' + ' | '.join(f'{c} (Δ v0.6; Δ C2)' for c in cands) + ' |',
            '|---|---|---|---|---|---|' + '---|' * len(cands)]
    tmap = {sc: t for t, scs in types.items() for sc in scs}
    for sc in scen:
        b = S[sc]
        row = [sc, tmap[sc]] + [f"{b[p]['unique_false_pass']:.2f}" for p in (V06, C2, L1, 'UCB1')]
        for c in cands:
            m = b[c]
            d6, d2 = m[f'diff_unique_false_pass_vs_{V06}_ci'], m[f'diff_unique_false_pass_vs_{C2}_ci']
            row.append(f"{m['unique_false_pass']:.2f} ({m[f'diff_unique_false_pass_vs_{V06}']:+.2f} [{d6[0]:+.2f},{d6[1]:+.2f}]; "
                       f"{m[f'diff_unique_false_pass_vs_{C2}']:+.2f} [{d2[0]:+.2f},{d2[1]:+.2f}])")
        out.append('| ' + ' | '.join(row) + ' |')

    out += ['', '## Recovery (restricted mean steps; censoring rate) and Δ vs v0.6 (95% CI)', '',
            '| scenario | v0.6 | C2 | L1 | ' + ' | '.join(cands) + ' |', '|---|---|---|---|' + '---|' * len(cands)]
    for sc in scen:
        b = S[sc]
        if b[V06].get('recovery_steps') is None:
            continue
        row = [sc] + [f"{b[p]['recovery_steps']:.1f} ({b[p]['recovery_censored_rate']:.2f})" for p in (V06, C2, L1)]
        for c in cands:
            m = b[c]
            d = m[f'diff_recovery_steps_vs_{V06}_ci']
            row.append(f"{m['recovery_steps']:.1f} ({m['recovery_censored_rate']:.2f}); {m[f'diff_recovery_steps_vs_{V06}']:+.1f} [{d[0]:+.1f},{d[1]:+.1f}]")
        out.append('| ' + ' | '.join(row) + ' |')

    out += ['', '## Other metrics, mean over the 19 scenarios (per-scenario values in summary.json)', '',
            '| policy | unique FP | variant-level unique FP | first find | duplicate rate | false-alarm rate (mean where defined) | exploration entropy | USD/probe | wall ms/probe | CPU µs/probe |',
            '|---|---|---|---|---|---|---|---|---|---|']
    for p in list(BASE) + cands:
        def avg(k):
            v = [S[sc][p].get(k) for sc in scen]
            v = [x for x in v if x is not None]
            return mean(v) if v else None
        fa = avg('false_alarm_rate')
        out.append(f"| {p} | {avg('unique_false_pass'):.2f} | {avg('unique_variant_false_pass'):.2f} | {avg('first_find_at'):.2f} | "
                   f"{avg('duplicate_rate'):.4f} | {'–' if fa is None else f'{fa:.3f}'} | {avg('exploration_entropy'):.3f} | "
                   f"{avg('usd_per_probe'):.5f} | {avg('wall_ms_per_probe'):.0f} | {avg('cpu_us_per_probe'):.1f} |")

    out += ['', '## Stable-type scenarios: Δ unique FALSE_PASS vs v0.6 (95% CI)', '',
            '| policy | ' + ' | '.join(types['stable']) + ' |', '|---|' + '---|' * len(types['stable'])]
    for p in [C2, L1] + cands:
        out.append(f'| {p} | ' + ' | '.join(
            fmt((S[sc][p][f'diff_unique_false_pass_vs_{V06}'], *S[sc][p][f'diff_unique_false_pass_vs_{V06}_ci'])) for sc in types['stable']) + ' |')

    if rules:
        out += ['', '## devkit.dev_rule', '']
        for n, r in rules.items():
            out.append(f"* **{n}**: failed {r['n_failed']}/{r['n_checks']}, eligible={r['eligible']}, pooled vs v0.6 "
                       f"{r['pooled_vs_v06']}, vs C2 {r['pooled_vs_C2']}")
            for c in r['failed']:
                out.append(f"  * {c['id']} {c['scenario']}: {c['value']}")
    print('\n'.join(out))


if __name__ == '__main__':
    main(sys.argv[1:])
