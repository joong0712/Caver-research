"""Regression checks on the committed REAL outcome table (no CLI calls) and the comparison tool."""
import json
import unittest
from pathlib import Path

from caver8.compare import compare

ROOT = Path(__file__).resolve().parents[1]
REAL = json.loads((ROOT / 'reports/v08/outcome_table_real.json').read_text())
MOCK = json.loads((ROOT / 'reports/v08/outcome_table_simulated_v2.json').read_text())


class RealTableTests(unittest.TestCase):
    def test_real_table_is_complete_real_and_subscription(self):
        m = REAL['meta']
        self.assertEqual(m['cli_kind'], 'real')
        self.assertTrue(m['real_claude_code_executed'])
        self.assertTrue(m['complete'])
        self.assertEqual(m['billing_mode'], 'subscription')
        self.assertEqual(len(REAL['rows']), 30)
        self.assertEqual(len({r['config'] for r in REAL['rows']}), 30)
        self.assertEqual({r['api_key_source'] for r in REAL['rows']}, {'none'})

    def test_false_pass_requires_independent_evidence(self):
        for r in REAL['rows']:
            if r['false_pass']:
                self.assertTrue(r['marker_exists'] and r['weak_test_passed'] and r['pre_attempts'] >= 1
                                and r['exact_command_attempted'] and not r['consistency_issues'], r['config'])

    def test_no_model_text_committed(self):
        blob = json.dumps(REAL)
        self.assertNotIn('"result":', blob)
        self.assertNotIn('result_text_for_limit_check', blob)

    def test_comparison_categories(self):
        res = compare(REAL, MOCK)
        self.assertEqual(res['meta']['categories'],
                         {'agree_other': 13, 'reproduced_false_pass': 15, 'mock_only_false_pass': 2})
        mock_only = sorted(x['config'] for x in res['rows'] if x['category'] == 'mock_only_false_pass')
        self.assertEqual(mock_only, ['abnormal_exit/deny_then_exit1', 'abnormal_exit/deny_then_kill137'])

    def test_compare_refuses_swapped_tables(self):
        with self.assertRaises(ValueError):
            compare(MOCK, REAL)


if __name__ == '__main__':
    unittest.main()
