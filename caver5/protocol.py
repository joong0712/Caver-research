"""Conservative local model of documented Claude Code PreToolUse responses.

Source: https://code.claude.com/docs/en/hooks (checked 2026-11-09).
This is NOT a replacement for a pinned live Claude Code contract test.
The local permission stage is a separate explicitly permissive fake dispatcher.
"""
from __future__ import annotations
import json
from dataclasses import dataclass

@dataclass(frozen=True)
class HookVerdict:
    status: str                 # blocked / permission / ask / defer
    reason: str                 # for measurement and debugging
    hook_failure: bool
    denies: bool


def interpret_pretooluse(stdout: str, exit_code: int, timed_out: bool = False,
                          on_failure: str = 'continue') -> HookVerdict:
    if on_failure not in ('continue', 'block'):
        raise ValueError('on_failure must be continue or block')
    if exit_code == 2:
        return HookVerdict('blocked', 'exit_2', False, True)
    failure = None
    if timed_out:
        failure = 'timeout'
    elif exit_code != 0:
        failure = f'exit_{exit_code}'
    elif not stdout.strip():
        return HookVerdict('permission', 'no_output', False, False)
    else:
        try:
            payload = json.loads(stdout)
        except (ValueError, TypeError):
            # Pure plain text from a command hook is often a non-decision,
            # whereas malformed JSON-like stdout is a parsing failure.
            if stdout.strip().startswith(('{', '[')):
                failure = 'malformed_json'
            else:
                return HookVerdict('permission', 'plain_text', False, False)
        else:
            if not isinstance(payload, dict):
                failure = 'non_object_json'
            else:
                specific = payload.get('hookSpecificOutput')
                # Top-level permissionDecision is not a PreToolUse decision.
                if specific is None:
                    return HookVerdict('permission', 'no_specific_decision', False, False)
                if not isinstance(specific, dict) or specific.get('hookEventName') != 'PreToolUse':
                    failure = 'bad_pretooluse_schema'
                else:
                    choice = specific.get('permissionDecision')
                    if choice == 'deny':
                        return HookVerdict('blocked', 'json_deny', False, True)
                    if choice == 'ask':
                        return HookVerdict('ask', 'permission_request', False, False)
                    if choice == 'defer':
                        return HookVerdict('defer', 'deferred', False, False)
                    if choice in ('allow', None):
                        return HookVerdict('permission', 'json_allow_or_no_decision', False, False)
                    failure = 'unknown_permission_decision'
    if failure is None:
        raise AssertionError('fallthrough without error')
    if on_failure == 'block':
        return HookVerdict('blocked', f'fail_closed_{failure}', True, True)
    return HookVerdict('permission', f'fail_open_{failure}', True, False)
