"""Compare a REAL outcome table with the SIMULATED one, config by config. No CLI calls.

Categories (per config):
  reproduced_false_pass  mock FALSE_PASS and real FALSE_PASS
  mock_only_false_pass   mock FALSE_PASS, real conclusive and not FALSE_PASS
  real_only_false_pass   real FALSE_PASS, mock not
  agree_other            same non-FALSE_PASS status
  differ_other           different non-FALSE_PASS statuses
  real_inconclusive      real run INCONCLUSIVE_* (no claim either way)
  real_missing           config not run for real
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path


def _index(table: dict) -> dict:
    out = {}
    for r in table['rows']:
        out.setdefault(r['config'], r)  # first repetition
    return out


def compare(real: dict, mock: dict) -> dict:
    if real['meta']['cli_kind'] != 'real' or mock['meta']['cli_kind'] != 'simulated':
        raise ValueError('expected one real and one simulated table')
    R, M = _index(real), _index(mock)
    rows = []
    for key, m in M.items():
        r = R.get(key)
        if r is None:
            cat = 'real_missing'
        elif r['status'].startswith('INCONCLUSIVE'):
            cat = 'real_inconclusive'
        elif m['status'] == 'FALSE_PASS' and r['status'] == 'FALSE_PASS':
            cat = 'reproduced_false_pass'
        elif m['status'] == 'FALSE_PASS':
            cat = 'mock_only_false_pass'
        elif r['status'] == 'FALSE_PASS':
            cat = 'real_only_false_pass'
        elif m['status'] == r['status']:
            cat = 'agree_other'
        else:
            cat = 'differ_other'
        g = (lambda k: r.get(k) if r else None)
        rows.append({'config': key, 'family': m['family'], 'variant': m['variant'], 'category': cat,
                     'mock_status': m['status'], 'real_status': g('status'),
                     'mock_hook': m.get('hook_exit_status'), 'real_hook': g('hook_exit_status'),
                     'real_target_hook_invoked': g('target_hook_invoked'),
                     'real_pre': g('pre_attempts'), 'real_post': g('post_executions'),
                     'real_marker': g('marker_exists'), 'weak_test_passed': m['weak_test_passed'],
                     'real_permission_denials': g('permission_denials'),
                     'real_attempted_commands': g('attempted_commands'),
                     'real_consistency_issues': g('consistency_issues')})
    counts = {}
    for x in rows:
        counts[x['category']] = counts.get(x['category'], 0) + 1
    return {'meta': {'real_runs': len(real['rows']), 'mock_configs': len(M),
                     'mock_false_pass': sum(m['status'] == 'FALSE_PASS' for m in M.values()),
                     'real_false_pass': sum(r['status'] == 'FALSE_PASS' for r in R.values()),
                     'categories': counts},
            'rows': rows}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--real', type=Path, default=Path('reports/v08/outcome_table_real.json'))
    p.add_argument('--mock', type=Path, default=Path('reports/v08/outcome_table_simulated_v2.json'))
    p.add_argument('--output', type=Path, default=Path('reports/v08/real_vs_mock'))
    a = p.parse_args()
    res = compare(json.loads(a.real.read_text()), json.loads(a.mock.read_text()))
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / 'comparison.json').write_text(json.dumps(res, indent=2, ensure_ascii=False))
    with (a.output / 'comparison.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(res['rows'][0]))
        w.writeheader()
        w.writerows(res['rows'])
    print(json.dumps(res['meta'], indent=2))
    for x in res['rows']:
        print(f"{x['config']:40s} {x['category']:24s} mock={x['mock_status']:24s} real={x['real_status']}")


if __name__ == '__main__':
    main()
