"""Executable PreToolUse-like hook with switchable, deliberate defects.

    python -m caver5.hook_fixture < event.json

Only JSON is returned; no shell commands, network access, or protected tools run.
"""
import json
import os
import sys
import time
from .fixtures import is_forbidden


def policy_should_deny(event: dict) -> bool:
    """Tiny policy tested by the legacy unit test (not full CLI behavior)."""
    return is_forbidden(event)


def handle(event: dict) -> int:
    fault_mode = os.getenv("CAVER_FAULT_MODE", "healthy")
    trigger_families = set(filter(None, os.getenv("CAVER_TRIGGER_FAMILIES", "").split(",")))
    family = os.getenv("CAVER_PROBE_FAMILY", "canonical")
    deny = policy_should_deny(event)
    if not deny:
        return 0
    if family in trigger_families:
        if fault_mode == "wrong_schema":
            print(json.dumps({"permissionDecision": "deny"}))
            return 0
        if fault_mode == "allow_instead":
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "allow",
                "permissionDecisionReason": "legacy expects deny"}}))
            return 0
        if fault_mode == "missing_decision":
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse"},
                              "note": "deny"}))
            return 0
        if fault_mode == "nonblocking_exit":
            print("deny requested but hook crashed", file=sys.stderr)
            return 1  # documented non-blocking error, not exit 2
        if fault_mode == "malformed_json":
            print('{"hookSpecificOutput": {"permissionDecision": "deny"}')
            return 0
        if fault_mode == "timeout":
            time.sleep(1.1)
            return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "Blocked by CAVER test fixture",
    }}))
    return 0


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, TypeError):
        print("Malformed input", file=sys.stderr)
        return 2
    return handle(event)


if __name__ == "__main__":
    sys.exit(main())
