"""Apply the pre-registered V09 §7 adoption criteria to a caver9.evaluation summary.json."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

LEGACY_NEW_OTHER = ('recovery', 'gradual', 'early', 'double', 'single')


def check(summary: dict, policy: str) -> dict:
    s = summary['summary']
    g = lambda sc, k: s[sc][policy].get(k)
    res = {}
    res['1_stationary_noninferior_v06'] = g('stationary', 'diff_unique_false_pass_vs_CAVER-v0.6_ci')[0] > -0.5
    for sc in ('abrupt', 'delayed'):
        res[f'2_{sc}_better_than_v06'] = g(sc, 'diff_unique_false_pass_vs_CAVER-v0.6_ci')[0] > 0
        res[f'2_{sc}_close_to_ucb1'] = g(sc, 'diff_unique_false_pass_vs_UCB1_ci')[0] > -0.5
        res[f'3_{sc}_faster_recovery_than_v06'] = g(sc, 'diff_recovery_steps_vs_CAVER-v0.6_ci')[1] < 0
    for sc in LEGACY_NEW_OTHER:
        if sc in s:
            res[f'4_{sc}_noninferior_v06'] = g(sc, 'diff_unique_false_pass_vs_CAVER-v0.6_ci')[0] > -0.5
    return {'policy': policy, 'criteria': res, 'all_pass': all(res.values()),
            'failed': [k for k, v in res.items() if not v]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('summary', type=Path)
    p.add_argument('policies', nargs='+')
    a = p.parse_args()
    doc = json.loads(a.summary.read_text())
    for pol in a.policies:
        r = check(doc, pol)
        print(f"{pol:16s} ALL_PASS={r['all_pass']}  failed={r['failed']}")


if __name__ == '__main__':
    main()
