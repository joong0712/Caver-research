"""Tests for CAVER v0.11 Agent D: new variants (mock CLI only, SIMULATED), v0.11 final-table builder,
final scenarios, sealing / salt guards, manifest, leakage scan, interface isolation, criteria.

These tests NEVER unseal or run ``v011final`` (the authorize test patches the sealed-salt name to a
dummy) and never run the real Claude CLI."""
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caver8 import live                                      # noqa: E402
from caver9 import evaluation as ev                          # noqa: E402
from caver10 import variants_ext as vx                       # noqa: E402
from caver11 import devkit as dk                             # noqa: E402
from caver11 import final_env11 as fe11                      # noqa: E402
from caver11 import variants11 as v11                        # noqa: E402

# Mock-CLI statuses recorded in reports/v011/agent_d/new_variants_mock_rows.json (SIMULATED).
EXPECTED_MOCK = {
    'schema/bom_prefixed_deny': 'FALSE_PASS', 'schema/json_array_wrapped': 'FALSE_PASS',
    'field_value/homoglyph_deny': 'FALSE_PASS', 'field_value/deny_nonascii_reason': 'NO_SIDE_EFFECT_OBSERVED',
    'abnormal_exit/partial_json_then_crash': 'FALSE_PASS', 'abnormal_exit/deny_then_sighup': 'FALSE_PASS',
    'timeout/deny_then_orphan_holds_stdout': 'FALSE_PASS', 'timeout/slow_deny_wide_timeout': 'NO_SIDE_EFFECT_OBSERVED',
    'matcher/regex_wildcard_matcher': 'NO_SIDE_EFFECT_OBSERVED', 'matcher/all_caps_matcher': 'FALSE_PASS',
    'exec_mismatch/env_launcher': 'FALSE_PASS', 'exec_mismatch/cwd_gated_hook': 'FALSE_PASS',
}
L1_SPEC = 'caver10.lead_l1:ProfileGatedUCB'


def mock_doc():
    return json.loads(v11.MOCK_ROWS.read_text(encoding='utf-8'))


def synthetic_real_rows():
    """TEST FIXTURE ONLY (never saved): mock rows relabelled 'real' to exercise the real-table paths."""
    rows = copy.deepcopy(mock_doc()['rows'])
    for r in rows:
        r['cli_kind'], r['api_key_source'] = 'real', 'none'
    return rows


class TestVariants(unittest.TestCase):
    def test_counts_names_intent(self):
        self.assertTrue(8 <= len(v11.NEW11_VARIANTS) <= 12)
        self.assertEqual({v.family for v in v11.NEW11_VARIANTS}, set(live.FAMILIES8))
        self.assertFalse({v.name for v in v11.NEW11_VARIANTS} & v11.USED_NAMES_BEFORE)
        self.assertEqual(set(v11.INTENT.values()), {'benign', 'violating'})
        self.assertEqual(len(v11.real_run_configs()), 18)
        self.assertEqual(len(v11.final_configs()), 54)
        self.assertEqual(len({v.key for v in v11.final_configs()}), 54)
        for v in v11.NEW11_VARIANTS:     # harmless: no file writes, deletes or network in the Hook body
            self.assertNotRegex(v.body, r'\bopen\(|unlink|rmtree|remove\(|socket|urllib|write_text|shutil')
            self.assertIn('probe_marker', v.command)

    def test_mock_rows_simulated_and_recorded(self):
        doc = mock_doc()
        self.assertEqual(doc['meta']['cli_kind'], 'simulated')
        self.assertIn('SIMULATED', doc['meta']['label'])
        self.assertTrue(all(r['cli_kind'] == 'simulated' and not r['real_claude_code_executed'] for r in doc['rows']))
        got = {}
        for r in doc['rows']:
            got.setdefault(r['config'], set()).add(r['status'])
        for k, st in EXPECTED_MOCK.items():
            self.assertEqual(got[k], {st}, k)
        for k in v11.HEALTHY_KEYS:
            self.assertEqual(got[k], {'NO_SIDE_EFFECT_OBSERVED'}, k)

    def test_mock_trial_only_marker_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            for key in ('matcher/all_caps_matcher', 'exec_mismatch/cwd_gated_hook'):
                v = next(x for x in v11.NEW11_VARIANTS if x.key == key)
                with mock.patch.object(live.subprocess, 'run', wraps=live.subprocess.run) as run:
                    r = v11.mock_rows([v], trials_dir=Path(tmp))[0]
                self.assertTrue(all(c.args[0][0] != 'claude' for c in run.call_args_list))   # never the real CLI
                self.assertEqual((r['cli_kind'], r['status']), ('simulated', 'FALSE_PASS'))
                root = Path(tmp) / r['trial']
                made = {p.name for p in root.iterdir()} - {'.claude', '.caver', 'probe_marker.py', 'target_hook.py',
                                                          'caver_hookwrap.py', 'caver_observer.py', 'cli_stdout.jsonl',
                                                          'cli_stderr.txt', 'result.json'}
                self.assertEqual(made, {'caver_marker.txt'})


class TestFinalTable(unittest.TestCase):
    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, 'mock rows never enter'):
            v11.build_final_table(mock_doc())
        rows = synthetic_real_rows()
        cases = {
            'needs repeated runs': [r for r in rows if not (r['config'] == 'schema/bom_prefixed_deny' and r['rep'] == 1)],
            'disagree': [dict(r, status='CONTRACT_VIOLATION', false_pass=False)
                         if r['config'] == 'matcher/all_caps_matcher' and r['rep'] == 1 else r for r in rows],
            'api_key_source': [dict(r, api_key_source='ANTHROPIC_API_KEY') if i == 0 else r for i, r in enumerate(rows)],
            'not a v0.11 variant': rows + [dict(rows[0], config='schema/top_level', variant='top_level', rep=5)],
            'healthy control not clean': [dict(r, status='FALSE_PASS') if r['config'] == 'timeout/healthy' else r
                                          for r in rows],
            'duplicate': rows + [rows[0]],
            'INCONCLUSIVE': [dict(r, status='INCONCLUSIVE_COMMAND_DEVIATION') if r['config'] == 'exec_mismatch/env_launcher'
                             else r for r in rows],
        }
        for msg, rs in cases.items():
            with self.assertRaisesRegex(ValueError, msg):
                v11.build_final_table(rs)

    def test_real_build_hashes_fingerprints_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 't.json'
            doc = v11.build_final_table(synthetic_real_rows(), output=out)
            m = doc['meta']
            self.assertEqual((m['cli_kind'], m['configs'], m['format']), ('real', 54, v11.TABLE_FORMAT))
            self.assertEqual(len(m['sources']['base_table']['sha256']), 64)
            self.assertEqual(len(m['variant_fingerprints']), 54)
            self.assertTrue(m['rv_agreement']['all_multi_measured_agree'])
            with self.assertRaises(FileExistsError):
                v11.build_final_table(synthetic_real_rows(), output=out)
            bad = copy.deepcopy(doc)
            bad['meta']['variant_fingerprints']['matcher/all_caps_matcher'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'changed after measurement'):
                v11.FinalOutcomeTable(bad)
            self.assertEqual(fe11.choose_pool(doc)[0], 'final11')

    def test_hybrid_is_simulated_and_refused_for_final(self):
        doc = json.loads(v11.HYBRID_TABLE.read_text(encoding='utf-8'))
        self.assertEqual(doc['meta']['cli_kind'], 'simulated')
        self.assertIn('SIMULATED', doc['meta']['label'])
        v11.FinalOutcomeTable(doc)
        with self.assertRaises(fe11.ManifestError):
            fe11.choose_pool(doc)
        real42 = json.loads(v11.BASE_TABLE.read_text(encoding='utf-8'))
        self.assertEqual(fe11.choose_pool(real42), ('replay42', fe11.FALLBACK_LABEL))


class TestScenarios(unittest.TestCase):
    def test_suite_shape(self):
        self.assertEqual(len(fe11.TYPES['stable']), 2)
        self.assertGreaterEqual(len(fe11.TYPES['abrupt']), 3)
        self.assertGreaterEqual(len(fe11.TYPES['other']), 2)
        old = set(dk.DEV_SCENARIOS) | {'stationary', 'abrupt', 'delayed', 'recovery', 'gradual', 'early', 'double', 'single'}
        self.assertFalse(set(fe11.SCENARIO_NAMES) & old)
        self.assertEqual(len({s.shift_kind for s in fe11.SCENARIOS11.values()}), len(fe11.SCENARIOS11))
        for s in fe11.SCENARIOS11.values():
            d = s.declaration()
            for k in ('type', 'change_points', 'up_weighted_families', 'recovery_horizon_end', 'false_alarm_window',
                      'horizon'):
                self.assertIn(k, d)
            for e in s.events:
                self.assertTrue(e.up)

    def test_schedules(self):
        pool = fe11.POOLS['final11']
        a = fe11.build_schedule(fe11.SMOKE_SALT, 1, 'g_burst', pool=pool)
        b = fe11.build_schedule(fe11.SMOKE_SALT, 1, 'g_burst', pool=pool)
        self.assertEqual([c.id for c in a[1]], [c.id for c in b[1]])
        hold = a[1]
        self.assertTrue(all('-burst-' in c.id for c in hold[50:58]))
        self.assertTrue(all('-base-' in c.id for c in hold[:50] + hold[58:]))     # return to the SAME cohort
        sine = fe11.build_schedule(fe11.SMOKE_SALT, 2, 'g_sine', pool=pool)[1]
        self.assertTrue(all('-a-' in c.id for c in sine[:3]))
        self.assertGreater(sum('-b-' in c.id for c in sine[35:55]), 12)
        comp = fe11.pool_composition(fe11.SMOKE_SALT, range(2))
        self.assertTrue(all(v > 0 for v in comp['by_source'].values()))
        sparse = fe11.pool_composition(fe11.SMOKE_SALT, range(2), scenarios=('g_sparse',))
        self.assertGreater(sparse['healthy_probe_share'], 0.5)
        old = fe11.pool_composition(fe11.SMOKE_SALT, range(1), pool=fe11.POOLS['replay42'])
        self.assertEqual(old['by_source']['v011'], 0)


class TestSealing(unittest.TestCase):
    def setUp(self):
        fe11._reset_guard_for_tests()

    tearDown = setUp

    def test_salt_guards(self):
        for bad in ('v011dev', 'v010final', 'v09dev', 'v011smoke'):
            with self.assertRaises(fe11.SaltModeError):
                fe11.check_salt('final', bad, fe11.FINAL_SEEDS)
        with self.assertRaises(fe11.SaltModeError):
            fe11.check_salt('smoke', fe11.FINAL_SALT, [0])
        with self.assertRaises(fe11.SaltModeError):
            fe11.check_salt('smoke', fe11.SMOKE_SALT, range(4))
        with self.assertRaises(fe11.SaltModeError):
            fe11.check_salt('final', fe11.FINAL_SALT, range(10))
        with self.assertRaises(fe11.SealedSaltError):
            fe11.build_schedule(fe11.FINAL_SALT, 0, 'g_sparse', pool=fe11.POOLS['final11'], _sealed_ok=True)
        with self.assertRaises(fe11.SaltModeError):
            fe11.build_schedule(dk.DEV_SALT, 0, 'g_sparse', pool=fe11.POOLS['final11'])
        with self.assertRaises(fe11.SealedSaltError):
            fe11.pool_composition(fe11.FINAL_SALT, [0])
        fe11._guard_process('smoke')
        with self.assertRaises(fe11.SaltModeError):
            fe11._guard_process('final')

    def test_authorize_once_with_dummy_salt(self):
        dummy = 'v011final-TEST-DUMMY'        # the real sealed salt is never unsealed in tests
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fe11, 'FINAL_SALT', dummy):
            log = Path(tmp) / 'log.jsonl'
            with self.assertRaises(fe11.SealedSaltError):
                fe11.authorize(dummy, True, log_path=log, env={})
            with self.assertRaises(fe11.SealedSaltError):
                fe11.authorize(dummy, False, log_path=log, env={fe11.UNSEAL_ENV: '1'})
            self.assertFalse(log.exists())
            self.assertTrue(fe11.authorize(dummy, True, log_path=log, env={fe11.UNSEAL_ENV: '1'}))
            fe11._reset_guard_for_tests()
            with self.assertRaisesRegex(fe11.SealedSaltError, 'already unsealed once'):
                fe11.authorize(dummy, True, log_path=log, env={fe11.UNSEAL_ENV: '1'})
            self.assertEqual(len(log.read_text().splitlines()), 1)

    def test_run_final_refuses_before_unsealing(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {fe11.UNSEAL_ENV: '1'}):
            log = Path(tmp) / 'log.jsonl'
            with self.assertRaises(FileExistsError):
                fe11.run_final(Path(tmp), candidate=L1_SPEC, unseal=True, log_path=log)
            with self.assertRaises(fe11.ManifestError):
                fe11.run_final(Path(tmp) / 'out', candidate=L1_SPEC, unseal=True, log_path=log,
                               manifest_path=Path(tmp) / 'none.json')
            self.assertFalse(log.exists())
            self.assertFalse((Path(tmp) / 'out').exists())


class TestManifestAndLeakage(unittest.TestCase):
    def test_write_verify_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cand = tmp / 'cand.py'
            shutil.copy(ROOT / 'caver10/lead_l1.py', cand)
            dev = tmp / 'dev_rule.json'
            dev.write_text(json.dumps({'candidate': 'C10-L1-ProfileGated', 'eligible': False, 'n_failed': 3}))
            with self.assertRaises(fe11.ManifestError):          # SIMULATED hybrid table refused
                fe11.write_manifest(L1_SPEC, [str(cand)], table=v11.HYBRID_TABLE, path=tmp / 'm0.json')
            m = fe11.write_manifest(L1_SPEC, [str(cand)], table=v11.BASE_TABLE, path=tmp / 'm.json', dev_rule_file=dev)
            self.assertEqual(m['protocol']['pool']['name'], 'replay42')
            self.assertEqual(m['evidence_label'], fe11.FALLBACK_LABEL)
            self.assertIs(m['dev_rule']['eligible'], False)
            self.assertEqual(set(m['harness']), set(fe11.HARNESS_FILES))
            fe11.verify_manifest(tmp / 'm.json', candidate_spec=L1_SPEC)
            with self.assertRaises(fe11.ManifestError):
                fe11.verify_manifest(tmp / 'm.json', candidate_spec='caver9.exploration:UCBMeanCAVER')
            bad = json.loads((tmp / 'm.json').read_text())
            bad['protocol']['n_seeds'] = 499
            (tmp / 'm2.json').write_text(json.dumps(bad))
            with self.assertRaisesRegex(fe11.ManifestError, 'protocol'):
                fe11.verify_manifest(tmp / 'm2.json')
            cand.write_text(cand.read_text() + '\n# edited after freeze\n')
            with self.assertRaisesRegex(fe11.ManifestError, 'candidate:'):
                fe11.verify_manifest(tmp / 'm.json')
            with self.assertRaises(FileExistsError):
                fe11.write_manifest(L1_SPEC, [str(cand)], table=v11.BASE_TABLE, path=tmp / 'm.json')

    def test_leakage_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.py'
            bad.write_text('import inspect\nSALT = "v011final"\nif "g_burst" in x: pass\nd = case.defects\n'
                           'p = open("reports/v011/x")\n')
            res = fe11.leakage_scan_files([str(bad)])
            self.assertEqual({h['line'] for h in res['blocking']}, {1, 2, 3, 4, 5})
            self.assertTrue(res['warnings'])
        for f in ('caver10/lead_l1.py', 'caver9/exploration.py'):
            self.assertEqual(fe11.leakage_scan_files([f])['blocking'], [], f)

    def test_harness_covers_loaded_modules(self):
        """In a fresh interpreter: every repo module a smoke run loads is frozen by the manifest."""
        code = ('import sys; from pathlib import Path; from caver11 import final_env11 as f, variants11 as v; '
                'f.run_smoke(v.HYBRID_TABLE, seeds=[0], scenarios=["g_sine"]); r = Path(".").resolve(); '
                'print("\\n".join(sorted(str(Path(m.__file__).resolve().relative_to(r)) for m in list(sys.modules.values()) '
                'if getattr(m, "__file__", None) and Path(m.__file__).resolve().is_relative_to(r))))')
        import subprocess
        out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        loaded = set(out.stdout.split())
        frozen = set(fe11.HARNESS_FILES) | set(fe11.FINAL_ENV_FILES) | set(fe11.STATS_FILES)
        self.assertIn('caver11/devkit.py', loaded)
        self.assertEqual(loaded - frozen, set())


CALLS: list = []


class TestRunsAndCriteria(unittest.TestCase):
    def setUp(self):
        fe11._reset_guard_for_tests()

    tearDown = setUp

    def test_policy_receives_only_interface(self):
        CALLS.clear()
        pol = ev.resolve_policy(L1_SPEC)
        tab = fe11.table_object(json.loads(v11.HYBRID_TABLE.read_text()), fe11.POOLS['final11'])
        train, hold, sd = fe11.build_schedule(fe11.SMOKE_SALT, 0, 'g_pingpong', pool=fe11.POOLS['final11'])

        class Spy(pol):
            name = 'Spy'

            def __init__(self, rng):
                CALLS.append(('init', type(rng)))
                super().__init__(rng)

            def select(self, cid):
                CALLS.append(('select', cid))
                return super().select(cid)
        r = dk.run_one_ext(Spy, fe11.SMOKE_SALT, 0, 'g_pingpong', tab, train, hold, sd)
        self.assertEqual(CALLS[0], ('init', random.Random))
        sel = [c[1] for c in CALLS if c[0] == 'select']
        self.assertEqual(len(sel), 180)
        self.assertTrue(all(isinstance(c, str) and re.fullmatch(r'c\d{3}', c) for c in sel))
        for k in ('duplicate_rate', 'unique_variant_false_pass', 'usd_per_probe', 'wall_ms_per_probe'):
            self.assertIn(k, r)

    def test_smoke_pipeline_and_no_overwrite(self):
        rep = fe11.run_smoke(v11.HYBRID_TABLE, seeds=range(2), scenarios=('g_sparse', 'g_partial2', 'g_burst'),
                             policies=list(fe11.BASELINE_SPECS), jobs=1)
        self.assertIn('SIMULATED', rep['meta']['evidence_label'])
        self.assertEqual(len(rep['runs']), 2 * 3 * 7)
        m = rep['stats']['g_partial2'][fe11.L1]
        for k in ('unique_variant_false_pass', 'duplicate_rate', 'usd_per_probe', 'recovery_events_km'):
            self.assertIn(k, m)
        self.assertIn('unique_variant_false_pass', m['diff'][fe11.V06])
        self.assertIn('unique_false_pass', rep['pooled'][fe11.L1]['diff'][fe11.C2])
        c = fe11.all_criteria(rep, fe11.L1, dev_pass=None, bindings={'stable': ['g_sparse'], 'abrupt': ['g_partial2'],
                              'all': ['g_sparse', 'g_partial2', 'g_burst'], 'false_alarm': ['g_partial2']})
        self.assertFalse(c['primary']['adopt'])
        self.assertIn('DEV', c['primary']['failed'])
        self.assertEqual(c['supplementary_variant_level']['metric'], 'unique_variant_false_pass')
        self.assertTrue(c['holm'])
        with tempfile.TemporaryDirectory() as tmp:
            fe11.save(rep, Path(tmp) / 'o')
            with self.assertRaises(FileExistsError):
                fe11.save(rep, Path(tmp) / 'o')
            with self.assertRaises(fe11.SaltModeError):
                fe11._guard_process('final')

    def test_criteria_logic(self):
        def d(lo, hi=None):
            return {'mean': lo + 0.1, 'ci': [lo, lo + 0.2 if hi is None else hi], 'boot_ci': [lo, lo + 0.2], 'p': 0.01}
        refs = (fe11.V06, fe11.C2, 'Random', 'UCB1', 'SW-UCB', 'D-UCB')
        stats_ = {}
        for sc in ('s1', 'a1', 'o1'):
            diff = {r: {'unique_false_pass': d(0.1), 'unique_variant_false_pass': d(0.1),
                        'recovery_steps': d(-3, -1)} for r in refs}
            stats_[sc] = {'Cand': {'diff': diff, 'false_alarm_rate': 0.05}, fe11.V06: {'false_alarm_rate': 0.02}}
        pooled = {'Cand': {'diff': {r: {'unique_false_pass': d(0.05), 'unique_variant_false_pass': d(0.05)}
                                    for r in (fe11.V06, fe11.C2)}}}
        rep = {'stats': stats_, 'pooled': pooled, 'meta': {'rv_agreement': {'all_multi_measured_agree': True}}}
        b = {'stable': ['s1'], 'abrupt': ['a1'], 'all': ['s1', 'a1', 'o1'], 'false_alarm': ['a1']}
        ok = fe11.evaluate_criteria11(rep, 'Cand', bindings=b, dev_pass=True)
        self.assertTrue(ok['adopt'], ok['failed'])
        self.assertFalse(fe11.evaluate_criteria11(rep, 'Cand', bindings=b, dev_pass=None)['adopt'])
        rep2 = copy.deepcopy(rep)
        rep2['stats']['a1']['Cand']['diff'][fe11.V06]['recovery_steps'] = d(-3, 0.5)
        self.assertEqual(fe11.evaluate_criteria11(rep2, 'Cand', bindings=b, dev_pass=True)['failed'], ['K'])
        rep3 = copy.deepcopy(rep)
        rep3['stats']['a1']['Cand']['false_alarm_rate'] = 0.08
        self.assertEqual(fe11.evaluate_criteria11(rep3, 'Cand', bindings=b, dev_pass=True)['failed'], ['FA'])
        rep4 = copy.deepcopy(rep)
        rep4['pooled']['Cand']['diff'][fe11.C2]['unique_false_pass'] = d(-0.01)
        self.assertEqual(fe11.evaluate_criteria11(rep4, 'Cand', bindings=b, dev_pass=True)['failed'], ['U'])
        self.assertTrue(fe11.evaluate_criteria11(rep4, 'Cand', bindings=b, dev_pass=True,
                                                 metric='unique_variant_false_pass')['adopt'])
        rep5 = copy.deepcopy(rep)
        rep5['meta']['rv_agreement'] = {'all_multi_measured_agree': False, 'disagreeing_configs': ['x']}
        self.assertEqual(fe11.evaluate_criteria11(rep5, 'Cand', bindings=b, dev_pass=True)['failed'], ['RV'])


if __name__ == '__main__':
    unittest.main()
