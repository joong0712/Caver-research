"""Lead integration, criteria checker and final-verdict regression (no CLI calls, no unsealing)."""
import json
import random
import unittest
from pathlib import Path

from caver5.fixtures import FAMILIES
from caver9.criteria import check
from caver9.integration import DualRewardUCB, BCNoViolation

ROOT = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def test_unprobed_arms_first_and_update_signature(self):
        p = DualRewardUCB(random.Random(0))
        seen = set()
        for i in range(len(FAMILIES)):
            a = p.select(f'c{i}')
            self.assertNotIn(a, seen)
            seen.add(a)
            p.update(f'c{i}', a, False, False)
        self.assertEqual(seen, set(FAMILIES))

    def test_ablation_ignores_violation_model(self):
        a, b = BCNoViolation(random.Random(1)), BCNoViolation(random.Random(1))
        for i, f in enumerate(FAMILIES * 3):
            a.update(f'c{i}', f, True, False)
            b.update(f'c{i}', f, False, False)
        self.assertEqual([a.score(f) for f in FAMILIES], [b.score(f) for f in FAMILIES])


def _summary(over=None):
    base = {'diff_unique_false_pass_vs_CAVER-v0.6_ci': [0.1, 0.5], 'diff_unique_false_pass_vs_UCB1_ci': [0.0, 0.4],
            'diff_recovery_steps_vs_CAVER-v0.6_ci': [-3.0, -1.0]}
    s = {sc: {'P': dict(base)} for sc in ('stationary', 'abrupt', 'delayed', 'recovery', 'gradual')}
    for (sc, k), v in (over or {}).items():
        s[sc]['P'][k] = v
    return {'summary': s}


class CriteriaTests(unittest.TestCase):
    def test_all_pass(self):
        self.assertTrue(check(_summary(), 'P')['all_pass'])

    def test_recovery_ci_touching_zero_fails(self):
        r = check(_summary({('abrupt', 'diff_recovery_steps_vs_CAVER-v0.6_ci'): [-2.9, 0.01]}), 'P')
        self.assertEqual(r['failed'], ['3_abrupt_faster_recovery_than_v06'])

    def test_stationary_margin(self):
        r = check(_summary({('stationary', 'diff_unique_false_pass_vs_CAVER-v0.6_ci'): [-0.51, 0.2]}), 'P')
        self.assertIn('1_stationary_noninferior_v06', r['failed'])


class FinalVerdictRegression(unittest.TestCase):
    def test_committed_final_verdict(self):
        doc = json.loads((ROOT / 'reports/v09/final_real/summary.json').read_text())
        self.assertEqual(check(doc, 'B-DR-Bayes')['failed'], ['3_abrupt_faster_recovery_than_v06'])
        self.assertTrue(check(doc, 'C9-UCBMean')['all_pass'])

    def test_final_salt_unsealed_exactly_twice_with_frozen_commit(self):
        log = [json.loads(x) for x in (ROOT / 'reports/v09/final_unseal_log.jsonl').read_text().splitlines()]
        self.assertEqual(len(log), 2)
        self.assertEqual({e['git_commit'][:7] for e in log}, {'2584d6a'})


if __name__ == '__main__':
    unittest.main()
