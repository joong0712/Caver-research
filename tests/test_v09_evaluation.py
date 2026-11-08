"""Tests for the CAVER v0.9 independent evaluation harness (caver9.evaluation).

The sealed final salt is NEVER unsealed here: refusal is tested with 'v09final', and the
unsealing/logging mechanism is tested with a fake sealed salt and a temporary log path.
"""
import json
import os
import random
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import caver9.evaluation as ev
from caver5.fixtures import FAMILIES as ARMS
from caver5.policies import BasePolicy, UCB1Policy
from caver6.policies import CAVERv06
from caver8 import benchmark as b8
from caver8.live import FAMILIES8

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / 'reports/v08/outcome_table_real.json'
SIM = ROOT / 'reports/v08/outcome_table_simulated.json'
NO_CPU = lambda runs: [{k: v for k, v in r.items() if k != 'cpu_us_per_probe'} for r in runs]


class Spy(BasePolicy):
    """Records everything the harness hands to a policy."""
    name = 'Spy'
    log = None

    def __init__(self, rng):
        super().__init__(rng)
        assert type(rng) is random.Random
        self.calls = []
        Spy.log = self.calls

    def select(self, case_id):
        self.calls.append(('select', case_id))
        return self.rng.choice(self.available(case_id))

    def observe_outcome(self, **kw):
        self.calls.append(('observe', kw))

    def update(self, case_id, arm, violated, newly_found, learn=True):
        super().update(case_id, arm, violated, newly_found, learn)
        self.calls.append(('update', case_id, arm, violated, newly_found, learn))

    def begin_evaluation(self):
        self.calls.append(('begin',))


class IdCheater(CAVERv06):
    """Audit: v0.6 that resets when the case-id STRING reveals the shifted cohort."""
    name = 'IdCheater'
    _reset = False

    def select(self, case_id):
        if not self._reset and '-eval-shift-' in case_id:
            self._reset = True
            for f in ARMS:
                self.successes[f] = self.failures[f] = 0.0
                self.counts[f] = 0
            self.post_change_steps = 36
        return super().select(case_id)


class BadArm(BasePolicy):
    name = 'BadArm'

    def select(self, case_id):
        return 'not-an-arm'


class IgnoresExhaustion(BasePolicy):
    name = 'IgnoresExhaustion'

    def select(self, case_id):
        return ARMS[0]


class UCB1ViaDUCB(ev.DiscountedUCB):
    name = 'D-UCB(gamma=1,xi=0.5)'
    GAMMA = 1.0
    XI = 0.5


class Base(unittest.TestCase):
    def setUp(self):
        ev._reset_salt_guard_for_tests()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop(ev.UNSEAL_ENV, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / 'unseal.jsonl'
        self.logp = mock.patch.object(ev, 'UNSEAL_LOG', self.log)
        self.logp.start()

    def tearDown(self):
        self.logp.stop()
        self.env.stop()
        self.tmp.cleanup()
        ev._reset_salt_guard_for_tests()


class BudgetAndInterface(Base):
    def test_every_policy_gets_exactly_train_plus_eval_probes(self):
        rep = ev.evaluate(list(ev.BASELINES) + ['UCB1-RM', 'D-UCB-RM', Spy], salt='v09dev', seeds=range(3),
                          scenarios='all', cpu_timing=False)
        self.assertEqual(len(rep['runs']), 10 * 3 * len(ev.ALL_SCENARIOS))
        for r in rep['runs']:
            self.assertEqual((r['selects'], r['updates']), (b8.TRAIN_BUDGET + b8.EVAL_BUDGET,) * 2)
            self.assertEqual(r['rule_violations'], 0)

    def test_interface_violations_raise(self):
        with self.assertRaises(ev.InterfaceError):
            ev.evaluate([BadArm], salt='v09dev', seeds=[0], scenarios='stationary')
        with self.assertRaises(ev.InterfaceError):
            ev.evaluate([IgnoresExhaustion], salt='v09dev', seeds=[0], scenarios='stationary')
        rep = ev.evaluate([IgnoresExhaustion], salt='v09dev', seeds=[0], scenarios='stationary',
                          enforce_available=False)
        self.assertGreater(rep['runs'][0]['rule_violations'], 0)

    def test_duplicate_names_refused(self):
        with self.assertRaises(ValueError):
            ev.evaluate(['UCB1', UCB1Policy], salt='v09dev', seeds=[0], scenarios='stationary')

    def test_policy_specs(self):
        self.assertIs(ev.resolve_policy('caver9.evaluation:DiscountedUCB'), ev.DiscountedUCB)
        self.assertIs(ev.resolve_policy('UCB1'), UCB1Policy)
        rm = ev.resolve_policy('caver5.policies:UCB1Policy-RM')
        self.assertEqual(rm.name, 'UCB1-RM')
        self.assertIs(rm, ev.resolve_policy('UCB1-RM'))
        with self.assertRaises(KeyError):
            ev.resolve_policy('NoSuchPolicy')


class SealedFinal(Base):
    def test_final_salt_refused_without_env_and_flag(self):
        for env, unseal in ((None, False), (None, True), ('1', False), ('yes', True), ('0', True)):
            if env is None:
                os.environ.pop(ev.UNSEAL_ENV, None)
            else:
                os.environ[ev.UNSEAL_ENV] = env
            with self.assertRaises(ev.SealedSaltError):
                ev.evaluate(['Random'], salt='v09final', seeds=[0], scenarios='stationary', unseal=unseal)
            ev._reset_salt_guard_for_tests()
        self.assertFalse(self.log.exists(), 'a refused request must not be logged as an unsealing')

    def test_final_schedules_and_cli_refused(self):
        with self.assertRaises(ev.SealedSaltError):
            ev.build_schedule('v09final', 0, 'stationary')
        with self.assertRaises(ev.SealedSaltError):
            ev.main(['--salt', 'v09final', '--seeds', '1', '--policies', 'Random', '--output', self.tmp.name])
        with self.assertRaises(ev.SealedSaltError):
            ev.verify_legacy(['Random'], salt='v09final', seeds=[0])
        self.assertFalse(self.log.exists())

    def test_unseal_mechanism_on_fake_sealed_salt(self):
        with mock.patch.object(ev, 'FINAL_SALTS', frozenset({'unit-test-sealed'})):
            with self.assertRaises(ev.SealedSaltError):
                ev.evaluate(['Random'], salt='unit-test-sealed', seeds=[0], scenarios='stationary')
            os.environ[ev.UNSEAL_ENV] = '1'
            rep = ev.evaluate(['Random'], salt='unit-test-sealed', seeds=[0], scenarios='stationary', unseal=True)
            self.assertEqual(rep['meta']['salt_class'], 'final')
            ev.evaluate(['Random'], salt='unit-test-sealed', seeds=[1], scenarios='stationary', unseal=True)
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])['salt'], 'unit-test-sealed')


class SaltMixing(Base):
    def test_one_salt_per_call(self):
        for bad in (['v09dev', 'v09final'], ('v09dev',), 'v09dev,v09final', 'v09dev v09final', ''):
            with self.assertRaises(ev.SaltMixingError):
                ev.evaluate(['Random'], salt=bad, seeds=[0], scenarios='stationary')

    def test_dev_then_final_in_one_process_refused(self):
        with mock.patch.object(ev, 'FINAL_SALTS', frozenset({'unit-test-sealed'})):
            os.environ[ev.UNSEAL_ENV] = '1'
            ev.evaluate(['Random'], salt='v09dev', seeds=[0], scenarios='stationary')
            with self.assertRaises(ev.SaltMixingError):
                ev.evaluate(['Random'], salt='unit-test-sealed', seeds=[0], scenarios='stationary', unseal=True)
            ev._reset_salt_guard_for_tests()
            ev.evaluate(['Random'], salt='unit-test-sealed', seeds=[0], scenarios='stationary', unseal=True)
            with self.assertRaises(ev.SaltMixingError):
                ev.evaluate(['Random'], salt='v09dev', seeds=[0], scenarios='stationary')


class DeterminismAndLegacy(Base):
    def test_deterministic_and_jobs_invariant(self):
        kw = dict(salt='v09dev', seeds=range(4), scenarios=['delayed', 'double', 'gradual'])
        pols = ['UCB1', 'D-UCB', 'CAVER-v0.6', 'SW-UCB-RM']
        a = ev.evaluate(pols, **kw)
        b = ev.evaluate(pols, **kw)
        c = ev.evaluate(pols, jobs=2, **kw)
        self.assertEqual(NO_CPU(a['runs']), NO_CPU(b['runs']))
        self.assertEqual(NO_CPU(a['runs']), NO_CPU(c['runs']))

    def test_legacy_scenarios_reproduce_caver8_exactly(self):
        res = ev.verify_legacy(ev.BASELINES, salt='v09dev', seeds=range(4), table=REAL)
        self.assertTrue(res['exact_match'], res['per_run_mismatch_examples'] or res['summary_mismatches'])
        self.assertEqual(res['runs_compared'], 4 * 4 * len(ev.BASELINES))
        res = ev.verify_legacy(['UCB1', 'CAVER-v0.6'], salt='v09dev', seeds=range(2), table=SIM,
                               outcome_stream='legacy')
        self.assertTrue(res['exact_match'])

    def test_opaque_ids_do_not_change_baseline_results(self):
        kw = dict(salt='v09dev', seeds=range(3), scenarios='legacy', cpu_timing=False)
        self.assertEqual(ev.evaluate(list(ev.BASELINES), **kw)['runs'],
                         ev.evaluate(list(ev.BASELINES), opaque_ids=False, **kw)['runs'])


class DUCB(Base):
    def test_predeclared_constants(self):
        self.assertAlmostEqual(ev.DiscountedUCB.GAMMA, 1 - 0.25 * (1 / 180) ** 0.5, places=12)
        self.assertAlmostEqual(ev.DiscountedUCB.GAMMA, 0.98137, places=5)
        self.assertEqual((ev.DiscountedUCB.XI, ev.DiscountedUCB.B), (0.6, 1.0))

    def test_gamma_one_xi_half_equals_ucb1(self):
        kw = dict(salt='v09dev', seeds=range(3), scenarios=['stationary', 'abrupt'], cpu_timing=False)
        a = ev.evaluate([UCB1Policy, UCB1ViaDUCB], **kw)['runs']
        u = [{k: v for k, v in r.items() if k != 'policy'} for r in a if r['policy'] == 'UCB1']
        d = [{k: v for k, v in r.items() if k != 'policy'} for r in a if r['policy'] != 'UCB1']
        self.assertEqual(u, d)

    def test_discounting_forgets(self):
        p = ev.DiscountedUCB(random.Random(0))
        for i in range(6):
            p.update(f'k{i}', ARMS[i], False, False)
        for i in range(60):
            p.update(f'c{i}', ARMS[0], True, False)
        g = ev.DiscountedUCB.GAMMA
        self.assertAlmostEqual(p.n_disc[ARMS[1]], g ** 64, places=9)
        total = sum(p.n_disc.values())
        self.assertGreater(p.index(ARMS[1], total) - p.x_disc[ARMS[1]] / p.n_disc[ARMS[1]],
                           p.index(ARMS[0], total) - p.x_disc[ARMS[0]] / p.n_disc[ARMS[0]])

    def test_reward_matched_signal(self):
        seen = []

        class Rec(UCB1Policy):
            name = 'Rec'

            def update(self, case_id, family, violated, newly_found, learn=True):
                seen.append((violated, newly_found))
                super().update(case_id, family, violated, newly_found, learn)

        rm = ev.reward_matched(Rec, 'Rec')
        ev.evaluate([rm], salt='v09dev', seeds=[0], scenarios='abrupt')
        self.assertEqual(len(seen), 180)
        self.assertTrue(all(v == n for v, n in seen))


class InformationHygiene(Base):
    def test_policy_sees_only_interface_fields(self):
        ev.evaluate([Spy], salt='v09dev', seeds=[5], scenarios='double')
        calls = Spy.log
        kinds = [c[0] for c in calls]
        self.assertEqual(kinds.count('begin'), 1)
        self.assertEqual(kinds.index('begin'), 3 * b8.TRAIN_BUDGET)  # select/observe/update per probe
        for c in calls:
            if c[0] == 'select':
                self.assertRegex(c[1], r'^c\d{3}$')
            elif c[0] == 'observe':
                self.assertEqual(set(c[1]), {'false_pass', 'violated', 'new_defect'})
                self.assertTrue(all(type(v) is bool for v in c[1].values()))
            elif c[0] == 'update':
                _, cid, arm, viol, new, learn = c
                self.assertIn(arm, ARMS)
                self.assertTrue(type(viol) is bool and type(new) is bool and learn is True)
                self.assertTrue(not new or viol)
        blob = repr([c[1] for c in calls if c[0] in ('select', 'update')])  # case ids only (arm 'case_shift' is a label)
        for leak in ('v09dev', 'shift', 'train', 'base', 'alt9', 'single9'):
            self.assertNotIn(leak, blob)

    def test_case_id_leak_is_closed(self):
        kw = dict(salt='v09dev', seeds=range(6), scenarios=['delayed'], cpu_timing=False)
        opaque = ev.evaluate([CAVERv06, IdCheater], **kw)['runs']
        strip = lambda rs, n: [{k: v for k, v in r.items() if k != 'policy'} for r in rs if r['policy'] == n]
        self.assertEqual(strip(opaque, 'CAVER-v0.6'), strip(opaque, 'IdCheater'))
        raw = ev.evaluate([CAVERv06, IdCheater], opaque_ids=False, **kw)['runs']
        self.assertNotEqual(strip(raw, 'CAVER-v0.6'), strip(raw, 'IdCheater'))


class Scenarios(Base):
    def test_new_scenarios_define_change_points(self):
        self.assertGreaterEqual(len(ev.NEW_SCENARIOS), 3)
        for name in ev.NEW_SCENARIOS:
            sd = ev.SCENARIO_DEFS[name]
            self.assertNotIn(name, b8.SCENARIOS)
            self.assertTrue(sd.events and sd.false_alarm_until is not None, name)
            for e in sd.events:
                self.assertTrue(0 < e.at < e.end <= b8.EVAL_BUDGET, name)
                self.assertTrue(e.up and e.up <= set(FAMILIES8), name)

    def test_schedules_switch_cohort_at_change_points(self):
        tag = lambda c: c.id.split('-', 1)[1].rsplit('-', 1)[0]
        for seed in range(3):
            _, h, _ = ev.build_schedule('v09dev', seed, 'early')
            self.assertEqual({tag(c) for c in h[:10]}, {'eval-base'})
            self.assertEqual({tag(c) for c in h[10:]}, {'eval-shift'})
            _, h, _ = ev.build_schedule('v09dev', seed, 'double')
            self.assertEqual([{tag(c) for c in h[a:b]} for a, b in ((0, 30), (30, 60), (60, 90))],
                             [{'eval-base'}, {'eval-shift'}, {'eval-alt9'}])
            _, h, _ = ev.build_schedule('v09dev', seed, 'single')
            self.assertEqual({tag(c) for c in h[30:]}, {'eval-single9'})
            _, h, _ = ev.build_schedule('v09dev', seed, 'gradual')
            self.assertEqual({tag(c) for c in h[:15]}, {'eval-base'})
            self.assertEqual({tag(c) for c in h[75:]}, {'eval-shift'})
        self.assertEqual(ev.SCENARIO_DEFS['double'].events[1].up, frozenset({'field_value', 'timeout'}))
        self.assertEqual(ev.SCENARIO_DEFS['single'].events[0].up, frozenset({'timeout'}))


class Reporting(Base):
    def test_labels_and_files(self):
        rep = ev.evaluate(['Random', 'UCB1', 'CAVER-v0.6'], salt='v09dev', seeds=range(3),
                          scenarios=['stationary', 'single'])
        m = rep['meta']
        self.assertEqual(m['data_label'], 'real-table replay')
        self.assertIs(m['independent_real_cli_runs'], False)
        self.assertIn('NOT the uncertainty', m['replay_caveat'])
        self.assertIn('UCB1', rep['stationary_loss'])
        self.assertIn('diff_unique_false_pass_vs_UCB1_ci', rep['summary']['single']['CAVER-v0.6'])
        ev.save_report(rep, Path(self.tmp.name) / 'out')
        for f in ('summary.json', 'summary.csv', 'runs.csv'):
            self.assertTrue((Path(self.tmp.name) / 'out' / f).exists())
        self.assertIn('real-table replay', (Path(self.tmp.name) / 'out/summary.csv').read_text())
        sim = ev.evaluate(['Random'], salt='v09dev', seeds=[0], scenarios='stationary', table=SIM)
        self.assertTrue(sim['meta']['data_label'].startswith('simulated-table replay'))


if __name__ == '__main__':
    unittest.main()
