"""v0.8 algorithms and benchmark: detector behaviour, information hygiene, determinism."""
import csv
import json
import random
import unittest
from pathlib import Path

from caver5.fixtures import FAMILIES
from caver8 import benchmark as bm
from caver8.policies import (GLRConfidenceDetector, ConfidenceGated, RiskAware, ConfGatedRiskAware,
                             TemperedV06, SEV_FALSE_PASS, SEV_CONTRACT_VIOLATION)

ROOT = Path(__file__).resolve().parents[1]
TABLE = json.loads((ROOT / 'reports/v08/outcome_table_simulated.json').read_text())
F = FAMILIES[0]


def _train(det, p, n, rng):
    for _ in range(n):
        det.observe(F, rng.random() < p)
    det.begin_evaluation()


class DetectorTests(unittest.TestCase):
    def test_glr_quiet_on_stationary_stream(self):
        alarms = 0
        for seed in range(50):
            rng = random.Random(seed)
            det = GLRConfidenceDetector()
            _train(det, 0.3, 30, rng)
            alarms += any(det.observe(F, rng.random() < 0.3) for _ in range(150))
        self.assertLessEqual(alarms, 3)  # delta = 0.05 per stream

    def test_glr_detects_large_abrupt_change_and_rebaselines(self):
        rng = random.Random(1)
        det = GLRConfidenceDetector()
        _train(det, 0.05, 30, rng)
        fired = [det.observe(F, rng.random() < 0.95) for _ in range(30)]
        self.assertTrue(any(fired))
        self.assertGreater(det.baseline[F][1] / det.baseline[F][0], 0.5)

    def test_threshold_grows_with_n(self):
        det = GLRConfidenceDetector()
        self.assertLess(det.threshold(10), det.threshold(100))


class PolicyTests(unittest.TestCase):
    def test_severity_reward_values(self):
        for fp, viol, expect in ((True, True, SEV_FALSE_PASS), (False, True, SEV_CONTRACT_VIOLATION),
                                 (False, False, 0.0)):
            p = RiskAware(random.Random(0))
            before = p.successes[F]
            p.observe_outcome(false_pass=fp, violated=viol, new_defect=viol)
            p.update('c1', F, viol, False)
            self.assertAlmostEqual(p.successes[F] - before, expect)
            self.assertAlmostEqual(p.successes[F] + p.failures[F], 1.0)

    def test_a_and_ab_use_glr_detector(self):
        for cls in (ConfidenceGated, ConfGatedRiskAware):
            self.assertIsInstance(cls(random.Random(0)).detector, GLRConfidenceDetector)

    def test_tempering_scales_training_posterior(self):
        p = TemperedV06(random.Random(0))
        for _ in range(10):
            p.update('c', F, True, True)
        s = p.successes[F]
        p.begin_evaluation()
        self.assertAlmostEqual(p.successes[F], s * TemperedV06.TAU)


class Spy:
    name = 'Spy'
    calls = []

    def __init__(self, rng):
        self.rng = rng

    def select(self, case_id):
        Spy.calls.append(('select', type(case_id)))
        return self.rng.choice(FAMILIES)

    def update(self, *args, **kw):
        Spy.calls.append(('update', tuple(type(a) for a in args)))


class BenchmarkTests(unittest.TestCase):
    def test_policies_receive_only_ids_arms_and_observations(self):
        table = bm.OutcomeTable(TABLE)
        train, hold, change = bm.schedules('dev', 0, 'delayed')
        bm.run_policy(Spy, 'dev', 0, 'delayed', table, train, hold, change)
        kinds = {c[1] for c in Spy.calls}
        self.assertEqual(kinds, {str, (str, str, bool, bool)})

    def test_dev_and_holdout_are_disjoint_and_deterministic(self):
        a = {c.id for c in bm.make_cases('dev', 3, 'train', bm.W_BASE)}
        b = {c.id for c in bm.make_cases('holdout', 3, 'train', bm.W_BASE)}
        self.assertFalse(a & b)
        self.assertEqual(bm.make_cases('dev', 3, 'x', bm.W_SHIFT), bm.make_cases('dev', 3, 'x', bm.W_SHIFT))

    def test_table_must_be_complete_and_kind_is_propagated(self):
        bad = {'meta': TABLE['meta'], 'rows': TABLE['rows'][:5]}
        with self.assertRaises(ValueError):
            bm.OutcomeTable(bad)
        rep = bm.benchmark(TABLE, 'dev', range(2), ('stationary',), ['Random'], jobs=1)
        self.assertEqual(rep['meta']['outcome_table_cli_kind'], 'simulated')
        self.assertFalse(rep['meta']['real_claude_code_executed_for_table'])

    def test_regression_against_committed_dev_round1(self):
        committed = [r for r in csv.DictReader(open(ROOT / 'reports/v08/dev_round1/runs.csv'))
                     if r['seed'] in ('0', '7') and r['scenario'] == 'recovery']
        names = [c.name for c in bm.POLICIES]
        fresh = bm.benchmark(TABLE, 'dev', (0, 7), ('recovery',), names, jobs=1)['runs']
        key = lambda r: (str(r['seed']), r['policy'])
        got = {key(r): (str(r['unique_defects']), str(r['unique_false_pass'])) for r in fresh}
        for r in committed:
            self.assertEqual(got[key(r)], (r['unique_defects'], r['unique_false_pass']), key(r))


if __name__ == '__main__':
    unittest.main()
