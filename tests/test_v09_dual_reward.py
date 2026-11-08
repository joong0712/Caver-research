"""v0.9 Agent B: dual-reward models, policies, fair UCB1s, dev harness guards and information hygiene.

No CLI calls. Benchmark runs here use the throw-away salt 'unittest' (never v09dev/v09final).
"""
import dataclasses
import json
import random
import unittest
from pathlib import Path

from caver5.fixtures import FAMILIES
from caver5.policies import BasePolicy, UCB1Policy
from caver6.policies import CAVERv06
from caver8.benchmark import OutcomeTable, schedules, run_policy
from caver9 import dual_reward as dr
from caver9.agent_b_dev import ALL, check_salt, instrument, norm_entropy, run_task, criteria

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / 'reports/v08/outcome_table_real.json').read_text())
TABLE = OutcomeTable(DOC)
SALT = 'unittest'
DR_CLASSES = dr.CANDIDATES + dr.ABLATIONS + dr.FAIR_UCB


class ModelTests(unittest.TestCase):
    def test_constants_are_the_preregistered_starting_values(self):
        self.assertEqual((dr.W_DISC, dr.W_VIOL), (0.6, 0.4))
        self.assertEqual((dr.GAMMA_DISC, dr.GAMMA_VIOL), (1.0, 0.97))
        for c in dr.CANDIDATES:
            self.assertEqual((c.w_disc, c.w_viol), (0.6, 0.4))
        self.assertEqual((dr.DualRewardTSDisc.w_disc, dr.DualRewardTSDisc.w_viol), (1.0, 0.0))
        self.assertEqual((dr.DualRewardTSViol.w_disc, dr.DualRewardTSViol.w_viol), (0.0, 1.0))
        self.assertEqual(dr.DualRewardTSRecentDisc.gamma_disc, dr.GAMMA_VIOL)

    def test_discovery_model_is_beta_posterior(self):
        m = dr.DiscoveryModel()
        arm = FAMILIES[0]
        for r in (True, False, False, True, False):
            m.observe(arm, r)
        self.assertAlmostEqual(m.mean(arm), (1 + 2) / (2 + 5))
        self.assertAlmostEqual(m.mean(FAMILIES[1]), 0.5)
        with self.assertRaises(ValueError):
            m.observe('nope', True)

    def test_violation_model_discounts_all_arms_and_bounds_memory(self):
        m = dr.RecentViolationModel()
        m.observe(FAMILIES[1], True)
        for _ in range(500):
            m.observe(FAMILIES[0], False)
        self.assertLess(m.n(FAMILIES[1]), 1e-5)            # unplayed arm forgets -> uncertainty returns
        self.assertAlmostEqual(m.sd(FAMILIES[1]), dr._BetaArms(1.0).sd(FAMILIES[1]), places=4)
        self.assertLessEqual(m.n(FAMILIES[0]), 1 / (1 - dr.GAMMA_VIOL) + 1e-9)

    def test_recent_model_tracks_a_rate_increase_faster(self):
        recent, stale = dr.RecentViolationModel(), dr._BetaArms(1.0)
        arm = FAMILIES[5]
        for _ in range(90):
            recent.observe(arm, False)
            stale.observe(arm, False)
        for _ in range(15):
            recent.observe(arm, True)
            stale.observe(arm, True)
        self.assertGreater(recent.mean(arm), 0.3)
        self.assertLess(stale.mean(arm), 0.2)

    def test_ts_combines_weighted_draws(self):
        p = dr.DualRewardTS(random.Random(0))
        for _ in range(30):
            p.update('c', FAMILIES[2], True, True)
        picks = [p.select(f'x{i}') for i in range(50)]
        self.assertGreater(picks.count(FAMILIES[2]), 40)

    def test_bayes_score_is_weighted_sum(self):
        p = dr.DualRewardBayes(random.Random(0))
        p.update('c', FAMILIES[0], True, False)
        a = FAMILIES[0]
        self.assertAlmostEqual(p.arm_score(a), 0.6 * p.disc.optimistic(a) + 0.4 * p.viol.optimistic(a))

    def test_exhaustion_rule_inherited(self):
        for cls in DR_CLASSES:
            p = cls(random.Random(1))
            self.assertIsInstance(p, BasePolicy)
            seen = set()
            for _ in range(len(FAMILIES)):
                arm = p.select('case')
                self.assertNotIn(arm, seen, cls.name)
                seen.add(arm)
                p.update('case', arm, False, False)
            self.assertIn(p.select('case'), FAMILIES)   # all exhausted: repeat allowed

    def test_learn_false_only_tracks_visits(self):
        p = dr.DualRewardTS(random.Random(0))
        p.update('c', FAMILIES[0], True, True, learn=False)
        self.assertEqual(p.disc.n(FAMILIES[0]), 0)
        self.assertEqual(p.visited['c'], {FAMILIES[0]})

    def test_unique_names(self):
        names = [c.name for c in ALL]
        self.assertEqual(len(names), len(set(names)))


class FairUCBTests(unittest.TestCase):
    def test_newfp_ucb_ignores_violation_reward(self):
        p = dr.UCB1NewFP(random.Random(0))
        p.update('c', FAMILIES[0], True, False)
        p.update('d', FAMILIES[0], True, True)
        self.assertEqual((p.counts[FAMILIES[0]], p.violations[FAMILIES[0]]), (2, 1))

    def test_combined_ucb_reward(self):
        p = dr.UCB1Combined(random.Random(0))
        p.update('c', FAMILIES[1], True, False)
        p.update('d', FAMILIES[1], True, True)
        self.assertAlmostEqual(p.violations[FAMILIES[1]], 0.4 + 1.0)
        self.assertIsInstance(p, UCB1Policy)


class HarnessTests(unittest.TestCase):
    def test_disc_only_v06_reproduces_caver_v06(self):
        for sc in ('stationary', 'delayed'):
            tr, h, c = schedules(SALT, 3, sc)
            a = dataclasses.asdict(run_policy(CAVERv06, SALT, 3, sc, TABLE, tr, h, c))
            b = dataclasses.asdict(run_policy(dr.DualRewardV06Disc, SALT, 3, sc, TABLE, tr, h, c))
            a.pop('policy'), b.pop('policy')
            self.assertEqual(a, b)

    def test_instrumentation_is_behaviour_neutral(self):
        tr, h, c = schedules(SALT, 2, 'abrupt')
        for cls in ALL:
            a = run_policy(cls, SALT, 2, 'abrupt', TABLE, tr, h, c)
            b = run_policy(instrument(cls), SALT, 2, 'abrupt', TABLE, tr, h, c)
            self.assertEqual(dataclasses.asdict(a), dataclasses.asdict(b), cls.name)

    def test_forbidden_salts_refused(self):
        for s in ('v09final', 'dev', 'holdout'):
            with self.assertRaises(PermissionError):
                check_salt(s)
            with self.assertRaises(PermissionError):
                run_task((s, 0, 'stationary', ['UCB1'], DOC))
        check_salt('v09dev')

    def test_run_task_fields(self):
        rows = run_task((SALT, 0, 'recovery', ['B-DR-Bayes', 'UCB1'], DOC))
        for r in rows:
            self.assertTrue(0.0 <= r['eval_entropy'] <= 1.0)
            self.assertGreater(r['cpu_us_per_probe'], 0)
            self.assertIsNotNone(r['recovery_capped'])

    def test_norm_entropy(self):
        self.assertAlmostEqual(norm_entropy(list(FAMILIES) * 3), 1.0)
        self.assertAlmostEqual(norm_entropy([FAMILIES[0]] * 9), 0.0)

    def test_criteria_logic(self):
        def blk(d06, ducb, rec06=None, own=None, recown=None):
            m = {'d_ufp_vs_CAVER-v0.6_ci': d06, 'd_ufp_vs_UCB1_ci': ducb}
            if rec06:
                m['d_rec_vs_CAVER-v0.6_ci'] = rec06
            if own:
                m['d_ufp_vs_own_disc_ci'], m['d_rec_vs_own_disc_ci'] = own, recown
            return {'X': m}
        s = {'stationary': blk([-0.4, 0.2], [0, 1]),
             'abrupt': blk([0.1, 1], [-0.4, 1], [-5, -1], [0.1, 1], [-3, -1]),
             'delayed': blk([0.1, 1], [-0.4, 1], [-5, -1], [0.1, 1], [-3, -1]),
             'recovery': blk([-0.4, 1], [0, 1], [-5, -1])}
        c = criteria(s, 'X')
        self.assertTrue(c['all'])
        self.assertTrue(c['hypothesis_supported_vs_own_disc'])
        s['stationary']['X']['d_ufp_vs_CAVER-v0.6_ci'] = [-0.51, 0.2]
        self.assertFalse(criteria(s, 'X')['all'])


class InformationHygieneTests(unittest.TestCase):
    """update() receives only (str, str, bool, bool); observe_outcome() only three booleans."""

    def _spy(self, cls, log):
        attrs = {}

        def update(self, case_id, arm, violated, newly_found, learn=True):
            log.append(('update', (case_id, arm, violated, newly_found), learn))
            cls.update(self, case_id, arm, violated, newly_found, learn)
        attrs['update'] = update
        if hasattr(cls, 'observe_outcome'):
            def observe_outcome(self, *args, **kwargs):
                log.append(('observe', args, kwargs))
                cls.observe_outcome(self, *args, **kwargs)
            attrs['observe_outcome'] = observe_outcome
        return type('Spy', (cls,), attrs)

    def test_harness_passes_only_observable_primitives(self):
        for cls in DR_CLASSES:
            log = []
            tr, h, c = schedules(SALT, 4, 'delayed')
            run_policy(self._spy(cls, log), SALT, 4, 'delayed', TABLE, tr, h, c)
            ups = [e for e in log if e[0] == 'update']
            self.assertEqual(len(ups), len(tr) + len(h))
            for _, args, learn in ups:
                self.assertEqual([type(a) for a in args], [str, str, bool, bool], cls.name)
                self.assertIn(args[1], FAMILIES)
                self.assertIs(learn, True)
            obs = [e for e in log if e[0] == 'observe']
            if hasattr(cls, 'observe_outcome'):
                self.assertEqual(len(obs), len(ups))
            for _, args, kwargs in obs:
                self.assertEqual(args, ())
                self.assertEqual(set(kwargs), {'false_pass', 'violated', 'new_defect'})
                self.assertTrue(all(type(v) is bool for v in kwargs.values()), cls.name)

    def test_observe_outcome_rejects_non_booleans(self):
        p = dr.DualRewardBayes(random.Random(0))
        with self.assertRaises(TypeError):
            p.observe_outcome(false_pass=1, violated=True, new_defect=False)
        with self.assertRaises(TypeError):
            p.observe_outcome(False, True, False)   # keyword-only

    def test_policies_hold_no_hidden_state_references(self):
        from caver9 import agent_b_dev
        tr, h, c = schedules(SALT, 5, 'abrupt')
        run_policy(instrument(dr.DualRewardV06), SALT, 5, 'abrupt', TABLE, tr, h, c)
        p = agent_b_dev._LAST[0]
        self.assertGreater(p._b_probes, 0)
        blob = repr(vars(p)) + repr(vars(p.viol))
        for leak in ('defects', 'W_SHIFT', 'change_at', 'Case8'):
            self.assertNotIn(leak, blob)


if __name__ == '__main__':
    unittest.main()
