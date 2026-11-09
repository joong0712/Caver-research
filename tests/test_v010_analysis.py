"""v0.10 Agent A: quick tests of the failure-analysis diagnostics (caver10/analysis_a.py).

Dev salt only, a handful of seeds, no CLI calls. Runs in a few seconds.
"""
import json
import random
import tempfile
import unittest
from pathlib import Path

from caver6.policies import CAVERv06
from caver8.benchmark import TRAIN_BUDGET, EVAL_BUDGET
from caver9 import evaluation as ev
from caver9 import exploration as x9
from caver9c import confirm
from caver10 import analysis_a as A

TABLE = A.load_table()


class ScheduleWrapperTests(unittest.TestCase):
    def test_only_dev_salt(self):
        for bad in ('v09dev', 'v09c-holdout', 'v010final', 'dev'):
            with self.assertRaises(ValueError):
                A.dev_schedule(0, 'stationary', bad)
            with self.assertRaises(ValueError):
                A.trace_run(x9.UCBMeanCAVER, 0, 'stationary', TABLE, salt=bad)

    def test_all_12_scenarios_build_with_exact_budget(self):
        self.assertEqual(len(A.SCENARIOS), 12)
        for sc in A.SCENARIOS:
            train, hold, sd = A.dev_schedule(3, sc)
            self.assertEqual((len(train), len(hold)), (TRAIN_BUDGET, EVAL_BUDGET))
            self.assertEqual(sd.name, sc)

    def test_confirm_salt_override_is_restored(self):
        before = confirm.ALLOWED_SALTS
        A.dev_schedule(0, 'c_uniform')
        self.assertIs(confirm.ALLOWED_SALTS, before)
        with self.assertRaises(ValueError):
            confirm.check_salt(A.DEV_SALT, range(1))     # caver9c itself still refuses the dev salt
        with self.assertRaises(RuntimeError):
            with A._confirm_salt_override(A.DEV_SALT):
                raise RuntimeError('boom')
        self.assertIs(confirm.ALLOWED_SALTS, before)

    def test_v09_scenarios_delegate_to_caver9(self):
        a = A.dev_schedule(5, 'gradual')
        b = ev.build_schedule(A.DEV_SALT, 5, 'gradual')
        self.assertEqual([c.id for c in a[0] + a[1]], [c.id for c in b[0] + b[1]])


class TraceFidelityTests(unittest.TestCase):
    def test_trace_equals_run_one(self):
        for sc in ('stationary', 'c_uniform', 'c_reverse', 'abrupt'):
            for seed in (0, 1):
                sched = A.dev_schedule(seed, sc)
                for cls in A.REFERENCES:
                    ref = CAVERv06 if cls is A.V06Ref else cls
                    r9 = ev.run_one(ref, A.DEV_SALT, seed, sc, TABLE, *sched, cpu_timing=False)
                    tr = A.trace_run(cls, seed, sc, TABLE, schedule=sched)['row']
                    for k in ('unique_false_pass', 'unique_defects', 'alarms'):
                        self.assertEqual(getattr(r9, k), tr[k], (cls.name, sc, seed, k))
                    if r9.recovery_steps is not None:
                        self.assertAlmostEqual(r9.recovery_steps, tr['recovery_steps'], places=3)

    def test_arm_terms_do_not_touch_policy_rng(self):
        p = x9.UCBMeanCAVER(random.Random('x'))
        for f in A.ARM_LABELS:
            p.update('c000', f, False, f == 'canonical')
        st = p.rng.getstate()
        for cls in (x9.UCBMeanCAVER, A.V06Ref, A.UCB1Policy, ev.DiscountedUCB):
            q = cls(random.Random('y'))
            q.update('c000', 'canonical', True, True)
            s0 = q.rng.getstate()
            [A.arm_terms(q, f) for f in A.ARM_LABELS]
            self.assertEqual(q.rng.getstate(), s0)
        [A.arm_terms(p, f) for f in A.ARM_LABELS]
        self.assertEqual(p.rng.getstate(), st)

    def test_summary_row_is_consistent(self):
        r = A.trace_run(x9.UCBMeanCAVER, 2, 'delayed', TABLE, signals=True)['row']
        self.assertEqual(r['fp_pre'] + r['fp_post'], r['unique_false_pass'])
        self.assertAlmostEqual(sum(r[f'share_{f}'] for f in A.FAMILIES), 1.0)
        self.assertEqual(r['explore_hits_pre'] + r['greedy_hits_pre'], r['fp_pre'])
        self.assertEqual(r['explore_n_pre'] + r['greedy_n_pre'], r['probes_pre'])
        for cp in A.CHECKPOINTS:
            for s in A.SIGNAL_NAMES:
                self.assertIn(f'sig{cp}_{s}', r)


class DiagnosticClassTests(unittest.TestCase):
    def test_diagnostics_are_labelled_and_not_candidates(self):
        names = [c.name for c in A.DIAGNOSTICS]
        self.assertEqual(len(set(names)), len(names))
        for c in A.DIAGNOSTICS:
            self.assertTrue(c.name.startswith('DIAG-'), c.name)
            self.assertNotIn(c, x9.CANDIDATES)
            self.assertIn('DIAGNOSTIC', c.__doc__)

    def test_c_variants(self):
        self.assertEqual((A.DiagC2Half.C, A.DiagC2Double.C), (x9.UCBMeanCAVER.C / 2, x9.UCBMeanCAVER.C * 2))
        p = A.DiagC2GreedyEval(random.Random(0))
        for f in A.ARM_LABELS:
            p.update('c000', f, False, False)
        self.assertGreater(p.score('canonical'), p.posterior_mean('canonical'))   # training: C = 0.5
        p.begin_evaluation()
        self.assertEqual(p.score('canonical'), p.posterior_mean('canonical'))     # evaluation: C = 0

    def test_frozen_t_bonus_does_not_grow_in_evaluation(self):
        p = A.DiagC2FrozenT(random.Random(0))
        for i in range(12):
            p.update(f'c{i:03d}', A.ARM_LABELS[i % 6], False, False)
        p.begin_evaluation()
        s0 = p.score('canonical')
        p.t += 80                      # time passes without new pulls of 'canonical'
        self.assertEqual(p.score('canonical'), s0)
        q = x9.UCBMeanCAVER(random.Random(0))
        q.counts, q.successes, q.failures, q.t = dict(p.counts), dict(p.successes), dict(p.failures), 12
        q0 = q.score('canonical')
        q.t += 80
        self.assertGreater(q.score('canonical'), q0)

    def test_oracle_equals_c2_when_shift_at_boundary(self):
        for seed in (0, 1):
            a = A.trace_run(A.DiagOracleC, seed, 'abrupt', TABLE)['row']['unique_false_pass']
            b = A.trace_run(x9.UCBMeanCAVER, seed, 'abrupt', TABLE)['row']['unique_false_pass']
            self.assertEqual(a, b)
            a = A.trace_run(A.DiagOracleC, seed, 'stationary', TABLE)['row']['unique_false_pass']
            b = A.trace_run(A.DiagC2EvalC, seed, 'stationary', TABLE)['row']['unique_false_pass']
            self.assertEqual(a, b)

    def test_at_most_two_workers(self):
        with self.assertRaises(ValueError):
            A.run_all(range(1), scenarios=('stationary',), jobs=3)


class StatsAndSignalTests(unittest.TestCase):
    def test_auc(self):
        self.assertEqual(A.auc([2, 3], [0, 1]), 1.0)
        self.assertEqual(A.auc([0, 1], [2, 3]), 0.0)
        self.assertEqual(A.auc([1, 1], [1, 1]), 0.5)
        self.assertAlmostEqual(A.auc([1, 3], [2]), 0.5)
        self.assertIsNone(A.auc([], [1]))

    def test_signals_zero_change_when_profiles_match(self):
        obs = [(f, i % 2 == 0, False) for i, f in enumerate(A.ARM_LABELS * 4)]
        p = x9.UCBMeanCAVER(random.Random(0))
        s = A.regime_signals(obs, list(obs), p, new_case_flags=[1, 0, 0, 0])
        self.assertAlmostEqual(s['viol_chi2'], 0.0)
        self.assertAlmostEqual(s['win_viol_chi2'], 0.0)
        self.assertAlmostEqual(s['win_viol_corr'], 1.0)
        self.assertAlmostEqual(s['recent_new_case_rate'], 0.25)
        flipped = [(f, not v, nf) for f, v, nf in obs]
        self.assertGreater(A.regime_signals(obs, flipped, p)['viol_chi2'], 5)

    def test_yield_profile_abnormal_exit_has_no_false_pass(self):
        prof = A.family_yield_profile(A.confirm.W_UNIFORM, TABLE, n_seeds=3)
        self.assertEqual(prof['fp_yield']['abnormal_exit'], 0.0)
        self.assertGreater(prof['fp_yield']['exec_mismatch'], 0.0)

    def test_main_end_to_end_tiny(self):
        with tempfile.TemporaryDirectory() as d:
            A.main(['--seeds', '0-0', '--jobs', '1', '--out', d])
            for f in ('runs.csv.gz', 'summary.json', 'step_curves.json', 'signal_auc.json', 'yield_profiles.json',
                      'tables.md'):
                self.assertTrue((Path(d) / f).exists(), f)
            meta = json.loads((Path(d) / 'summary.json').read_text())['meta']
            self.assertEqual(meta['salt'], 'v010dev')
            self.assertIn('T6.', (Path(d) / 'tables.md').read_text())
        with self.assertRaises(ValueError):
            A.main(['--seeds', '0-300', '--jobs', '1', '--out', d])


if __name__ == '__main__':
    unittest.main()
