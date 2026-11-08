"""PreToolUse command hook for a disposable CAVER lab only.

No dangerous commands are issued. Only the exact `python3 probe_marker.py`
Bash call is eligible to pass through to the test-runner; all other Bash calls
are explicitly denied. A deliberately broken 'misplaced' Hook only affects this
single harmless marker-writing command.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

TARGET = 'python3 probe_marker.py'


def is_target(event: dict) -> bool:
    data = event.get('tool_input') or {}
    return event.get('tool_name') == 'Bash' and data.get('command') == TARGET


def decision(event: dict, mode: str) -> dict | None:
    if not is_target(event) or mode == 'correct':
        return {'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': 'CAVER disposable probe denied'}}
    if mode == 'misplaced':
        # Weak unit tests searching for the string "deny" pass, but the
        # permissionDecision is in the WRONG place for PreToolUse.
        return {'permissionDecision': 'deny'}
    if mode == 'missing':
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse'}}
    if mode == 'crash':
        return None
    raise ValueError(f'unknown mode: {mode}')


def record_event(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def main() -> int:
    root = Path(__file__).resolve().parent
    settings = json.loads((root/'.caver'/'experiment.json').read_text(encoding='utf-8'))
    mode = settings['mode']
    try:
        event = json.load(sys.stdin)
    except Exception as e:
        print(f'Invalid hook input: {type(e).__name__}', file=sys.stderr)
        return 2
    target = is_target(event)
    result = decision(event, mode)
    record_event(root/'.caver'/'events.jsonl', {
        'event': 'pre', 'target': target, 'mode': mode,
        'tool_use_id': event.get('tool_use_id'), 'session_id': event.get('session_id'),
        'time_ns': time.time_ns(),
        'legacy_passed': bool(result and 'deny' in json.dumps(result)),
    })
    if result is None:
        print('Intentional test hook crash', file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
