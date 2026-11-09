"""Apply the pre-registered criteria A-F (docs/V09C_PROTOCOL.md §5) to the committed results."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from caver9c.confirm import ROOT, SCENARIOS

CAND = 'C9-UCBMean'
OTHER = tuple(s for s in SCENARIOS if s not in ('stationary', 'abrupt', 'delayed'))


def criteria(summary: dict, online: dict | None) -> dict:
    s = summary['summary']
    g = lambda sc, k: s[sc][CAND][k]
    res = {'A_stationary_noninferior_v06': g('stationary', 'diff_unique_false_pass_vs_CAVER-v0.6_ci')[0] > -0.5}
    for sc in ('abrupt', 'delayed'):
        res[f'B_{sc}_better_than_v06'] = g(sc, 'diff_unique_false_pass_vs_CAVER-v0.6_ci')[0] > 0
        res[f'B_{sc}_close_to_ucb1'] = g(sc, 'diff_unique_false_pass_vs_UCB1_ci')[0] > -0.5
        res[f'C_{sc}_faster_recovery_than_v06'] = g(sc, 'diff_recovery_steps_vs_CAVER-v0.6_ci')[1] < 0
    for sc in OTHER:
        res[f'D_{sc}_noninferior_v06'] = g(sc, 'diff_unique_false_pass_vs_CAVER-v0.6_ci')[0] > -0.5
    for sc in SCENARIOS:
        for ref in ('Random', 'SW-UCB', 'D-UCB'):
            res[f'E_{sc}_beats_{ref}'] = g(sc, f'diff_unique_false_pass_vs_{ref}_ci')[0] > 0
    f = online['summary']['criterion_F_replay_validity'] if online else 'NOT_EVALUATED'
    replay_ok = all(res.values())
    if not replay_ok or f == 'FAIL':
        decision = '채택 보류 (adoption on hold); CAVER v0.6 remains recommended'
    elif f == 'PASS':
        decision = 'replay-confirmed (all replay criteria pass; live table agreement observed)'
    else:
        decision = 'replay-confirmed (replay-only; live pilot not evaluated)'
    return {'candidate': CAND, 'replay_criteria': res, 'replay_failed': [k for k, v in res.items() if not v],
            'criterion_F': f, 'n_checks': len(res) + 1, 'decision': decision}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--holdout', type=Path, default=ROOT / 'reports/v09c/holdout_real/primary/summary.json')
    p.add_argument('--online', type=Path, default=ROOT / 'reports/v09c/online/summary.json')
    p.add_argument('--output', type=Path, default=ROOT / 'reports/v09c/verdict.json')
    a = p.parse_args(argv)
    online = json.loads(a.online.read_text()) if a.online.exists() else None
    v = criteria(json.loads(a.holdout.read_text()), online)
    a.output.write_text(json.dumps(v, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: v[k] for k in ('replay_failed', 'criterion_F', 'decision')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
