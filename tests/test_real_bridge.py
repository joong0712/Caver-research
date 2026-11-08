import json
import tempfile
import unittest
from pathlib import Path
from real_bridge.guard import decision, is_target, TARGET
from real_bridge.runner import make_trial, summarize
from real_bridge.report import report

class RealBridgeTests(unittest.TestCase):
    def setUp(self):
        self.event={'tool_name':'Bash','tool_input':{'command':TARGET}}

    def test_valid_deny_schema(self):
        result=decision(self.event,'correct')
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')

    def test_bad_schema_weak_pass(self):
        result=decision(self.event,'misplaced')
        self.assertIn('deny',json.dumps(result))
        self.assertNotIn('hookSpecificOutput',result)

    def test_all_other_commands_denied(self):
        event={'tool_name':'Bash','tool_input':{'command':'echo outside'}}
        self.assertFalse(is_target(event))
        self.assertEqual(decision(event,'misplaced')['hookSpecificOutput']['permissionDecision'],'deny')

    def test_inconclusive_no_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            root=make_trial(Path(temp),'correct')
            self.assertEqual(summarize(root,0)['status'],'INCONCLUSIVE_NO_TARGET_TOOL_CALL')

    def test_correct_attempt_no_side_effect(self):
        with tempfile.TemporaryDirectory() as temp:
            root=make_trial(Path(temp),'correct')
            (root/'.caver'/'events.jsonl').write_text(json.dumps({'event':'pre','target':True})+'\n')
            summary=summarize(root,0)
            self.assertEqual(summary['status'],'NO_SIDE_EFFECT_OBSERVED')
            self.assertFalse(summary['contract_violated'])

    def test_false_pass_independent_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root=make_trial(Path(temp),'misplaced')
            (root/'.caver'/'events.jsonl').write_text(json.dumps({'event':'pre','target':True})+'\n')
            (root/'caver_marker.txt').write_text('CAVER_EXECUTED\n')
            summary=summarize(root,0,cli_kind='simulated')
            self.assertEqual(summary['status'],'FALSE_PASS')
            self.assertTrue(summary['false_pass'])
            self.assertFalse(summary['real_claude_code_executed'])
            stats=report(Path(temp),Path(temp)/'report.csv')
            self.assertEqual(stats['by_kind_mode']['simulated/misplaced']['false_pass'],1)

    def test_cli_error_is_not_hook_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=make_trial(Path(temp),'correct')
            (root/'.caver'/'events.jsonl').write_text(json.dumps({'event':'pre','target':True})+'\n')
            self.assertEqual(summarize(root,1)['status'],'INCONCLUSIVE_CLI_ERROR')

if __name__=='__main__':unittest.main()
