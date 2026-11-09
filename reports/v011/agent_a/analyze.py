"""Agent A: render tables from a devkit output directory (summary.json + runs.csv.gz). No new runs.

python3 reports/v011/agent_a/analyze.py reports/v011/agent_a/dev A11-PooledGLR-Reset ... > tables.md
Type-level CIs: per seed, mean over the type's scenarios of (candidate - reference), then normal 95%.
"""
import csv
import gzip
import json
import sys
from pathlib import Path
from statistics import mean, stdev

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from caver11.devkit import TYPES, DEV_SCENARIOS, V06, C2  # noqa: E402


def ci(d):
    m = mean(d)
    h = 1.96 * stdev(d) / len(d) ** 0.5
    return f'{m:+.2f} [{m - h:+.2f}, {m + h:+.2f}]'


def f2(x, nd=2):
    return '–' if x is None else f'{x:.{nd}f}'


def main():
    out = Path(sys.argv[1])
    cands = sys.argv[2:]
    S = json.loads((out / 'summary.json').read_text())
    s, P, rules = S['summary'], S['pooled'], S.get('rules', {})
    by = {}
    with gzip.open(out / 'runs.csv.gz', 'rt') as f:
        for r in csv.DictReader(f):
            by[(r['scenario'], r['policy'], int(r['seed']))] = r
    seeds = sorted({k[2] for k in by})
    refs = ['Random', 'UCB1', 'SW-UCB', 'D-UCB', V06, C2, 'C10-L1-ProfileGated']
    pols = refs + cands
    print(f"evidence: {S['meta']['evidence_type']}; salt {S['meta']['salt']}; {S['meta']['n_seeds']} seeds; commit {S['meta']['git_commit']}\n")

    print('### Unique FALSE_PASS (mean)\n')
    print('| scenario | type | ' + ' | '.join(pols) + ' |')
    print('|' + '---|' * (len(pols) + 2))
    typ = {sc: t for t, scs in TYPES.items() for sc in scs}
    for sc in DEV_SCENARIOS:
        print(f'| {sc} | {typ[sc]} | ' + ' | '.join(f2(s[sc][p]['unique_false_pass']) for p in pols) + ' |')

    for c in cands:
        print(f'\n### {c}: paired Δ unique FALSE_PASS, recovery, FA, duplicates\n')
        print('| scenario | Δ vs v0.6 | Δ vs C2 | recovery (v0.6 / C2 / cand) | Δ recovery vs v0.6 | FA (cand / v0.6) | alarm rate | dup rate (cand / v0.6 / C2) | variant FP Δ vs v0.6 |')
        print('|---|---|---|---|---|---|---|---|---|')
        for sc in DEV_SCENARIOS:
            m = s[sc][c]
            d6 = m.get(f'diff_unique_false_pass_vs_{V06}_ci')
            d2 = m.get(f'diff_unique_false_pass_vs_{C2}_ci')
            r6 = m.get(f'diff_recovery_steps_vs_{V06}_ci')

            def fmt(k, cc):
                v = m.get(k)
                return '–' if v is None else f'{v:+.2f} [{cc[0]:+.2f}, {cc[1]:+.2f}]'
            print(f"| {sc} | {fmt(f'diff_unique_false_pass_vs_{V06}', d6)} | {fmt(f'diff_unique_false_pass_vs_{C2}', d2)} | "
                  f"{f2(s[sc][V06].get('recovery_steps'), 1)} / {f2(s[sc][C2].get('recovery_steps'), 1)} / {f2(m.get('recovery_steps'), 1)} | "
                  f"{fmt(f'diff_recovery_steps_vs_{V06}', r6) if r6 else '–'} | {f2(m.get('false_alarm_rate'), 3)} / {f2(s[sc][V06].get('false_alarm_rate'), 3)} | "
                  f"{f2(m.get('alarm_rate'), 3)} | {f2(m['duplicate_rate'], 3)} / {f2(s[sc][V06]['duplicate_rate'], 3)} / {f2(s[sc][C2]['duplicate_rate'], 3)} | "
                  f"{fmt(f'diff_unique_variant_false_pass_vs_{V06}', m.get(f'diff_unique_variant_false_pass_vs_{V06}_ci'))} |")

    print('\n### Type-level and pooled Δ unique FALSE_PASS (per-seed mean over the type\'s scenarios; 95% CI)\n')
    print('| policy | stable vs v0.6 | stable vs C2 | abrupt vs v0.6 | abrupt vs C2 | other vs v0.6 | other vs C2 | pooled-19 vs v0.6 | pooled-19 vs C2 | pooled variant-FP vs v0.6 | pooled variant-FP vs C2 |')
    print('|---|---|---|---|---|---|---|---|---|---|---|')
    for c in [L for L in pols if L not in (V06,)]:
        cells = []
        for t in ('stable', 'abrupt', 'other'):
            for ref in (V06, C2):
                if ref == c:
                    cells.append('–')
                    continue
                d = [mean(float(by[(sc, c, x)]['unique_false_pass']) - float(by[(sc, ref, x)]['unique_false_pass'])
                          for sc in TYPES[t]) for x in seeds]
                cells.append(ci(d))
        for k in ('unique_false_pass', 'unique_variant_false_pass'):
            for ref in (V06, C2):
                v, cc = P[c].get(f'diff_{k}_vs_{ref}'), P[c].get(f'diff_{k}_vs_{ref}_ci')
                cells.append('–' if v is None else f'{v:+.2f} [{cc[0]:+.2f}, {cc[1]:+.2f}]')
        print(f'| {c} | ' + ' | '.join(cells) + ' |')

    print('\n### Means over 19 scenarios: first find, duplicate rate, recovery (abrupt types), alarms, cost\n')
    print('| policy | unique FP | variant FP | first find | dup rate | recovery abrupt-type mean | censored abrupt-type | alarm rate | FA mean (where defined) | USD/probe | wall ms/probe | CPU µs/probe |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|')
    for c in pols:
        rows = [s[sc][c] for sc in DEV_SCENARIOS]
        ab = [s[sc][c] for sc in TYPES['abrupt']]
        fa = [r['false_alarm_rate'] for r in rows if r.get('false_alarm_rate') is not None]
        al = [r['alarm_rate'] for r in rows if r.get('alarm_rate') is not None]
        cpu = mean(float(by[(sc, c, x)]['cpu_us_per_probe']) for sc in DEV_SCENARIOS for x in seeds)
        print(f"| {c} | {mean(r['unique_false_pass'] for r in rows):.2f} | {mean(r['unique_variant_false_pass'] for r in rows):.2f} | "
              f"{mean(r['first_find_at'] for r in rows):.2f} | {mean(r['duplicate_rate'] for r in rows):.3f} | "
              f"{mean(r['recovery_steps'] for r in ab):.1f} | {mean(r['recovery_censored_rate'] for r in ab):.3f} | "
              f"{f2(mean(al), 3) if al else '–'} | {f2(mean(fa), 3) if fa else '–'} | {mean(r['usd_per_probe'] for r in rows):.4f} | "
              f"{mean(r['wall_ms_per_probe'] for r in rows):.0f} | {cpu:.1f} |")

    if rules:
        print('\n### dev_rule (V011_DESIGN §5)\n')
        for c, r in rules.items():
            ids = {}
            for x in r['failed']:
                ids.setdefault(x['id'], []).append(f"{x['scenario']} ({x['value']})")
            print(f"* **{c}**: failed {r['n_failed']}/{r['n_checks']}, eligible={r['eligible']}, "
                  f"pooled vs v0.6 {r['pooled_vs_v06']}, vs C2 {r['pooled_vs_C2']}")
            for k, v in ids.items():
                print(f'  * {k}: ' + '; '.join(v))


if __name__ == '__main__':
    main()
