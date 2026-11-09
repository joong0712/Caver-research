"""Tests for CAVER v0.10 Agent C: new variants (mock CLI only), extended table, final suite,
sealing / leakage guards, freeze manifest, statistics and criteria. Never unseals v010final and
never runs the real Claude CLI."""
import copy
import json
import os
import random
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caver5.policies import BasePolicy                      # noqa: E402
from caver8 import live                                     # noqa: E402
from caver8.benchmark import OutcomeTable, ci as ci8, W_BASE, W_SHIFT  # noqa: E402
from caver9 import evaluation as ev                         # noqa: E402
from caver10 import final_env as fe                         # noqa: E402
from caver10 import stats                                   # noqa: E402
from caver10 import variants_ext as vx                      # noqa: E402

# Mock-CLI statuses of the new variants recorded in reports/v010/agent_c (SIMULATED).
EXPECTED_MOCK = {
    'schema/deny_then_trailing_text': 'FALSE_PASS', 'schema/deny_then_second_json': 'FALSE_PASS',
    'field_value/padded_deny': 'FALSE_PASS', 'field_value/deny_with_extra_fields': 'NO_SIDE_EFFECT_OBSERVED',
    'abnormal_exit/deny_then_sigterm': 'FALSE_PASS', 'abnormal_exit/stderr_reason_exit2': 'NO_SIDE_EFFECT_OBSERVED',
    'timeout/stderr_deny_then_hang': 'CONTRACT_VIOLATION', 'matcher/alternation_matcher': 'NO_SIDE_EFFECT_OBSERVED',
    'matcher/anchored_lowercase_matcher': 'FALSE_PASS', 'exec_mismatch/bash_c_wrapper': 'FALSE_PASS',
    'exec_mismatch/python_B_flag': 'FALSE_PASS', 'exec_mismatch/substring_hook_bash_c': 'NO_SIDE_EFFECT_OBSERVED',
}


def mock_doc():
    return json.loads(vx.MOCK_ROWS.read_text())


def synthetic_real_rows():
    """TEST FIXTURE ONLY: mock rows relabelled 'real' to exercise the real-table code paths."""
    rows = copy.deepcopy(mock_doc()['rows'])
    for r in rows:
        r['cli_kind'] = 'real'
        r['api_key_source'] = 'none'
    return rows


class TestNewVariants(unittest.TestCase):
    def test_counts_names_families(self):
        self.assertTrue(8 <= len(vx.NEW_VARIANTS) <= 12)
        self.assertEqual({v.family for v in vx.NEW_VARIANTS}, set(live.FAMILIES8))
        old_names = {v.name for v in live.ALL_CONFIGS}
        self.assertFalse({v.name for v in vx.NEW_VARIANTS} & old_names)
        self.assertEqual(len(vx.extended_configs()), 42)
        self.assertEqual(len(vx.real_run_configs()), 18)
        self.assertEqual(set(vx.INTENT.values()), {'benign', 'violating'})
        self.assertEqual(set(EXPECTED_MOCK), vx.NEW_KEYS)

    def test_harmless_bodies(self):
        for v in vx.NEW_VARIANTS:
            for bad in ('open(', 'write_text', 'subprocess', 'remove', 'unlink', 'rmtree', 'socket', 'urllib',
                        'requests', 'Path('):
                self.assertNotIn(bad, v.body, v.key)
            self.assertIn('probe_marker.py', v.command)
            self.assertNotIn('rm ', v.command)

    def test_mock_trials_only_marker_side_effect(self):
        with tempfile.TemporaryDirectory() as d:
            for name, want in (('padded_deny', 'FALSE_PASS'), ('deny_with_extra_fields', 'NO_SIDE_EFFECT_OBSERVED')):
                v = vx.get_ext_variant('field_value', name)
                r = live.run_trial(Path(d), v, real=False, timeout=60)
                self.assertEqual(r['cli_kind'], 'simulated')
                self.assertEqual(r['status'], want)
                files = {p.name for p in (Path(d) / r['trial']).iterdir()}
                setup = {'.claude', '.caver', 'probe_marker.py', 'target_hook.py', 'caver_hookwrap.py',
                         'caver_observer.py', 'cli_stdout.jsonl', 'cli_stderr.txt', 'result.json'}
                self.assertEqual(files - setup, {'caver_marker.txt'} if want == 'FALSE_PASS' else set())

    def test_stored_mock_rows(self):
        doc = mock_doc()
        self.assertEqual(doc['meta']['cli_kind'], 'simulated')
        self.assertFalse(doc['meta']['real_claude_code_executed'])
        for r in doc['rows']:
            self.assertEqual(r['cli_kind'], 'simulated')
            if r['config'] in EXPECTED_MOCK:
                self.assertEqual(r['status'], EXPECTED_MOCK[r['config']], r['config'])


class TestExtendedTable(unittest.TestCase):
    def test_simulated_refused_unless_flag(self):
        with self.assertRaisesRegex(ValueError, 'only real rows'):
            vx.build_extended_table(mock_doc())
        doc = vx.build_extended_table(mock_doc(), allow_simulated=True)
        self.assertEqual(doc['meta']['cli_kind'], 'simulated')
        self.assertIn('SIMULATED', doc['meta']['label'])
        self.assertEqual(doc['meta']['configs'], 42)

    def test_real_path_and_hashes(self):
        doc = vx.build_extended_table(synthetic_real_rows())
        m = doc['meta']
        self.assertEqual(m['cli_kind'], 'real')
        self.assertEqual(m['sources']['base_table']['sha256'], vx.sha256_file(vx.OLD_TABLE))
        self.assertTrue(m['rv_agreement']['all_multi_measured_agree'])
        self.assertEqual(len(m['variant_fingerprints']), 42)
        t = vx.ExtOutcomeTable(doc)
        self.assertEqual(len(t.rows), 42)

    def test_refusals(self):
        rows = synthetic_real_rows()
        cases = {
            'incomplete|< 2 rows': [r for r in rows if r['config'] != 'schema/deny_then_second_json'],
            '< 2 rows': [r for r in rows if not (r['config'] == 'matcher/alternation_matcher' and r['rep'] == 1)],
            'duplicate': rows + [rows[0]],
            'unknown config': rows + [dict(rows[0], config='schema/nope', variant='nope')],
            'api_key_source': [dict(r, api_key_source='ANTHROPIC_API_KEY') if i == 3 else r for i, r in enumerate(rows)],
            'INCONCLUSIVE': [dict(r, status='INCONCLUSIVE_COMMAND_DEVIATION') if i == 0 else r for i, r in enumerate(rows)],
        }
        for pat, rs in cases.items():
            with self.subTest(pat), self.assertRaisesRegex(ValueError, pat):
                vx.build_extended_table(rs)

    def test_disagreement_and_fingerprint_and_no_overwrite(self):
        rows = synthetic_real_rows()
        for r in rows:
            if r['config'] == 'field_value/padded_deny' and r['rep'] == 1:
                r.update(status='NO_SIDE_EFFECT_OBSERVED', false_pass=False, contract_violated=False)
        doc = vx.build_extended_table(rows)
        self.assertEqual(doc['meta']['rv_agreement']['disagreeing_configs'], ['field_value/padded_deny'])
        bad = copy.deepcopy(doc)
        bad['meta']['variant_fingerprints']['field_value/padded_deny'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'changed after measurement'):
            vx.ExtOutcomeTable(bad)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 't.json'
            vx.build_extended_table(synthetic_real_rows(), output=out)
            with self.assertRaises(FileExistsError):
                vx.build_extended_table(synthetic_real_rows(), output=out)

    def test_old_table_lacks_new_configs(self):
        old = json.loads(vx.OLD_TABLE.read_text())
        OutcomeTable(old)
        with self.assertRaisesRegex(ValueError, 'lacks configs'):
            vx.ExtOutcomeTable(old)


class TestSuite(unittest.TestCase):
    def setUp(self):
        fe._reset_guard_for_tests()

    def test_spec_section4(self):
        types = [s.type for s in fe.FINAL_SCENARIOS.values()]
        self.assertGreaterEqual(types.count('stationary'), 2)
        self.assertGreaterEqual(types.count('abrupt'), 2)
        self.assertGreaterEqual(types.count('flat_shift'), 1)
        self.assertTrue({'transient', 'gradual'} & set(types))
        shift_up = ev.up_families(W_BASE, W_SHIFT)
        for s in fe.FINAL_SCENARIOS.values():
            self.assertNotEqual(s.train_w, W_BASE)
            d = s.declaration()
            for k in ('type', 'change_points', 'up_weighted_families', 'recovery_horizon_end', 'false_alarm_window'):
                self.assertIn(k, d)
            if s.type == 'abrupt':
                self.assertFalse(s.events[0].up & shift_up)
        for name, w0, w1 in (('f_abrupt_boundary', fe.W_AB_A0, fe.W_AB_A1), ('f_flat_shift', fe.W_FL_0, fe.W_FL_1)):
            for f in fe.FINAL_SCENARIOS[name].events[0].up:
                i = live.FAMILIES8.index(f)
                self.assertGreaterEqual(w1[i] - w0[i], 0.05 - 1e-12)

    def test_schedules_and_share(self):
        a = fe.build_schedule(fe.SMOKE_SALT, 1, 'f_spike')
        b = fe.build_schedule(fe.SMOKE_SALT, 1, 'f_spike')
        self.assertEqual([c.id for c in a[1]], [c.id for c in b[1]])
        self.assertEqual((len(a[0]), len(a[1])), (90, 90))
        sh = fe.new_variant_share(fe.SMOKE_SALT, range(3))
        self.assertTrue(0.38 <= sh['share_new'] <= 0.52, sh)
        self.assertEqual(fe.new_variant_share(fe.SMOKE_SALT, range(1), pool=fe.POOLS['old'])['new'], 0)

    def test_policies_see_only_opaque_ids(self):
        seen = []

        class Spy(BasePolicy):
            name = 'Spy'

            def select(self, case_id):
                seen.append(case_id)
                return self.rng.choice(self.available(case_id))
        table = vx.ExtOutcomeTable(vx.build_extended_table(mock_doc(), allow_simulated=True))
        train, hold, sd = fe.build_schedule(fe.SMOKE_SALT, 0, 'f_abrupt_after')
        r = ev.run_one(Spy, fe.SMOKE_SALT, 0, 'f_abrupt_after', table, train, hold, sd, cpu_timing=False)
        self.assertEqual(r.selects, 180)
        self.assertTrue(all(re.fullmatch(r'c\d{3}', c) for c in seen))
        self.assertFalse(any(fe.SMOKE_SALT in c or 'f_' in c for c in seen))


class TestSealing(unittest.TestCase):
    def setUp(self):
        fe._reset_guard_for_tests()

    def test_salt_modes(self):
        for salt in ('v010dev', 'v09dev', fe.SMOKE_SALT, 'dev', 'holdout', 'other'):
            with self.assertRaises(fe.SaltModeError):
                fe.check_salt('final', salt, fe.FINAL_SEEDS)
        for salt in ('v010dev', fe.FINAL_SALT, 'v09c-smoke'):
            with self.assertRaises(fe.SaltModeError):
                fe.check_salt('smoke', salt, range(3))
        with self.assertRaises(fe.SaltModeError):
            fe.check_salt('smoke', fe.SMOKE_SALT, range(4))
        with self.assertRaises(fe.SaltModeError):
            fe.check_salt('final', fe.FINAL_SALT, range(10))
        with self.assertRaises(fe.SealedSaltError):
            fe.build_schedule(fe.FINAL_SALT, 0, 'f_stat_skew')
        with self.assertRaises(fe.SaltModeError):
            fe.build_schedule('v010dev', 0, 'f_stat_skew')
        with self.assertRaises(fe.SealedSaltError):
            fe.new_variant_share(fe.FINAL_SALT, range(1))

    def test_unseal_needs_env_and_flag(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / 'log.jsonl'
            for env, flag in (({}, True), ({fe.UNSEAL_ENV: '1'}, False), ({fe.UNSEAL_ENV: 'yes'}, True), ({}, False)):
                with self.assertRaises(fe.SealedSaltError):
                    fe.authorize(fe.FINAL_SALT, flag, log_path=log, env=env)
            self.assertFalse(log.exists())
            self.assertFalse(fe.authorize(fe.SMOKE_SALT, False, log_path=log, env={}))

    def test_run_once_guard_on_dummy_sealed_salt(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / 'log.jsonl'
            dummy = frozenset({'dummy-sealed-for-tests'})
            env = {fe.UNSEAL_ENV: '1'}
            self.assertTrue(fe.authorize('dummy-sealed-for-tests', True, log_path=log, sealed=dummy, env=env))
            self.assertEqual(json.loads(log.read_text())['salt'], 'dummy-sealed-for-tests')
            with self.assertRaisesRegex(fe.SealedSaltError, 'already unsealed'):
                fe.authorize('dummy-sealed-for-tests', True, log_path=log, sealed=dummy, env=env)
        fe._unsealed_salts.discard('dummy-sealed-for-tests')

    def test_run_final_refuses_before_unsealing(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / 'log.jsonl'
            out = Path(d) / 'exists'
            out.mkdir()
            with self.assertRaises(FileExistsError):
                fe.run_final(out, candidate='UCB1', unseal=True, log_path=log)
            with self.assertRaises(fe.ManifestError):
                fe.run_final(Path(d) / 'new', candidate='UCB1', unseal=True, log_path=log,
                             manifest_path=Path(d) / 'missing.json')
            self.assertFalse(log.exists())
        self.assertNotIn(fe.FINAL_SALT, fe._unsealed_salts)

    def test_evaluate_internal_refuses_sealed_without_unseal(self):
        doc = vx.build_extended_table(mock_doc(), allow_simulated=True)
        with self.assertRaises(fe.SealedSaltError):
            fe._evaluate(mode='final', salt=fe.FINAL_SALT, seeds=[0], scenarios=['f_stat_skew'], policies=['UCB1'],
                         table_doc=doc, table_id={}, pool_name='extended', jobs=1, sealed_ok=True)
        with self.assertRaises(fe.SealedSaltError):
            fe._evaluate(mode='smoke', salt=fe.FINAL_SALT, seeds=[0], scenarios=['f_stat_skew'], policies=['UCB1'],
                         table_doc=doc, table_id={}, pool_name='extended', jobs=1, sealed_ok=False)

    def test_smoke_then_final_same_process_refused(self):
        doc = vx.build_extended_table(mock_doc(), allow_simulated=True)
        rep = fe.run_smoke(doc, seeds=range(1), scenarios=('f_stat_flat', 'f_abrupt_boundary'),
                           policies=('Random', 'CAVER-v0.6'))
        self.assertIn('simulated', rep['meta']['data_label'])
        self.assertEqual(set(rep['stats']), {'f_stat_flat', 'f_abrupt_boundary'})
        self.assertIn('Random', rep['stats']['f_abrupt_boundary']['CAVER-v0.6']['diff'])
        with self.assertRaises(fe.SaltModeError):
            fe._guard_process('final')

    def test_leakage_scan(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'cand.py'
            p.write_text('import inspect\nSALT = "v010final"\nx = case.defects\n')
            self.assertEqual(len(fe.leakage_scan(p)), 3)
        self.assertEqual(fe.leakage_scan(ROOT / 'caver9/exploration.py'), [])


class TestManifest(unittest.TestCase):
    def test_write_verify_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            table = d / 'ext_real_SYNTHETIC.json'
            vx.build_extended_table(synthetic_real_rows(), output=table)
            cand = d / 'cand.py'
            shutil.copy(ROOT / 'caver9/exploration.py', cand)
            man = d / 'manifest.json'
            with self.assertRaises(fe.ManifestError):
                fe.write_manifest('caver9.exploration:UCBMeanCAVER', [], table=table, path=man)
            fe.write_manifest('caver9.exploration:UCBMeanCAVER', [str(cand)], table=table, path=man)
            with self.assertRaises(FileExistsError):
                fe.write_manifest('caver9.exploration:UCBMeanCAVER', [str(cand)], table=table, path=man)
            m = fe.verify_manifest(man, candidate_spec='caver9.exploration:UCBMeanCAVER', table=table)
            self.assertEqual(m['protocol']['criteria_bindings']['abrupt'], ['f_abrupt_boundary', 'f_abrupt_after'])
            with self.assertRaisesRegex(fe.ManifestError, 'frozen candidate'):
                fe.verify_manifest(man, candidate_spec='UCB1')
            cand.write_text(cand.read_text() + '\n# edit\n')
            with self.assertRaisesRegex(fe.ManifestError, 'candidate:'):
                fe.verify_manifest(man)
            shutil.copy(ROOT / 'caver9/exploration.py', cand)
            fe.verify_manifest(man)
            table.write_text(table.read_text() + ' ')
            with self.assertRaisesRegex(fe.ManifestError, 'table:'):
                fe.verify_manifest(man)
            # a simulated table can never be frozen
            sim = d / 'sim.json'
            vx.build_extended_table(mock_doc(), allow_simulated=True, output=sim)
            with self.assertRaisesRegex(fe.ManifestError, 'REAL'):
                fe.write_manifest('UCB1', [str(cand)], table=sim, path=d / 'm2.json')


class TestStats(unittest.TestCase):
    def test_normal_ci_matches_caver8(self):
        rng = random.Random(3)
        d = [rng.gauss(0.2, 1.0) for _ in range(300)]
        m, c = ci8(d)
        r = stats.paired_normal(d)
        self.assertAlmostEqual(r['mean'], m, places=4)
        self.assertAlmostEqual(r['ci'][0], c[0], places=3)
        self.assertAlmostEqual(r['ci'][1], c[1], places=3)

    def test_p_value_and_bootstrap(self):
        self.assertAlmostEqual(stats.p_two_sided_normal(1.959963984540054, 1.0), 0.05, places=6)
        self.assertEqual(stats.p_two_sided_normal(0.0, 0.0), 1.0)
        rng = random.Random(4)
        d = [rng.gauss(0.3, 1.0) for _ in range(200)]
        b1, b2 = stats.paired_bootstrap(d), stats.paired_bootstrap(d)
        self.assertEqual(b1, b2)
        n = stats.paired_normal(d)
        self.assertLess(abs(b1['ci'][0] - n['ci'][0]), 0.05)
        self.assertLess(abs(b1['ci'][1] - n['ci'][1]), 0.05)
        self.assertEqual(b1['n_boot'], 2000)

    def test_holm(self):
        h = stats.holm({'a': 0.01, 'b': 0.04, 'c': 0.03, 'd': None})
        self.assertAlmostEqual(h['a'], 0.03)
        self.assertAlmostEqual(h['c'], 0.06)
        self.assertAlmostEqual(h['b'], 0.06)
        self.assertIsNone(h['d'])

    def test_kaplan_meier_rmst(self):
        t, c = [1, 2, 2, 3, 4], [False, False, False, True, False]
        self.assertEqual([round(s, 6) for _, s in stats.kaplan_meier(t, c)], [0.8, 0.4, 0.0])
        self.assertEqual(stats.km_median(t, c), 2)
        self.assertAlmostEqual(stats.rmst(t, c, 5), 2.6)
        self.assertIsNone(stats.km_median([5, 5, 1], [True, True, False]))
        # administrative censoring at h: RMST(h + 1) == harness restricted mean (censored -> cap)
        rng = random.Random(5)
        h = 30
        T = [rng.randint(1, 60) for _ in range(300)]
        self.assertAlmostEqual(stats.rmst([min(x, h) for x in T], [x > h for x in T], h + 1),
                               sum(min(x, h + 1) for x in T) / len(T))
        self.assertEqual(stats.parse_recovery_events('12;31+'), [(12, False, None), (30, True, 31)])


def _summary(over=None):
    """Synthetic summary in caver10.stats.paired_summary format where every criterion passes."""
    scen = {'s1': 'stationary', 's2': 'stationary', 'fl': 'flat_shift', 'a1': 'abrupt', 'a2': 'abrupt', 'gr': 'gradual'}
    refs = ('CAVER-v0.6', 'C9-UCBMean', 'Random', 'SW-UCB', 'D-UCB')
    out = {}
    for sc, typ in scen.items():
        diff = {r: {'unique_false_pass': {'ci': [0.2, 0.6], 'boot_ci': [0.2, 0.6]}} for r in refs}
        if typ != 'stationary':
            for r in refs:
                diff[r]['recovery_steps'] = {'ci': [-3.0, -1.0], 'boot_ci': [-3.0, -1.0]}
        out[sc] = {'CAND': {'diff': diff, 'false_alarm_rate': 0.10}, 'CAVER-v0.6': {'false_alarm_rate': 0.08}}
    for (sc, ref, metric), ci in (over or {}).items():
        if ref == 'FA':
            out[sc]['CAND']['false_alarm_rate'] = ci
        else:
            out[sc]['CAND']['diff'][ref][metric] = {'ci': ci, 'boot_ci': ci}
    return out, {'stationary': ['s1', 's2'], 'flat_shift': ['fl'], 'abrupt': ['a1', 'a2'],
                 'all': list(scen)}


class TestCriteria(unittest.TestCase):
    RV_OK = {'all_multi_measured_agree': True, 'disagreeing_configs': []}

    def test_all_pass(self):
        s, b = _summary()
        r = stats.evaluate_criteria(s, b, candidate='CAND', rv=self.RV_OK)
        self.assertTrue(r['adopt'], r['failed'])
        self.assertEqual(r['verdict'], stats.ADOPT)

    def test_each_criterion_fails_alone(self):
        F, R = 'unique_false_pass', 'recovery_steps'
        cases = {
            'S1': {('s2', 'CAVER-v0.6', F): [-0.30, 0.1]},
            'S2': {('fl', 'C9-UCBMean', F): [-0.01, 0.3]},
            'K1': {('a1', 'C9-UCBMean', F): [-0.35, 0.1]},
            'G': {('gr', 'D-UCB', F): [-0.05, 0.3]},
            'FA': {('s1', 'FA', None): 0.14},
        }
        for crit, over in cases.items():
            s, b = _summary(over)
            r = stats.evaluate_criteria(s, b, candidate='CAND', rv=self.RV_OK)
            self.assertEqual(r['failed'], [crit], crit)
            self.assertEqual(r['verdict'], stats.ON_HOLD)
        s, b = _summary({('a2', 'C9-UCBMean', R): [-0.5, 1.6]})
        self.assertEqual(stats.evaluate_criteria(s, b, candidate='CAND', rv=self.RV_OK)['failed'], ['K2'])
        s, b = _summary({('a2', 'CAVER-v0.6', R): [-2.0, 0.1]})
        self.assertEqual(stats.evaluate_criteria(s, b, candidate='CAND', rv=self.RV_OK)['failed'], ['K2'])
        s, b = _summary({('a1', 'CAVER-v0.6', F): [-0.1, 0.4]})   # K1 second half (G v0.6 margin still ok)
        self.assertEqual(stats.evaluate_criteria(s, b, candidate='CAND', rv=self.RV_OK)['failed'], ['K1'])

    def test_rv_missing_and_methods(self):
        s, b = _summary()
        self.assertEqual(stats.evaluate_criteria(s, b, candidate='CAND', rv=None)['failed'], ['RV'])
        r = stats.evaluate_criteria(s, b, candidate='CAND', rv={'all_multi_measured_agree': False,
                                                                 'disagreeing_configs': ['x/y']})
        self.assertEqual(r['failed'], ['RV'])
        s['s1']['CAND']['diff']['Random']['unique_false_pass'] = {'ci': [0.1, 0.3], 'boot_ci': [-0.1, 0.3]}
        self.assertTrue(stats.evaluate_criteria(s, b, candidate='CAND', rv=self.RV_OK)['adopt'])
        self.assertEqual(stats.evaluate_criteria(s, b, candidate='CAND', rv=self.RV_OK,
                                                 ci_method='bootstrap')['failed'], ['G'])
        del s['a1']['CAND']['diff']['C9-UCBMean']
        self.assertIn('K1', stats.evaluate_criteria(s, b, candidate='CAND', rv=self.RV_OK)['failed'])
        with self.assertRaises(ValueError):
            stats.evaluate_criteria(s, dict(b, abrupt=[]), candidate='CAND', rv=self.RV_OK)

    def test_caver9_summary_format(self):
        s = {sc: {'CAND': {f'diff_unique_false_pass_vs_{r}_ci': [0.1, 0.5]
                           for r in ('CAVER-v0.6', 'C9-UCBMean', 'Random', 'SW-UCB', 'D-UCB')},
                  'CAVER-v0.6': {'false_alarm_rate': None}} for sc in ('s', 'f', 'a')}
        for r in ('CAVER-v0.6', 'C9-UCBMean'):
            s['a']['CAND'][f'diff_recovery_steps_vs_{r}_ci'] = [-2.0, -0.5]
        b = {'stationary': ['s'], 'flat_shift': ['f'], 'abrupt': ['a'], 'all': ['s', 'f', 'a']}
        self.assertTrue(stats.evaluate_criteria(s, b, candidate='CAND', rv=self.RV_OK)['adopt'])


if __name__ == '__main__':
    unittest.main()
