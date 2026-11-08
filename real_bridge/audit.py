"""PostToolUse auditor. Does not claim that missing PostToolUse implies denial."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path


def main() -> int:
    event = json.load(sys.stdin)
    if event.get('tool_name') == 'Bash' and (event.get('tool_input') or {}).get('command') == 'python3 probe_marker.py':
        root = Path(__file__).resolve().parent
        path = root/'.caver'/'events.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as file:
            file.write(json.dumps({'event':'post', 'target':True,
                'tool_use_id':event.get('tool_use_id'),
                'session_id':event.get('session_id'),
                'time_ns':time.time_ns()},ensure_ascii=False)+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
