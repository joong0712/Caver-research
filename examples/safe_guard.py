"""Opt-in safe demonstration PreToolUse hook; never executes a tool.

For experiments in a disposable Claude project only. This demonstration denies
one exact inert Bash echo command, does not implement real policy security.
"""
import json
import sys


def main():
    try:
        event = json.load(sys.stdin)
        tool = event.get('tool_name', '')
        argument = event.get('tool_input', {})
        command = argument.get('command', '') if isinstance(argument, dict) else ''
        if tool == 'Bash' and command.strip() == 'echo CAVER_RESEARCH_SENTINEL':
            print(json.dumps({'hookSpecificOutput':{
                'hookEventName':'PreToolUse',
                'permissionDecision':'deny',
                'permissionDecisionReason':'CAVER research sentinel: intentionally denied'}}))
        return 0
    except (ValueError, TypeError, AttributeError) as exc:
        print(f'Invalid input: {exc}',file=sys.stderr)
        return 2  # fail-closed on invalid input

if __name__=='__main__': sys.exit(main())
