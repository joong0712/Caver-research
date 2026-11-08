import json
import subprocess
import sys
import unittest
from pathlib import Path
from caver5.protocol import interpret_pretooluse
from caver5.adapter import probe,independent_oracle,simulated_dispatch
from caver5.fixtures import Case,FAMILIES,make_event

class ProtocolTests(unittest.TestCase):
    def test_json_deny(self):
        payload=json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny'}})
        self.assertTrue(interpret_pretooluse(payload,0).denies)

    def test_exit2_blocks_even_with_allow(self):
        self.assertTrue(interpret_pretooluse('{"hookSpecificOutput":{"permissionDecision":"allow"}}',2).denies)

    def test_top_level_deny_not_decision(self):
        self.assertFalse(interpret_pretooluse('{"permissionDecision":"deny"}',0).denies)

    def test_onfailure_block_for_exit_nonzero(self):
        self.assertFalse(interpret_pretooluse('',1,on_failure='continue').denies)
        self.assertTrue(interpret_pretooluse('',1,on_failure='block').denies)

    def test_onfailure_block_for_malformed_json(self):
        self.assertTrue(interpret_pretooluse('{"x":',0,on_failure='block').denies)

    def test_onfailure_block_for_timeout(self):
        self.assertTrue(interpret_pretooluse('',124,timed_out=True,on_failure='block').denies)

    def test_permission_ask_is_not_dispatch(self):
        payload=json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'ask'}})
        self.assertEqual(interpret_pretooluse(payload,0).status,'ask')

    def test_wrong_schema_modelled_no_decision(self):
        self.assertEqual(interpret_pretooluse('{"permissionDecision":"deny"}',0).status,'permission')

    def test_true_subprocess_and_independent_oracle(self):
        healthy=probe(Case('a','healthy',frozenset()),FAMILIES[0])
        broken=probe(Case('b','wrong_schema',frozenset({FAMILIES[0]})),FAMILIES[0])
        self.assertFalse(healthy.false_pass)
        self.assertTrue(broken.false_pass)
        self.assertFalse(probe(Case('c','nonblocking_exit',frozenset({FAMILIES[0]})),FAMILIES[0],on_failure='block').false_pass)

    def test_safe_guard_contract(self):
        root=Path(__file__).resolve().parents[1]
        event={'hook_event_name':'PreToolUse','tool_name':'Bash',
               'tool_input':{'command':'echo CAVER_RESEARCH_SENTINEL'}}
        res=subprocess.run([sys.executable,str(root/'examples'/'safe_guard.py')],
                           input=json.dumps(event),capture_output=True,text=True,timeout=3)
        self.assertEqual(res.returncode,0)
        self.assertTrue(interpret_pretooluse(res.stdout,res.returncode).denies)
        event['tool_input']['command']='echo SAFE'
        res=subprocess.run([sys.executable,str(root/'examples'/'safe_guard.py')],
                           input=json.dumps(event),capture_output=True,text=True,timeout=3)
        self.assertFalse(interpret_pretooluse(res.stdout,res.returncode).denies)
