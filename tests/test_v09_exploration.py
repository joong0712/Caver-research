"""Tests for caver9.exploration (Agent C) and its dev harness. Uses a test-only salt."""
import json
import math
import random
import unittest
from dataclasses import asdict
from pathlib import Path

from caver5.fixtures import FAMILIES
from caver6.policies import CAVERv06
from caver8.benchmark import OutcomeTable, schedules, run_policy, SCENARIOS
from caver9 import exploration as ex
from caver9 import agent_c_dev as dev

ROOT = Path(__file__).resolve().parents[1]
SALT = 'v09ctest'
TABLE = OutcomeTable(json.loads((ROOT / 'reports/v08/outcome_table_real.json').read_text(encoding='utf-8')))
EVERY = ex.ALL + ex.POST_HOC


def run(cls, seed, scenario):
    train, hold, change_at = schedules(SALT, seed, scenario)
    return run_policy(cls, SALT, seed, scenario, TABLE, train, hold, change_at)


def strip(r):
    d = asdict(r)
    d.pop('policy')
    return d


class TestReproducesV06(unittest.TestCase):
    def test_default_configuration_equals_caver_v06(self):
        for sc in SCENARIOS:
            for seed in range(3):
                self.assertEqual(strip(run(CAVERv06, seed, sc)), strip(run(ex.ExploreCAVER, seed, sc)), (sc, seed))

    def test_instrumentation_preserves_behaviour(self):
        for cls in (CAVERv06, ex.UCBMeanCAVER, ex.RecencyCAVER):
            holder = []
            a = run(cls, 1, 'delayed')
            b = run(dev.instrument(cls, holder), 1, 'delayed')
            self.assertEqual(asdict(a), asdict(b))
            self.assertEqual(len(holder[0]._arms), 180)


class TestMechanisms(unittest.TestCase):
    def test_names_unique_and_constants(self):
        names = [c.name for c in EVERY]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(ex.CANDIDATES), 3)
        self.assertEqual((ex.RecencyCAVER.FREQ_WEIGHT, ex.RecencyCAVER.STALE_WEIGHT,
                          ex.RecencyCAVER.STALE_HORIZON, ex.RecencyCAVER.FREQ_DECAY), (0.12, 0.08, 30, 0.9))
        self.assertEqual(ex.UCBMeanCAVER.C, 0.5)
        self.assertEqual((ex.AdaptiveEpsCAVER.EPS_MIN, ex.AdaptiveEpsCAVER.EPS_MAX,
                          ex.AdaptiveEpsCAVER.YIELD_DECAY), (0.03, 0.25, 0.95))
        self.assertEqual((ex.UCBMean025.C, ex.UCBMean100.C, ex.FixedEps10CAVER.EPS), (0.25, 1.0, 0.10))

    def test_select_respects_per_case_exhaustion(self):
        for cls in EVERY:
            p = cls(random.Random(0))
            chosen = []
            for _ in range(len(FAMILIES)):
                arm = p.select('c1')
                self.assertNotIn(arm, chosen, cls.name)
                chosen.append(arm)
                p.update('c1', arm, False, False)
            self.assertEqual(sorted(chosen), sorted(FAMILIES))
            self.assertIn(p.select('c1'), FAMILIES)   # all exhausted: repeat allowed

    def test_ucbmean_untested_first_and_formula(self):
        p = ex.UCBMeanCAVER(random.Random(0))
        seen = set()
        for i in range(len(FAMILIES)):
            arm = p.select(f'c{i}')
            self.assertNotIn(arm, seen)
            seen.add(arm)
            p.update(f'c{i}', arm, True, arm == FAMILIES[0])
        f = FAMILIES[0]
        expect = 2 / 3 + 0.5 * math.sqrt(2 * math.log(6) / 1)
        self.assertAlmostEqual(p.score(f), expect)
        p.counts[f] = 0
        self.assertEqual(p.score(f), float('inf'))

    def test_ucb_bonus_grows_for_neglected_arm(self):
        p = ex.UCBMeanCAVER(random.Random(0))
        for f in FAMILIES:
            p.update('x', f, False, False)
        before = p.score(FAMILIES[5])
        for i in range(50):
            p.update(f'y{i}', FAMILIES[0], False, False)
        self.assertGreater(p.score(FAMILIES[5]), before)

    def test_recency_terms(self):
        p = ex.RecencyCAVER(random.Random(0))
        self.assertAlmostEqual(p.freq_deficit(FAMILIES[0]), 0.0)
        for i in range(30):
            p.update(f'c{i}', FAMILIES[0], False, False)
        self.assertAlmostEqual(p.freq_deficit(FAMILIES[3]), 1 - 6 * (1 / 6) * 0.9 ** 30)
        self.assertEqual(p.freq_deficit(FAMILIES[0]), 0.0)
        self.assertEqual(p.staleness(FAMILIES[3], 30), 1.0)
        self.assertEqual(p.staleness(FAMILIES[0], 30), 0.0)
        bonus = p.extra_bonus(FAMILIES[3])
        self.assertAlmostEqual(bonus, 0.12 * p.freq_deficit(FAMILIES[3]) + 0.08)
        self.assertEqual(ex.ExploreCAVER(random.Random(0)).extra_bonus(FAMILIES[0]), 0.0)

    def test_adaptive_epsilon(self):
        p = ex.AdaptiveEpsCAVER(random.Random(0))
        for i in range(20):
            p.update(f't{i}', FAMILIES[i % 6], True, i % 4 == 0)   # train yield 0.25
        p.begin_evaluation()
        self.assertAlmostEqual(p.yield_train, 0.25)
        self.assertAlmostEqual(p.epsilon(), 0.03)
        for i in range(40):
            p.update(f'e{i}', FAMILIES[i % 6], False, False)
        drop = 1 - (0.25 * 0.95 ** 40) / 0.25
        self.assertAlmostEqual(p.epsilon(), 0.03 + 0.22 * drop)
        self.assertLessEqual(p.epsilon(), 0.25)
        p.yield_recent = 0.25
        p.post_change_steps = 5
        self.assertEqual(p.epsilon(), 0.18)

    def test_fixed_eps_and_epsilon_only_in_evaluation(self):
        p = ex.FixedEps10CAVER(random.Random(0))
        p.post_change_steps = 10
        self.assertEqual(p.epsilon(), 0.10)
        q = ex.UCBMeanCAVER(random.Random(0))
        self.assertEqual(q.epsilon(), 0.0)
        self.assertFalse(q.SENTINEL)

    def test_local_reset_on_alarm(self):
        p = ex.UCBMeanCAVER(random.Random(0))
        f = FAMILIES[1]
        for i in range(10):
            p.update(f't{i}', f, False, False)
        p.begin_evaluation()
        for i in range(8):
            p.update(f'e{i}', f, True, False)
        self.assertEqual(p.alarm_count, 1)
        self.assertEqual(p.reset_log[0]['family'], f)
        self.assertLess(p.counts[f], 18)

    def test_silent_detector_never_alarms(self):
        p = ex.PHUCBMeanNoReset(random.Random(0))
        for i in range(10):
            p.update(f't{i}', FAMILIES[1], False, False)
        p.begin_evaluation()
        for i in range(10):
            p.update(f'e{i}', FAMILIES[1], True, False)
        self.assertEqual(p.alarm_count, 0)
        self.assertTrue(p.detector.in_evaluation)


class TestInformationHygiene(unittest.TestCase):
    def test_update_receives_only_str_str_bool_bool(self):
        for base in (ex.RecencyCAVER, ex.UCBMeanCAVER, ex.AdaptiveEpsCAVER):
            calls = {'select': [], 'update': []}

            class Spy(base):
                name = base.name

                def __init__(self, rng, *extra, **kw):
                    assert not extra and not kw and isinstance(rng, random.Random)
                    super().__init__(rng)

                def select(self, *args, **kw):
                    calls['select'].append((args, kw))
                    return super().select(*args, **kw)

                def update(self, *args, **kw):
                    calls['update'].append((args, kw))
                    return super().update(*args, **kw)

            run(Spy, 0, 'abrupt')
            self.assertEqual(len(calls['update']), 180)
            for args, kw in calls['select']:
                self.assertEqual(kw, {})
                self.assertEqual(len(args), 1)
                self.assertIs(type(args[0]), str)
            for args, kw in calls['update']:
                self.assertEqual(len(args), 4, base.name)
                self.assertEqual([type(a) for a in args], [str, str, bool, bool], base.name)
                self.assertIn(args[1], FAMILIES)
                self.assertEqual(set(kw), {'learn'})
                self.assertIs(kw['learn'], True)

    def test_no_hidden_state_reaches_policy(self):
        holder = []
        run(dev.instrument(ex.UCBMeanCAVER, holder), 2, 'delayed')
        p = holder[0]
        blob = repr(vars(p))
        for forbidden in ('defects', 'W_SHIFT', 'change_at', 'false_pass', 'Case8', 'healthy'):
            self.assertNotIn(forbidden, blob)
        self.assertFalse(hasattr(p, 'observe_outcome'))


class TestHarness(unittest.TestCase):
    def test_forbidden_salts_refused(self):
        for s in ('v09final', 'dev', 'holdout'):
            with self.assertRaises(ValueError):
                dev.check_salt(s)
            with self.assertRaises(ValueError):
                dev.run_one((s, 0, 'stationary', ['UCB1'], {}))
        dev.check_salt('v09dev')

    def test_entropy_and_caps(self):
        self.assertAlmostEqual(dev.norm_entropy(list(FAMILIES) * 3), 1.0)
        self.assertEqual(dev.norm_entropy([FAMILIES[0]] * 5), 0.0)
        self.assertEqual((dev.recovery_cap('abrupt'), dev.recovery_cap('delayed'), dev.recovery_cap('recovery')),
                         (91, 46, 61))
        self.assertIsNone(dev.recovery_cap('stationary'))

    def test_run_one_rows(self):
        doc = json.loads((ROOT / 'reports/v08/outcome_table_real.json').read_text(encoding='utf-8'))
        rows = dev.run_one((SALT, 0, 'abrupt', ['CAVER-v0.6', 'C9-UCBMean'], doc))
        self.assertEqual([r['policy'] for r in rows], ['CAVER-v0.6', 'C9-UCBMean'])
        for r in rows:
            self.assertGreaterEqual(r['diversity'], 0.0)
            self.assertLessEqual(r['diversity'], 1.0)
            self.assertAlmostEqual(sum(r[f'share_{f}'] for f in
                                       ('schema', 'field_value', 'abnormal_exit', 'timeout', 'matcher',
                                        'exec_mismatch')), 1.0, places=3)
            self.assertIsNotNone(r['recovery_steps_capped'])
        self.assertGreater(rows[0]['sentinel_share'], 0)
        self.assertEqual(rows[1]['sentinel_share'], 0)


if __name__ == '__main__':
    unittest.main()
