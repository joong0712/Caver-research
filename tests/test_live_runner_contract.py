import sys
import tempfile
import unittest
from pathlib import Path
from real_bridge.runner import run_one
from real_bridge.feedback import export_feedback, replay_to_policy

class IntegrationContractTests(unittest.TestCase):
    def test_runner_with_mock_cli_and_oracle(self):
        # This checks the bridge, NOT Claude Code itself.
        with tempfile.TemporaryDirectory() as tmp:
            basedir=Path(tmp)
            fake=Path(__file__).parent/'mock_claude.py'
            for mode, failure, expected in (
                ('correct','block','NO_SIDE_EFFECT_OBSERVED'),
                ('misplaced','block','FALSE_PASS'),
                ('crash','continue','CONTRACT_VIOLATION'),
                ('crash','block','NO_SIDE_EFFECT_OBSERVED'),
            ):
                answer=run_one(basedir,mode,failure,cli=str(fake),cli_kind='simulated')
                self.assertEqual(answer['status'],expected)
                self.assertFalse(answer['real_claude_code_executed'])
            response=export_feedback(basedir,basedir/'real_feedback.jsonl',include_simulated=True)
            self.assertGreater(response['observations'],0)
            reply=replay_to_policy(basedir/'real_feedback.jsonl')
            self.assertEqual(reply['observations_replayed'],response['observations'])

if __name__=='__main__':unittest.main()
