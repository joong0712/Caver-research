"""Run controls for real-CLI mode, tested with a FAKE run_trial: no Claude Code is invoked.

Covers subscription mode (--billing-mode subscription --max-runs), the API-mode USD cap,
duplicate prevention / resume, and graceful stops that keep partial results.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caver8 import live

OAUTH = {'loggedIn': True, 'authMethod': 'oauth_token', 'apiProvider': 'firstParty'}


def fake_row(variant, *, cost=0.02, code=0, is_error=False, limit=False, key_source='none'):
    return {'config': variant.key, 'family': variant.family, 'variant': variant.name, 'cli_kind': 'real',
            'real_claude_code_executed': True, 'trial': 'fake', 'cli_exit_code': code, 'wall_ms': 1.0,
            'usage_limit_hit': limit, 'api_key_source': key_source, 'cli_is_error': is_error,
            'total_cost_usd': cost, 'status': 'NO_SIDE_EFFECT_OBSERVED', 'hook_exit_status': 'exit_0',
            'false_pass': False, 'contract_violated': False}


class RunControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / 'table.json'
        self.calls = []
        patch_which = mock.patch.object(live.shutil, 'which', return_value='/usr/bin/claude')
        patch_which.start()
        self.addCleanup(patch_which.stop)
        self.addCleanup(self.tmp.cleanup)

    def _patch(self, **kw):
        def fake(parent, variant, *, real, timeout, extra_args):
            self.calls.append((variant.key, extra_args))
            return fake_row(variant, **kw)
        return mock.patch.object(live, 'run_trial', side_effect=fake)

    def build(self, **kw):
        args = dict(real=True, billing_mode='subscription', max_runs=30, output=self.out, auth_status=OAUTH)
        args.update(kw)
        return live.build_table(self.dir / 'trials', **args)

    def test_subscription_requires_valid_max_runs(self):
        for bad in (None, 0, 31):
            with self.assertRaises(PermissionError):
                self.build(max_runs=bad)

    def test_subscription_refuses_api_key_or_third_party_provider(self):
        with self.assertRaises(PermissionError):
            live.verify_subscription_auth(OAUTH, {'ANTHROPIC_API_KEY': 'x'})
        with self.assertRaises(PermissionError):
            live.verify_subscription_auth(dict(OAUTH, apiProvider='bedrock'), {})
        with self.assertRaises(PermissionError):
            live.verify_subscription_auth(dict(OAUTH, authMethod='api_key'), {})
        info = live.verify_subscription_auth(OAUTH, {})
        self.assertEqual(info['billing_env_vars_present'], [])

    def test_runs_all_30_once_each_without_duplicates(self):
        with self._patch():
            doc = self.build()
        keys = [k for k, _ in self.calls]
        self.assertEqual(len(keys), 30)
        self.assertEqual(len(set(keys)), 30)
        self.assertTrue(doc['meta']['complete'])
        self.assertEqual(keys[0], 'schema/healthy')

    def test_max_runs_stops_and_resume_never_reruns(self):
        with self._patch():
            doc = self.build(max_runs=10)
        self.assertEqual(len(self.calls), 10)
        self.assertFalse(doc['meta']['complete'])
        self.assertIn('max_runs', doc['meta']['stop_reason'])
        saved = json.loads(self.out.read_text())
        self.assertEqual(len(saved['rows']), 10)
        first = [k for k, _ in self.calls]
        self.calls.clear()
        with self._patch():
            doc = self.build(max_runs=30, resume=True)
        self.assertEqual(len(self.calls), 20)
        self.assertFalse(set(first) & {k for k, _ in self.calls})
        self.assertTrue(doc['meta']['complete'])

    def test_usage_limit_stops_gracefully_and_saves(self):
        with self._patch(code=1, is_error=True, limit=True):
            doc = self.build()
        self.assertEqual(len(self.calls), 1)
        self.assertIn('limit', doc['meta']['stop_reason'])
        self.assertEqual(len(json.loads(self.out.read_text())['rows']), 1)

    def test_two_consecutive_cli_errors_stop(self):
        with self._patch(code=1, is_error=True):
            doc = self.build()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(doc['meta']['stop_reason'], 'two consecutive CLI errors')

    def test_api_key_source_reported_by_cli_stops_subscription_mode(self):
        with self._patch(key_source='ANTHROPIC_API_KEY'):
            doc = self.build()
        self.assertEqual(len(self.calls), 1)
        self.assertIn('apiKeySource', doc['meta']['stop_reason'])

    def test_api_mode_reserve_and_budget_flag(self):
        with self._patch(cost=0.20):
            doc = self.build(billing_mode='api', approve_cost=True, max_usd=1.0, max_runs=None)
        # 1.0 cap, 0.10 reserve: runs at spent 0,.2,.4,.6,.8 -> stops before a 6th
        self.assertEqual(len(self.calls), 5)
        self.assertIn('reserve', doc['meta']['stop_reason'])
        self.assertEqual(self.calls[0][1][0], '--max-budget-usd')

    def test_api_mode_stops_when_cost_not_reported(self):
        with self._patch(cost=None):
            doc = self.build(billing_mode='api', approve_cost=True, max_usd=1.0, max_runs=None)
        self.assertEqual(len(self.calls), 1)
        self.assertIn('cost not reported', doc['meta']['stop_reason'])

    def test_parse_stream_json(self):
        out = '\n'.join(json.dumps(x) for x in (
            {'type': 'system', 'subtype': 'init', 'apiKeySource': 'none', 'model': 'm'},
            {'type': 'assistant'},
            {'type': 'result', 'subtype': 'success', 'is_error': False, 'total_cost_usd': 0.01,
             'permission_denials': [{}], 'result': 'text'}))
        p = live.parse_cli_output(out)
        self.assertEqual((p['api_key_source'], p['total_cost_usd'], p['permission_denials']), ('none', 0.01, 1))


class WrapperTests(unittest.TestCase):
    def test_exit_codes_and_invocation_recorded_through_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            for name, status in (('deny_then_kill137', 'exit_137'), ('deny_then_exit2', 'exit_2')):
                r = live.run_trial(Path(d), live.get_variant('abnormal_exit', name), real=False)
                self.assertEqual(r['hook_exit_status'], status)
            r = live.run_trial(Path(d), live.get_variant('matcher', 'wrong_tool_matcher'), real=False)
            self.assertFalse(r['target_hook_invoked'])
            self.assertEqual(r['status'], 'FALSE_PASS')


if __name__ == '__main__':
    unittest.main()
