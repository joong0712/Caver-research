#!/usr/bin/env python3
"""MOCK of `claude -p` Hook handling. NOT Claude Code. Results are `simulated`.

Emulates one agent turn that attempts exactly the pre-approved Bash command
(taken from --allowedTools 'Bash(<cmd>)'), runs the configured PreToolUse hooks,
then permission check, execution and PostToolUse hooks.

Every semantic choice below is a MODEL ASSUMPTION written from the public Hook
documentation; points marked [ASSUMPTION] are exactly what a real CLI run must
verify. Do not cite mock outcomes as Claude Code behaviour.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

ASSUMPTIONS = {
    'matcher': '[ASSUMPTION] "*"/"" match all; otherwise case-sensitive regex full match',
    'exit2': 'exit code 2 blocks the tool call (stdout ignored)',
    'exit_other': ('other non-zero exit = non-blocking error; stdout JSON ignored; onFailure:block denies. '
                   'REFUTED by real CLI 2.1.319 (2026-11-08): a stdout deny JSON WAS honoured on exit 1 and 137; '
                   'mock behaviour left unchanged so outcome_table_simulated*.json stay reproducible'),
    'timeout': 'timeout = non-blocking error (partial stdout ignored); onFailure:block denies',
    'invalid_value': '[ASSUMPTION] unknown permissionDecision value / wrong hookEventName = hook error',
    'top_level_permissionDecision': 'ignored (not a PreToolUse decision field)',
    'legacy_decision': '[ASSUMPTION] deprecated top-level decision:block still denies',
    'non_json_stdout': '[ASSUMPTION] non-JSON stdout on exit 0 = no decision',
    'permission': '[ASSUMPTION] allowedTools Bash(<cmd>) matches the exact command string only',
}


def matcher_matches(matcher: str, tool: str) -> bool:
    if matcher in ('', '*'):
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return False


def interpret(proc_code: int | None, stdout: str) -> str:
    """Return deny | allow | ask | none | error for one hook."""
    if proc_code is None:
        return 'error'  # timeout
    if proc_code == 2:
        return 'deny'
    if proc_code != 0:
        return 'error'
    text = stdout.strip()
    if not text:
        return 'none'
    try:
        doc = json.loads(text)
    except ValueError:
        return 'none'
    if not isinstance(doc, dict):
        return 'error'
    spec = doc.get('hookSpecificOutput')
    if spec is not None:
        if not isinstance(spec, dict) or spec.get('hookEventName') != 'PreToolUse':
            return 'error'
        choice = spec.get('permissionDecision')
        if choice is None:
            return 'none'
        return choice if choice in ('deny', 'allow', 'ask') else 'error'
    legacy = doc.get('decision')
    if legacy == 'block':
        return 'deny'
    if legacy == 'approve':
        return 'allow'
    return 'none'


def run_hooks(groups, event, root: Path, phase: str) -> list[str]:
    decisions = []
    for group in groups:
        if not matcher_matches(group.get('matcher', ''), event['tool_name']):
            continue
        for h in group['hooks']:
            argv = [h['command'], *(a.replace('${CLAUDE_PROJECT_DIR}', str(root)) for a in h.get('args', []))]
            try:
                p = subprocess.run(argv, input=json.dumps(event), capture_output=True, text=True,
                                   cwd=root, timeout=h.get('timeout', 60))
                verdict = interpret(p.returncode, p.stdout)
            except subprocess.TimeoutExpired:
                verdict = interpret(None, '')
            if verdict == 'error' and h.get('onFailure') == 'block':
                verdict = 'deny'
            if phase == 'pre':
                decisions.append(verdict)
    return decisions


def main() -> int:
    args = sys.argv[1:]
    allowed = args[args.index('--allowedTools') + 1]
    m = re.fullmatch(r'Bash\((.*)\)', allowed, re.S)
    command = m.group(1)
    root = Path.cwd()
    settings = json.loads((root / '.claude' / 'settings.local.json').read_text())['hooks']
    event = {'hook_event_name': 'PreToolUse', 'session_id': 'mock-session', 'cwd': str(root),
             'tool_name': 'Bash', 'tool_input': {'command': command, 'description': 'probe'},
             'tool_use_id': 'mock-tool-1'}
    decisions = run_hooks(settings.get('PreToolUse', []), event, root, 'pre')
    denials = []
    if 'deny' in decisions:
        outcome = 'denied by PreToolUse hook'
        denials.append({'tool_name': 'Bash', 'tool_input': event['tool_input']})
    elif 'allow' in decisions or command == allowed[5:-1]:
        subprocess.run(command, shell=True, cwd=root, capture_output=True)
        post = dict(event, hook_event_name='PostToolUse', tool_response={'stdout': '', 'stderr': ''})
        run_hooks(settings.get('PostToolUse', []), post, root, 'post')
        outcome = 'executed'
    else:  # pragma: no cover - unreachable with exact allow rule
        outcome = 'denied by permission rules'
        denials.append({'tool_name': 'Bash', 'tool_input': event['tool_input']})
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'mock': True,
                      'result': f'MOCK: {outcome}', 'num_turns': 2, 'total_cost_usd': 0.0,
                      'hook_decisions': decisions, 'permission_denials': denials}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
