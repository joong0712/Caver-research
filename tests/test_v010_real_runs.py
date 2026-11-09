"""Lead real-batch runner: caps, resume, subscription gate. Uses the MOCK CLI only (no real calls)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caver8 import live
from caver10 import real_runs

MOCK = [sys.executable, str(live.MOCK_CLI)]
OAUTH = {'loggedIn': True, 'authMethod': 'oauth_token', 'apiProvider': 'firstParty', 'billing_env_vars_present': []}


class RealRunsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        for target, value in (('verify_auth', OAUTH), ('cli_version', 'mock')):
            p = mock.patch.object(real_runs, target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_cap_resume_and_schema(self):
        vs = [live.get_variant('schema', 'top_level'), live.get_variant('schema', 'healthy')]
        out = self.d / 't.json'
        doc = real_runs.run_batch(vs, label='T', reps=2, cli=MOCK, prompt_key='alt', max_runs=3, output=out,
                                  trials_dir=self.d / 'tr')
        self.assertEqual(doc['meta']['runs_recorded'], 3)
        self.assertIn('max_runs', doc['meta']['stop_reason'])
        doc = real_runs.run_batch(vs, label='T', reps=2, cli=MOCK, prompt_key='alt', max_runs=3, output=out,
                                  trials_dir=self.d / 'tr')
        self.assertEqual(doc['meta']['runs_recorded'], 4)
        self.assertTrue(doc['meta']['complete'])
        keys = [(r['config'], r['rep']) for r in doc['rows']]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(doc['rows'][0]['status'], 'FALSE_PASS')

    def test_hard_cap(self):
        with self.assertRaises(ValueError):
            real_runs.run_batch([], label='T', reps=1, cli=MOCK, prompt_key='std', max_runs=41,
                                output=self.d / 'x.json', trials_dir=self.d)

    def test_alt_prompt_keeps_exact_command_slot(self):
        self.assertIn('`{cmd}`', real_runs.PROMPT_ALT)
        self.assertNotEqual(real_runs.PROMPT_ALT, real_runs.PROMPT_STD)


class GateTests(unittest.TestCase):
    def test_api_key_refused(self):
        with mock.patch.object(real_runs.subprocess, 'run') as run, mock.patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'x'}):
            run.return_value.stdout = json.dumps({'loggedIn': True, 'authMethod': 'oauth_token', 'apiProvider': 'firstParty'})
            with self.assertRaises(PermissionError):
                real_runs.verify_auth(['claude'])


if __name__ == '__main__':
    unittest.main()
