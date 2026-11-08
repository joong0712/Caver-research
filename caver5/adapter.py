"""Test Hook *subprocesses*, then audit an INERT fake tool dispatcher.

Permission granted is an explicit local experiment assumption. A real CLI may
still prompt, deny, or apply managed permission rules. No shell command from a
fixture is ever executed. This is not a production security control.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from .fixtures import Case, is_forbidden, make_event
from .hook_fixture import policy_should_deny
from .protocol import interpret_pretooluse

ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class ProbeResult:
    case_id: str
    family: str
    legacy_unit_passed: bool
    hook_exit_code: int
    timed_out: bool
    hook_stdout: str
    hook_stderr: str
    hook_verdict: str
    hook_reason: str
    tool_dispatched: bool
    oracle_violation: bool
    false_pass: bool
    elapsed_ms: float

    def to_dict(self):
        return asdict(self)


def simulated_dispatch(event: dict, log_path: Path) -> None:
    """Record an action without executing any simulated shell command."""
    with log_path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'tool_name':event['tool_name'],
                                 'tool_input':event['tool_input'],
                                 'dispatched':True}, ensure_ascii=False) + '\n')


def independent_oracle(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    for line in log_path.read_text(encoding='utf-8').splitlines():
        item = json.loads(line)
        if item.get('dispatched') and is_forbidden(item):
            return True
    return False


def probe(case: Case, family: str, timeout_s: float = 0.65,
          on_failure: str = 'continue') -> ProbeResult:
    event = make_event(family)
    legacy_unit_passed = policy_should_deny(make_event('canonical'))
    env = os.environ.copy()
    env.update({'CAVER_FAULT_MODE':case.fault_mode,
                'CAVER_TRIGGER_FAMILIES':','.join(sorted(case.triggers)),
                'CAVER_PROBE_FAMILY':family})
    start = time.perf_counter()
    try:
        process = subprocess.run([sys.executable, '-S', '-m', 'caver5.hook_fixture'],
                                 input=json.dumps(event), text=True,
                                 capture_output=True, cwd=ROOT,
                                 env=env, timeout=timeout_s)
        stdout, stderr, code, timed_out = process.stdout,process.stderr,process.returncode,False
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode('utf-8', 'replace') if isinstance(e.stdout,bytes) else (e.stdout or '')
        stderr = e.stderr.decode('utf-8', 'replace') if isinstance(e.stderr,bytes) else (e.stderr or '')
        code, timed_out = 124,True
    result = interpret_pretooluse(stdout, code, timed_out, on_failure)
    with tempfile.TemporaryDirectory(prefix='caver5-') as temporary:
        log_path = Path(temporary)/'dispatch.jsonl'
        # Locally modeled: any nonblocking decision passes permissions for a
        # disposable dummy tool. This does NOT make any claim about Claude CLI.
        dispatched = result.status == 'permission'
        if dispatched:
            simulated_dispatch(event, log_path)
        violation = independent_oracle(log_path)
    elapsed_ms=(time.perf_counter()-start)*1000
    return ProbeResult(case.id, family, legacy_unit_passed, code, timed_out,
                       stdout.strip(), stderr.strip(), result.status, result.reason,
                       dispatched, violation, legacy_unit_passed and violation,elapsed_ms)
