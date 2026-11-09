"""v0.9 confirmation study: leakage prevention, sealing, freeze manifest, scenarios, pilot pipeline.

Never unseals the real holdout salt and never calls the real Claude CLI.
"""
import json
import random
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caver5.fixtures import FAMILIES
from caver8.benchmark import OutcomeTable, TRAIN_BUDGET, EVAL_BUDGET
from caver9 import evaluation as ev
from caver9c import confirm, manifest, online, verdict

ROOT = Path(__file__).resolve().parents[1]
TABLE = OutcomeTable(json.loads((ROOT / 'reports/v08/outcome_table_real.json').read_text()))


class SealingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / 'log.jsonl'
        self.addCleanup(self.tmp.cleanup)

    def test_sealed_salt_needs_env_and_flag(self):
        for env, flag in (({}, False), ({}, True), ({confirm.UNSEAL_ENV: '1'}, False)):
            with self.assertRaises(confirm.SealedSaltError):
                confirm.authorize('fake-sealed', flag, log_path=self.log, sealed={'fake-sealed'}, env=env)
        self.assertFalse(self.log.exists())

    def test_unseal_is_logged_and_only_once(self):
        env = {confirm.UNSEAL_ENV: '1'}
        self.assertTrue(confirm.authorize('fake-sealed', True, log_path=self.log, sealed={'fake-sealed'}, env=env))
        self.assertEqual(len(self.log.read_text().splitlines()), 1)
        with self.assertRaises(confirm.SealedSaltError):
            confirm.authorize('fake-sealed', True, log_path=self.log, sealed={'fake-sealed'}, env=env)

    def test_real_holdout_refused_without_unseal_and_never_overwritten(self):
        out = Path(self.tmp.name) / 'out'
        with mock.patch.dict('os.environ', {}, clear=False):
            with self.assertRaises(confirm.SealedSaltError):
                confirm.run_holdout(out, unseal=False, log_path=self.log)
        out.mkdir()
        with self.assertRaises(FileExistsError):
            confirm.run_holdout(out, unseal=True, log_path=self.log)

    def test_only_study_salts_and_smoke_cap(self):
        for bad in ('v09dev', 'v09final', 'dev', 'holdout', 'v09c-dev'):
            with self.assertRaises(ValueError):
                confirm.check_salt(bad, range(1))
        with self.assertRaises(ValueError):
            confirm.check_salt(confirm.SMOKE_SALT, range(4))


class ManifestTests(unittest.TestCase):
    def test_committed_manifest_matches_current_files(self):
        m = manifest.verify()
        self.assertEqual(m['candidate'], 'caver9.exploration:UCBMeanCAVER')
        self.assertEqual(m['constants']['C'], 0.5)

    def test_tampering_is_detected(self):
        doc = json.loads(manifest.MANIFEST.read_text())
        doc['files']['caver9/exploration.py'] = '0' * 64
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(doc, f)
        with self.assertRaises(RuntimeError):
            manifest.verify(Path(f.name))


class ScenarioTests(unittest.TestCase):
    def test_all_12_scenarios_have_exact_budget_and_events(self):
        self.assertEqual(len(confirm.SCENARIOS), 12)
        for sc in confirm.SCENARIOS:
            train, hold, sd = confirm.build_schedule(confirm.SMOKE_SALT, 0, sc)
            self.assertEqual((len(train), len(hold)), (TRAIN_BUDGET, EVAL_BUDGET), sc)
            if sc != 'stationary':
                self.assertTrue(sd.events, sc)
                for e in sd.events:
                    self.assertTrue(e.up and 0 <= e.at < e.end <= EVAL_BUDGET, sc)

    def test_new_scenario_definitions(self):
        d = confirm.NEW_DEFS
        self.assertEqual([e.at for e in d['c_oscillate'].events], [15, 30, 45, 60, 75])
        self.assertEqual(d['c_reverse'].events[0].up, frozenset({'schema', 'field_value', 'abnormal_exit'}))
        train, _, _ = confirm.build_schedule(confirm.SMOKE_SALT, 0, 'c_reverse')
        self.assertTrue(all('train-rev9c' in c.id for c in train))
        _, hold, _ = confirm.build_schedule(confirm.SMOKE_SALT, 0, 'c_late')
        self.assertTrue(all('eval-base' in c.id for c in hold[:70]) and all('eval-shift' in c.id for c in hold[70:]))


class Spy:
    name = 'Spy'
    seen_ids = []

    def __init__(self, rng):
        self.rng = rng
        self.visited = {}

    def select(self, case_id):
        Spy.seen_ids.append(case_id)
        left = [f for f in FAMILIES if f not in self.visited.get(case_id, set())] or list(FAMILIES)
        return self.rng.choice(left)

    def update(self, case_id, arm, violated, newly_found, learn=True):
        assert (type(case_id), type(arm), type(violated), type(newly_found)) == (str, str, bool, bool)
        self.visited.setdefault(case_id, set()).add(arm)


class LeakageTests(unittest.TestCase):
    def test_policies_see_only_opaque_ids(self):
        Spy.seen_ids = []
        for sc in ('delayed', 'c_oscillate', 'c_reverse'):
            train, hold, sd = confirm.build_schedule(confirm.SMOKE_SALT, 1, sc)
            ev.run_one(Spy, confirm.SMOKE_SALT, 1, sc, TABLE, train, hold, sd)
        self.assertTrue(Spy.seen_ids)
        self.assertTrue(all(re.fullmatch(r'c\d{3}', i) for i in Spy.seen_ids))

    def test_smoke_evaluation_runs_with_all_comparators(self):
        rep = confirm.evaluate(salt=confirm.SMOKE_SALT, seeds=range(2), scenarios=('stationary', 'c_uniform'), jobs=1)
        self.assertEqual(set(rep['meta']['policies']), {'Random', 'UCB1', 'SW-UCB', 'D-UCB', 'CAVER-v0.6', 'C9-UCBMean'})
        self.assertIn('REPLAY', rep['meta']['evidence_type'])
        self.assertIn('diff_unique_false_pass_vs_D-UCB_ci', rep['summary']['c_uniform']['C9-UCBMean'])


class OnlinePilotTests(unittest.TestCase):
    def test_cap_and_overwrite_guards(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                online.run_pilot(Path(d) / 'x', real=False, max_runs=31)
            with self.assertRaises(ValueError):
                online.run_pilot(Path(d) / 'x', real=False, max_runs=5, live_steps=2)  # 3 policies x 2 > 5
            Path(d, 'y').mkdir()
            with self.assertRaises(FileExistsError):
                online.run_pilot(Path(d) / 'y', real=False)

    def test_mock_pilot_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            doc = online.run_pilot(Path(d) / 'out', real=False, max_runs=4, live_steps=2,
                                   policies=(confirm.CANDIDATE, 'UCB1'), trials_dir=Path(d) / 'trials')
            self.assertEqual(doc['meta']['runs_done'], 4)
            self.assertIn('SIMULATED', doc['meta']['evidence_type'])
            rows = [json.loads(x) for x in (Path(d) / 'out/live_probes.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(r['cli_kind'] == 'simulated' for r in rows))

    def test_real_mode_refuses_without_subscription(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(PermissionError):
                online.run_pilot(Path(d) / 'o', real=True, auth_status={'loggedIn': True, 'authMethod': 'api_key',
                                                                        'apiProvider': 'firstParty'})


class VerdictTests(unittest.TestCase):
    def _summary(self, lb=0.2, rec_ub=-1.0):
        m = {'diff_unique_false_pass_vs_CAVER-v0.6_ci': [lb, 1.0], 'diff_unique_false_pass_vs_UCB1_ci': [0.0, 1.0],
             'diff_recovery_steps_vs_CAVER-v0.6_ci': [-3.0, rec_ub]}
        for r in ('Random', 'SW-UCB', 'D-UCB'):
            m[f'diff_unique_false_pass_vs_{r}_ci'] = [0.5, 1.5]
        return {'summary': {sc: {'C9-UCBMean': dict(m)} for sc in confirm.SCENARIOS}}

    def test_decisions(self):
        ok = {'summary': {'criterion_F_replay_validity': 'PASS'}}
        bad = {'summary': {'criterion_F_replay_validity': 'FAIL'}}
        self.assertTrue(verdict.criteria(self._summary(), ok)['decision'].startswith('replay-confirmed'))
        self.assertTrue(verdict.criteria(self._summary(), bad)['decision'].startswith('채택 보류'))
        self.assertTrue(verdict.criteria(self._summary(rec_ub=0.01), ok)['decision'].startswith('채택 보류'))
        self.assertIn('replay-only', verdict.criteria(self._summary(), None)['decision'])


if __name__ == '__main__':
    unittest.main()
