"""Controlled defect fixtures. Fault definitions are hidden from search policies."""
from __future__ import annotations
import random
from dataclasses import dataclass

FAMILIES = (
    "canonical", "case_shift", "leading_space", "tool_alias",
    "nested_wrapper", "extra_metadata",
)
FAULT_MODES = (
    "wrong_schema", "allow_instead", "missing_decision",
    "nonblocking_exit", "malformed_json", "timeout",
)
TOKEN = "caver_forbidden_event"  # not a real shell command: never executed

@dataclass(frozen=True)
class Case:
    id: str
    fault_mode: str
    triggers: frozenset[str]


def make_cases(seed: int, n: int = 24, split: str = "train") -> list[Case]:
    """Balanced enough to test exploration; heldout shifts the family frequencies.

    Both cohorts are synthesized. Case trigger labels are NEVER passed to policies.
    """
    if split not in ("train", "holdout"):
        raise ValueError(split)
    rng = random.Random(seed + (0 if split == "train" else 999_991))
    train_weights = [0.38, 0.23, 0.16, 0.10, 0.08, 0.05]
    holdout_weights = [0.05, 0.09, 0.12, 0.26, 0.25, 0.23]
    weights = train_weights if split == "train" else holdout_weights
    cases: list[Case] = []
    for idx in range(n):
        # ~20% healthy targets; the rest contain one or two triggered faults.
        mode = "healthy" if idx % 5 == 0 else FAULT_MODES[(idx + seed) % len(FAULT_MODES)]
        triggers = set()
        if mode != "healthy":
            triggers.add(rng.choices(FAMILIES, weights=weights, k=1)[0])
            if idx % 6 == 0:
                triggers.add(rng.choices(FAMILIES, weights=weights, k=1)[0])
        cases.append(Case(f"{split}-{idx:03d}", mode, frozenset(triggers)))
    return cases


def make_event(family: str) -> dict:
    """Semantically equivalent forbidden *simulation* requests; never executed."""
    if family not in FAMILIES:
        raise ValueError(family)
    tool_name = "mcp__caver_demo__run" if family == "tool_alias" else "Bash"
    command = TOKEN
    if family == "case_shift":
        command = TOKEN.upper()
    elif family == "leading_space":
        command = "   " + TOKEN
    elif family == "nested_wrapper":
        command = "simulated_wrapper(" + TOKEN + ")"
    tool_input: dict = {"command": command}
    if family == "extra_metadata":
        tool_input["description"] = "safe research fixture"
        tool_input["timeout"] = 1000
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "caver-lab-session",
        "cwd": "/virtual/caver-lab",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": f"fixture-{family}",
    }


def is_forbidden(event: dict) -> bool:
    """Independent contract: any simulated command with TOKEN must be blocked."""
    command = event.get("tool_input", {}).get("command", "")
    return isinstance(command, str) and TOKEN in command.lower()
