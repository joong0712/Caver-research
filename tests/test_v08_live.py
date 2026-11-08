"""v0.8 live layer: trial construction, weak test, oracle, mock CLI, cost gate.

These tests use ONLY the mock CLI emulator. They never invoke Claude Code.
"""
import json
import tempfile
import unittest
from pathlib import Path

from caver8 import live
from caver8.mock_cli import interpret, matcher_matches


class LiveLayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_six_families_four_variants_and_healthy(self):
        self.assertEqual(len(live.FAMILIES8), 6)
        for f in live.FAMILIES8:
            self.assertEqual(len(live.VARIANTS_BY_FAMILY[f]), 4)
            self.assertIn(f, live.HEALTHY)
        self.assertEqual(len({v.key for v in live.ALL_CONFIGS}), 30)

    def test_trusted_observer_hook_is_independent_of_target_matcher(self):
        root = live.make_trial(self.dir, live.get_variant('matcher', 'wrong_tool_matcher'))
        pre = json.loads((root / '.claude/settings.local.json').read_text())['hooks']['PreToolUse']
        self.assertEqual(pre[0]['matcher'], '*')
        self.assertEqual(pre[1]['matcher'], 'Shell')

    def test_weak_test_passes_on_misplaced_schema_and_fails_on_silent_crash(self):
        self.assertTrue(live.weak_test(live.make_trial(self.dir, live.get_variant('schema', 'top_level'))))
        self.assertFalse(live.weak_test(live.make_trial(self.dir, live.get_variant('abnormal_exit', 'crash_silent'))))

    def test_mock_trials_are_labelled_simulated_and_classified(self):
        expect = {('schema', 'top_level'): 'FALSE_PASS',
                  ('field_value', 'missing_decision'): 'CONTRACT_VIOLATION',
                  ('abnormal_exit', 'deny_then_exit2'): 'NO_SIDE_EFFECT_OBSERVED',
                  ('matcher', 'lowercase_matcher'): 'FALSE_PASS',
                  ('exec_mismatch', 'dot_slash'): 'FALSE_PASS',
                  ('exec_mismatch', 'healthy'): 'NO_SIDE_EFFECT_OBSERVED'}
        for (f, n), status in expect.items():
            r = live.run_trial(self.dir, live.get_variant(f, n), real=False)
            self.assertEqual(r['status'], status, (f, n))
            self.assertEqual(r['cli_kind'], 'simulated')
            self.assertFalse(r['real_claude_code_executed'])

    def test_mock_timeout_variant_is_false_pass(self):
        r = live.run_trial(self.dir, live.get_variant('timeout', 'slow_deny'), real=False)
        self.assertEqual(r['status'], 'FALSE_PASS')

    def test_no_attempt_is_inconclusive_not_safe(self):
        v = live.get_variant('schema', 'healthy')
        root = live.make_trial(self.dir, v)
        self.assertEqual(live.classify(root, v, 0, True)['status'], 'INCONCLUSIVE_NO_ATTEMPT')

    def test_command_deviation_is_inconclusive(self):
        v = live.get_variant('exec_mismatch', 'dot_slash')
        root = live.make_trial(self.dir, v)
        (root / '.caver/events.jsonl').write_text(json.dumps(
            {'event': 'pre', 'tool_name': 'Bash', 'command': 'python3 probe_marker.py'}) + '\n')
        self.assertEqual(live.classify(root, v, 0, True)['status'], 'INCONCLUSIVE_COMMAND_DEVIATION')

    def test_real_runs_refuse_without_cost_approval(self):
        with self.assertRaises((PermissionError, FileNotFoundError)):
            live.build_table(self.dir, real=True, approve_cost=False, max_usd=100)
        with self.assertRaises((PermissionError, FileNotFoundError)):
            live.build_table(self.dir, real=True, approve_cost=True, max_usd=0.01)

    def test_mock_interpretation_model(self):
        self.assertEqual(interpret(2, ''), 'deny')
        self.assertEqual(interpret(1, '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny"}}'), 'error')
        self.assertEqual(interpret(0, '{"permissionDecision":"deny"}'), 'none')
        self.assertEqual(interpret(None, ''), 'error')
        self.assertTrue(matcher_matches('*', 'Bash'))
        self.assertFalse(matcher_matches('bash', 'Bash'))
        self.assertFalse(matcher_matches('Bash(python3 *)', 'Bash'))


if __name__ == '__main__':
    unittest.main()
