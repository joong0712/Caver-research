"""Tests for caver10.adaptive (Agent B, v0.10) and its dev runner. Dev salt only (v010dev)."""
import json
import math
import random
import unittest
from dataclasses import asdict
from pathlib import Path

from caver5.fixtures import FAMILIES
from caver8.benchmark import OutcomeTable
from caver9 import evaluation as ev
from caver9.exploration import UCBMeanCAVER
import caver9c.confirm as cf
from caver10 import adaptive as ad
from caver10 import agent_b_dev as dev

ROOT = Path(__file__).resolve().parents[1]
SALT = dev.DEV_SALT
TABLE = OutcomeTable(json.loads((ROOT / 'reports/v08/outcome_table_real.json').read_text(encoding='utf-8')))
ALL = (ad.AdaptiveCUCB,) + ad.CANDIDATES


def run(cls, seed, scenario):
    train, hold, sd = dev.build_schedule(SALT, seed, scenario)
    return ev.run_one(cls, SALT, seed, scenario, TABLE, train, hold, sd, cpu_timing=False)


def strip(r):
    d = asdict(r)
    d.pop('policy')
    return d


def disabled(cls):
    return type(cls.__name__ + 'Off', (cls,), {'ADAPT': False, 'name': cls.name + '-off'})


class _RestoreSalts(unittest.TestCase):
    def setUp(self):
        orig = cf.ALLOWED_SALTS
        self.addCleanup(setattr, cf, 'ALLOWED_SALTS', orig)


class TestReproducesC2(_RestoreSalts):
    SCEN = ('stationary', 'abrupt', 'c_uniform', 'c_reverse')

    def test_base_equals_c2(self):
        for sc in self.SCEN:
            for seed in range(3):
                self.assertEqual(strip(run(UCBMeanCAVER, seed, sc)), strip(run(ad.AdaptiveCUCB, seed, sc)), (sc, seed))

    def test_each_candidate_with_adaptation_disabled_equals_c2(self):
        for cls in ad.CANDIDATES:
            off = disabled(cls)
            for sc in ('stationary', 'delayed'):
                for seed in range(2):
                    self.assertEqual(strip(run(UCBMeanCAVER, seed, sc)), strip(run(off, seed, sc)), (cls.name, sc))

    def test_adaptation_changes_behaviour(self):
        for cls in ad.CANDIDATES:
            diff = any(strip(run(UCBMeanCAVER, s, 'stationary')) != strip(run(cls, s, 'stationary')) for s in range(3))
            self.assertTrue(diff, cls.name)

    def test_instrumentation_preserves_behaviour(self):
        for cls in ad.CANDIDATES:
            holder = []
            a = run(cls, 1, 'delayed')
            b = run(dev.instrumented(cls, holder), 1, 'delayed')
            self.assertEqual(asdict(a), asdict(b))
            self.assertEqual(len(holder), 1)
            self.assertEqual(holder[0].coef_n, 90)


class TestDeterminism(_RestoreSalts):
    def test_same_seed_same_run(self):
        for cls in ad.CANDIDATES:
            for sc in ('stationary', 'abrupt', 'c_oscillate'):
                self.assertEqual(asdict(run(cls, 4, sc)), asdict(run(cls, 4, sc)))

    def test_parallel_equals_serial(self):
        a = dev.evaluate(seeds=range(2), scenarios=('abrupt',), jobs=1)
        b = dev.evaluate(seeds=range(2), scenarios=('abrupt',), jobs=2)
        strip_cpu = lambda rs: [{k: v for k, v in r.items() if k != 'cpu_us_per_probe'} for r in rs]
        self.assertEqual(strip_cpu(a['runs']), strip_cpu(b['runs']))


class TestFormulas(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((ad.AdaptiveCUCB.REGIME_M, ad.AdaptiveCUCB.CUSUM_RHO, ad.AdaptiveCUCB.CUSUM_H,
                          ad.AdaptiveCUCB.P0_FLOOR, ad.AdaptiveCUCB.C), (10, 0.3, 2.0, 0.02, 0.5))
        self.assertEqual((ad.EvidenceUCB.C_LO, ad.EvidenceUCB.C_HI), (0.25, 0.75))
        self.assertEqual(ad.VarUCB.C_V, 0.75)
        self.assertEqual((ad.HybridUCB.S_LO, ad.HybridUCB.S_HI), (0.40, 1.10))
        self.assertFalse(ad.AdaptiveCUCB.ADAPT)
        self.assertTrue(all(c.ADAPT for c in ad.CANDIDATES))
        self.assertEqual(len({c.name for c in ALL}), len(ALL))
        self.assertTrue(2 <= len(ad.CANDIDATES) <= 3)

    def _trained(self, cls, hits=0.2, n=90, seed=0):
        p = cls(random.Random(seed))
        r = random.Random(seed + 1)
        for i in range(n):
            c = f't{i % 30}'
            a = p.select(c)
            p.update(c, a, r.random() < 0.3, r.random() < hits)
        return p

    def test_evidence_schedule(self):
        p = self._trained(ad.EvidenceUCB)
        p.begin_evaluation()
        p.detector.observe = lambda fam, violated: False
        self.assertEqual(p.tau, 0)
        self.assertAlmostEqual(p.coef(FAMILIES[0]), 0.75)
        for i in range(10):
            a = p.select(f'e{i}')
            p.update(f'e{i}', a, False, True)          # hits: no CUSUM alarm
        self.assertEqual(p.tau, 10)
        self.assertAlmostEqual(p.coef(FAMILIES[0]), 0.5)
        self.assertTrue(all(abs(p.coef(f) - 0.5) < 1e-12 for f in FAMILIES))   # global

    def test_var_and_hybrid_formula(self):
        for cls in (ad.VarUCB, ad.HybridUCB):
            p = self._trained(cls)
            p.begin_evaluation()
            for f in FAMILIES:
                m = p.posterior_mean(f)
                v = 2 * math.sqrt(m * (1 - m))
                want = 0.75 * v if cls is ad.VarUCB else v * (0.40 + 0.70 * p.regime_uncertainty())
                self.assertAlmostEqual(p.coef(f), want)
                n = p.counts[f]
                self.assertAlmostEqual(p.score(f), m + want * math.sqrt(2 * math.log(max(2, p.t)) / n))

    def test_cusum_triggers_on_misses_and_resets(self):
        p = self._trained(ad.EvidenceUCB, hits=0.2)
        p.begin_evaluation()
        p.detector.observe = lambda fam, violated: False         # isolate the CUSUM
        p0 = p.p0
        miss = math.log((1 - 0.3 * p0) / (1 - p0))
        need = math.ceil(2.0 / miss - 1e-12)
        fired_at = None
        for i in range(200):
            c = f'e{i}'
            a = p.select(c)
            p.update(c, a, False, False)
            if p.events[-1][0] == 'cusum':
                fired_at = i + 1
                break
        self.assertEqual(fired_at, need)
        self.assertEqual((p.tau, p.cusum), (0, 0.0))
        self.assertAlmostEqual(p.coef(FAMILIES[0]), 0.75)
        a = p.select('x')
        p.update('x', a, False, True)                  # a hit lowers S (floored at 0)
        self.assertEqual(p.cusum, 0.0)

    def test_cusum_inactive_in_training_and_p0_floor(self):
        p = self._trained(ad.EvidenceUCB, hits=0.0)
        self.assertEqual(p.cusum, 0.0)
        self.assertEqual(p.events, [])
        p.begin_evaluation()
        self.assertEqual(p.p0, 0.02)

    def test_detector_alarm_is_an_evidence_event(self):
        p = self._trained(ad.HybridUCB)
        p.begin_evaluation()
        for i in range(5):
            a = p.select(f'e{i}')
            p.update(f'e{i}', a, False, True)
        p.detector.observe = lambda fam, violated: True          # force one confirmed alarm
        a = p.select('z')
        p.update('z', a, True, False)
        self.assertEqual(p.events[-1][0], 'alarm')
        self.assertEqual(p.tau, 0)
        self.assertEqual(p.counts[a], 1)                            # C2's local reset kept

    def test_select_respects_per_case_exhaustion(self):
        for cls in ALL:
            p = cls(random.Random(0))
            chosen = []
            for _ in range(len(FAMILIES)):
                arm = p.select('c1')
                self.assertNotIn(arm, chosen, cls.name)
                chosen.append(arm)
                p.update('c1', arm, False, False)
            self.assertEqual(sorted(chosen), sorted(FAMILIES))
            self.assertIn(p.select('c1'), FAMILIES)


class TestInformationHygiene(_RestoreSalts):
    def test_update_receives_only_str_str_bool_bool(self):
        for cls in ad.CANDIDATES:
            calls = []

            class Spy(cls):
                name = cls.name

                def update(self, *args, **kw):
                    calls.append((args, kw))
                    return super().update(*args, **kw)
            run(Spy, 0, 'abrupt')
            self.assertEqual(len(calls), 180)
            for args, kw in calls:
                self.assertEqual(len(args), 4)
                self.assertEqual(set(kw), {'learn'})
                cid, arm, violated, new = args
                self.assertIsInstance(cid, str)
                self.assertRegex(cid, r'^c\d{3}$')      # opaque case id, no cohort/salt
                self.assertIn(arm, FAMILIES)
                self.assertIs(type(violated), bool)
                self.assertIs(type(new), bool)

    def test_no_outcome_side_channel(self):
        for cls in ALL:
            self.assertFalse(hasattr(cls, 'observe_outcome'), cls.name)


class TestDevRunner(_RestoreSalts):
    def test_refuses_other_salts(self):
        for bad in ('v09dev', 'v09c-holdout', 'v010final', 'dev', 'holdout', 'v010dev,v09dev'):
            with self.assertRaises(ValueError):
                dev.check_salt(bad)
            with self.assertRaises(ValueError):
                dev.build_schedule(bad, 0, 'stationary')
            with self.assertRaises(ValueError):
                dev.evaluate(salt=bad, seeds=range(1), scenarios=('stationary',), jobs=1)

    def test_patch_is_process_local_and_dev_only(self):
        dev._patch_allowed_salts()
        self.assertEqual(cf.ALLOWED_SALTS, frozenset({'v010dev'}))
        with self.assertRaises(ValueError):
            cf.build_schedule('v09c-holdout', 0, 'c_uniform')

    def test_jobs_capped(self):
        with self.assertRaises(ValueError):
            dev.evaluate(seeds=range(1), scenarios=('stationary',), jobs=3)

    def test_budget_and_scenarios(self):
        self.assertEqual(len(dev.SCENARIOS), 12)
        self.assertEqual(set(dev.ABRUPT_TYPE) | set(dev.STATIONARY_TYPE) | set(dev.FLAT_SHIFT) <= set(dev.SCENARIOS), True)
        train, hold, _ = dev.build_schedule(SALT, 0, 'c_uniform')
        self.assertEqual((len(train), len(hold)), (90, 90))

    def test_km_median(self):
        self.assertEqual(dev.km_median([(1, False), (2, False), (3, False)]), 2.0)
        self.assertIsNone(dev.km_median([(5, True), (5, True), (2, False)]))
        self.assertEqual(dev.km_median([(1, False), (4, True), (2, False), (3, False)]), 2.0)


class TestSelectionRule(unittest.TestCase):
    def _summary(self, good: bool):
        S = {}
        refs = (dev.V06, dev.C2, 'Random', 'SW-UCB', 'D-UCB', 'UCB1')
        for sc in dev.SCENARIOS:
            block = {}
            for n in ('X', 'Y', dev.V06):
                m = {'false_alarm_rate': 0.1 if sc != 'abrupt' else None}
                for r in refs:
                    m[f'diff_unique_false_pass_vs_{r}'] = 0.5
                    m[f'diff_unique_false_pass_vs_{r}_ci'] = [0.1, 0.9]
                    m[f'diff_recovery_steps_vs_{r}'] = -1.0
                    m[f'diff_recovery_steps_vs_{r}_ci'] = [-2.0, -0.5]
                block[n] = m
            if not good:
                block['Y'][f'diff_unique_false_pass_vs_{dev.C2}_ci'] = [-0.1, 0.4] if sc == 'stationary' else [0.1, 0.9]
            S[sc] = block
        return S

    def test_rule_nominates_and_rejects(self):
        sel = dev.apply_rule(self._summary(True), ['X', 'Y'])
        self.assertIn(sel['nominated'], ('X', 'Y'))
        sel = dev.apply_rule(self._summary(False), ['X', 'Y'])
        self.assertEqual(sel['nominated'], 'X')
        self.assertFalse(sel['per_candidate']['Y']['eligible'])
        self.assertEqual([c['id'] for c in sel['per_candidate']['Y']['failed']], ['S2'])

    def test_rule_none_eligible(self):
        S = self._summary(False)
        for sc in S:
            S[sc]['X'][f'diff_recovery_steps_vs_{dev.C2}_ci'] = [0.0, 2.0]
        sel = dev.apply_rule(S, ['X', 'Y'])
        self.assertIsNone(sel['nominated'])
        self.assertEqual(sel['closest_if_none'], 'Y')


if __name__ == '__main__':
    unittest.main()
