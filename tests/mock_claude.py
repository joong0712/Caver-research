#!/usr/bin/env python3
"""Minimal contract-test double, NOT Claude Code. Used only in automated tests."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

root=Path.cwd()
settings=json.loads((root/'.claude'/'settings.local.json').read_text())
pre=settings['hooks']['PreToolUse'][0]['hooks'][0]
event={'hook_event_name':'PreToolUse','tool_name':'Bash',
       'tool_input':{'command':'python3 probe_marker.py'},'tool_use_id':'mocktool1',
       'session_id':'mock-session'}
res=subprocess.run([pre['command'],*(arg.replace('${CLAUDE_PROJECT_DIR}',str(root)) for arg in pre['args'])],
                   input=json.dumps(event),capture_output=True,text=True,cwd=root)
blocked=(res.returncode==2 or (res.returncode!=0 and pre['onFailure']=='block'))
if res.returncode==0 and res.stdout.strip():
    try:
        doc=json.loads(res.stdout)
        if (doc.get('hookSpecificOutput') or {}).get('permissionDecision')=='deny':
            blocked=True
    except (ValueError,AttributeError):
        blocked=pre['onFailure']=='block'
if not blocked:
    subprocess.run([sys.executable,'probe_marker.py'],cwd=root,check=True)
    post=settings['hooks']['PostToolUse'][0]['hooks'][0]
    event['hook_event_name']='PostToolUse'
    event['tool_response']={'stdout':'','stderr':''}
    subprocess.run([post['command'],*(arg.replace('${CLAUDE_PROJECT_DIR}',str(root)) for arg in post['args'])],
                   input=json.dumps(event),capture_output=True,text=True,cwd=root,check=True)
print(json.dumps({'result':'mock tool blocked' if blocked else 'mock tool executed'}))
