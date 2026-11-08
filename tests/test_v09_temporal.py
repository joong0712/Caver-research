"""Agent A (v0.9 temporal adaptation): unit + information-hygiene tests.

Uses the mechanics-only salt `v09a-unittest`; no performance numbers are read.
"""
import json
import math
import random
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caver5.fixtures import FAMILIES
from caver5.policies import BasePolicy
from caver6.policies import CAVERv06
from caver8.benchmark import OutcomeTable, schedules, run_policy
from caver9.temporal import (TemporalV06Base, DecayGM, DecayFast, AlarmShrink, DiscountedUCB,
                             GM_GAMMA, CANDIDATES)
from caver9 import agent_a_dev

ROOT = Path(__file__).resolve().parents[1]
SALT = 'v09a-unittest'
TABLE = OutcomeTable(json.loads((ROOT / 'reports/v08/outcome_table_real.json').read_text(encoding='utf-8')))
ALL = CANDIDATES + (DiscountedUCB, TemporalV06Base)


def run(cls, seed=0, scenario='abrupt'):
    train, hold, change_at = schedules(SALT, seed, scenario)
    return asdict(run_policy(cls, SALT, seed, scenario, TABLE, train, hold, change_at))


class TestConstants(unittest.TestCase):
    def test_predeclared_constants(self):
        self.assertAlmostEqual(GM_GAMMA, 1 - 0.25 * math.sqrt(1 / 180))
        self.assertAlmostEqual(DecayGM.decay_gamma, 0.981366, places=6)
        self.assertEqual(DecayFast.decay_gamma, 0.95)
        self.assertEqual(AlarmShrink.alarm_shrink, 0.2)
        self.assertEqual(AlarmShrink.decay_gamma, 1.0)
        # Regression (dev run 1): the constant must survive __init__ on the instance.
        for cls, g in ((DecayGM, GM_GAMMA), (DecayFast, 0.95), (AlarmShrink, 1.0)):
            self.assertEqual(cls(random.Random(0)).decay_gamma, g)
        self.assertIsNone(DecayGM.alarm_shrink)
        self.assertEqual((DiscountedUCB.gamma, DiscountedUCB.xi, DiscountedUCB.B), (GM_GAMMA, 0.6, 1.0))
        self.assertLessEqual(len(CANDIDATES), 3)

    def test_unique_names(self):
        names = [c.name for c in agent_a_dev.POLICIES]
        self.assertEqual(len(names), len(set(names)))


class TestEquivalenceToV06(unittest.TestCase):
    def test_base_reproduces_v06_run_for_run(self):
        for scenario in ('stationary', 'abrupt', 'delayed', 'recovery'):
            for seed in (0, 1):
                a, b = run(CAVERv06, seed, scenario), run(TemporalV06Base, seed, scenario)
                a.pop('policy'), b.pop('policy')
                self.assertEqual(a, b, (scenario, seed))

    def test_decay_candidates_actually_differ_from_v06(self):
        # Regression for dev run 1, where a shadowed gamma made A1/A2 exact v0.6 copies.
        for cls in (DecayGM, DecayFast):
            p, q = cls(random.Random(0)), CAVERv06(random.Random(0))
            for i in range(5):
                for x in (p, q):
                    x.update(f'c{i}', FAMILIES[i % 2], violated=False, newly_found=False)
            self.assertLess(p.failures[FAMILIES[0]], q.failures[FAMILIES[0]])

    def test_recording_wrapper_is_transparent(self):
        for cls in (CAVERv06, DecayGM, DiscountedUCB):
            train, hold, change_at = schedules(SALT, 3, 'delayed')
            a = asdict(run_policy(cls, SALT, 3, 'delayed', TABLE, train, hold, change_at))
            W = agent_a_dev.recorded(cls, change_at)
            b = asdict(run_policy(W, SALT, 3, 'delayed', TABLE, train, hold, change_at))
            self.assertEqual(a, b)
            self.assertEqual(len(W.last.arms), 90)
            self.assertEqual(W.last.calls, 180)


class TestDecayMechanics(unittest.TestCase):
    def test_continuous_decay_scales_all_families(self):
        p = DecayFast(random.Random(0))
        for f in FAMILIES:
            p.successes[f], p.failures[f], p.counts[f] = 2.0, 8.0, 10.0
        p.update('c0', FAMILIES[0], violated=True, newly_found=True)
        self.assertAlmostEqual(p.successes[FAMILIES[0]], 2 * 0.95 + 1)
        self.assertAlmostEqual(p.failures[FAMILIES[0]], 8 * 0.95)
        for f in FAMILIES[1:]:
            self.assertAlmostEqual(p.successes[f], 1.9)
            self.assertAlmostEqual(p.failures[f], 7.6)
            self.assertAlmostEqual(p.counts[f], 9.5)

    def test_no_decay_when_frozen(self):
        p = DecayFast(random.Random(0))
        p.update('c0', FAMILIES[1], violated=False, newly_found=False)
        before = dict(p.failures)
        p.update('c1', FAMILIES[2], violated=True, newly_found=True, learn=False)
        self.assertEqual(before, p.failures)
        self.assertIn(FAMILIES[2], p.visited['c1'])   # exhaustion bookkeeping still applies

    def test_alarm_shrink_only_on_alarm(self):
        p = AlarmShrink(random.Random(0))
        for f in FAMILIES:
            p.successes[f], p.failures[f], p.counts[f] = 5.0, 5.0, 10.0
        p.detector.observe = lambda fam, v: False
        p.update('c0', FAMILIES[0], violated=False, newly_found=False)
        self.assertEqual(p.failures[FAMILIES[1]], 5.0)
        p.detector.observe = lambda fam, v: True
        p.update('c1', FAMILIES[0], violated=True, newly_found=True)
        self.assertEqual((p.successes[FAMILIES[0]], p.failures[FAMILIES[0]], p.counts[FAMILIES[0]]), (1.0, 0.0, 1))
        for f in FAMILIES[1:]:
            self.assertAlmostEqual(p.failures[f], 1.0)
            self.assertAlmostEqual(p.counts[f], 2.0)
        self.assertEqual(len(p.shrink_log), 1)
        self.assertEqual(p.post_change_steps, 36)


class TestDiscountedUCB(unittest.TestCase):
    def test_untested_first_and_index(self):
        p = DiscountedUCB(random.Random(0))
        chosen = set()
        for i in range(6):
            arm = p.select(f'c{i}')
            self.assertNotIn(arm, chosen)
            chosen.add(arm)
            p.update(f'c{i}', arm, violated=(arm == FAMILIES[0]), newly_found=False)
        self.assertEqual(chosen, set(FAMILIES))
        n = sum(p.N.values())
        f = FAMILIES[0]
        expected = p.S[f] / p.N[f] + 2 * math.sqrt(0.6 * math.log(max(2.0, n)) / p.N[f])
        self.assertAlmostEqual(p.index(f), expected)

    def test_discounting(self):
        p = DiscountedUCB(random.Random(0))
        p.update('a', FAMILIES[0], True, False)
        p.update('b', FAMILIES[1], False, False)
        self.assertAlmostEqual(p.N[FAMILIES[0]], GM_GAMMA)
        self.assertAlmostEqual(p.S[FAMILIES[0]], GM_GAMMA)
        self.assertAlmostEqual(p.N[FAMILIES[1]], 1.0)

    def test_respects_case_exhaustion(self):
        p = DiscountedUCB(random.Random(1))
        seen = set()
        for _ in range(6):
            arm = p.select('same')
            self.assertNotIn(arm, seen)
            seen.add(arm)
            p.update('same', arm, False, False)


class TestInformationHygiene(unittest.TestCase):
    """The policy sees only (case_id: str, arm: str, violated: bool, newly_found: bool)."""

    def test_update_and_select_argument_types(self):
        for cls in ALL:
            calls = {'update': 0, 'select': 0}

            class Spy(cls):
                name = cls.name

                def select(self, case_id, *args, **kwargs):
                    assert not args and not kwargs
                    assert type(case_id) is str
                    calls['select'] += 1
                    arm = super().select(case_id)
                    assert arm in FAMILIES
                    return arm

                def update(self, case_id, arm, violated, newly_found, *args, **kwargs):
                    assert not args and set(kwargs) <= {'learn'}
                    assert [type(x) for x in (case_id, arm, violated, newly_found)] == [str, str, bool, bool], \
                        [type(x) for x in (case_id, arm, violated, newly_found)]
                    calls['update'] += 1
                    super().update(case_id, arm, violated, newly_found, **kwargs)

            for scenario in ('abrupt', 'recovery'):
                run(Spy, 0, scenario)
            self.assertEqual(calls, {'update': 360, 'select': 360}, cls.name)

    def test_no_hidden_channels(self):
        for cls in ALL:
            self.assertTrue(issubclass(cls, BasePolicy))
            self.assertFalse(hasattr(cls, 'observe_outcome'), cls.name)
            p = cls(random.Random(0))
            for attr in vars(p):
                self.assertNotIn(attr, {'case', 'cases', 'defects', 'weights', 'change_at', 'table', 'scenario'})

    def test_dev_script_refuses_other_salts(self):
        for bad in ('v09final', 'dev', 'holdout'):
            with self.assertRaises(ValueError):
                agent_a_dev.check_salt(bad)
        agent_a_dev.check_salt('v09dev')


if __name__ == '__main__':
    unittest.main()
