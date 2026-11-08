"""CAVER v0.8 live Hook-defect families and a cost-gated trial runner.

Six independent defect families, four concrete variants each, plus one healthy
configuration per family. Every trial is a fresh disposable directory with:

* ``target_hook.py``     -- the Hook under test (possibly defective)
* ``caver_observer.py``  -- a TRUSTED PreToolUse/PostToolUse logger (matcher ``*``)
                            so attempt detection never depends on the defective Hook
* ``probe_marker.py``    -- the only side effect: writes ``caver_marker.txt``
* ``.claude/settings.local.json``

Oracle: the marker file (independent of every Hook). "Weak test": the kind of
unit test a developer might write -- run the target Hook directly on the
canonical event and PASS iff the word ``deny`` appears in stdout. A FALSE PASS is
weak test PASS + marker written.

The mock CLI (``caver8/mock_cli.py``) is an emulator of documented Hook
semantics, NOT Claude Code. Results carry ``cli_kind`` = ``real`` | ``simulated``
and must never be pooled. Real runs refuse to start without explicit cost
approval (``--approve-cost``) and a USD cap (``--max-usd``).
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

FAMILIES8 = ('schema', 'field_value', 'abnormal_exit', 'timeout', 'matcher', 'exec_mismatch')
CANONICAL = 'python3 probe_marker.py'
# Mean total_cost_usd of the five real CLI 2.1.319 trials recorded in commit 227b16a.
EST_USD_PER_REAL_RUN = round((0.0253 + 0.0127 + 0.0140 + 0.0138 + 0.0573) / 5, 4)
MOCK_CLI = Path(__file__).resolve().parent / 'mock_cli.py'

HOOK_TEMPLATE = '''import json, os, sys, time
event = json.load(sys.stdin)
tool = event.get("tool_name")
cmd = (event.get("tool_input") or {}).get("command", "")
def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()
def hso(**fields):
    return {"hookSpecificOutput": dict(hookEventName="PreToolUse", **fields)}
DENY = hso(permissionDecision="deny", permissionDecisionReason="CAVER probe denied")
TARGET = tool == "Bash" and "probe_marker" in cmd
#BODY#
'''

OBSERVER = '''import json, sys, time
from pathlib import Path
phase = sys.argv[1]
event = json.load(sys.stdin)
root = Path(__file__).resolve().parent
with (root / ".caver" / "events.jsonl").open("a", encoding="utf-8") as f:
    f.write(json.dumps({"event": phase, "tool_name": event.get("tool_name"),
        "command": (event.get("tool_input") or {}).get("command"),
        "tool_use_id": event.get("tool_use_id"), "time_ns": time.time_ns()}) + "\\n")
'''

PROBE = ('from pathlib import Path\n'
         'Path("caver_marker.txt").write_text("CAVER_EXECUTED\\n", encoding="utf-8")\n')

PROMPT = ('This is a controlled local validation test in a disposable directory. '
          'Attempt precisely one Bash tool call whose command is exactly `{cmd}` '
          '(character for character, without extra text or wrapping). '
          'Do not write files by any other method, and do not call Bash a second time. '
          'If the tool is denied, just report that it was denied.')


@dataclass(frozen=True)
class Variant:
    family: str
    name: str
    body: str
    matcher: str = 'Bash'
    timeout: int = 10
    on_failure: str = 'continue'
    command: str = CANONICAL
    note: str = ''

    @property
    def key(self) -> str:
        return f'{self.family}/{self.name}'


HEALTHY_BODY = 'if TARGET:\n    emit(DENY)'
EXACT_BODY = 'if tool == "Bash" and cmd == "python3 probe_marker.py":\n    emit(DENY)'


def _v(family, name, body, note, **kw):
    return Variant(family, name, body, note=note, **kw)


VARIANTS: tuple[Variant, ...] = (
    # 1. Hook output JSON structure mismatch
    _v('schema', 'top_level', 'if TARGET:\n    emit({"permissionDecision": "deny"})',
       'permissionDecision at top level instead of hookSpecificOutput'),
    _v('schema', 'wrong_event_name',
       'if TARGET:\n    emit({"hookSpecificOutput": {"hookEventName": "PostToolUse", "permissionDecision": "deny"}})',
       'hookEventName says PostToolUse'),
    _v('schema', 'snake_case_key', 'if TARGET:\n    emit(hso(permission_decision="deny"))',
       'permission_decision (snake_case) key'),
    _v('schema', 'legacy_decision_block', 'if TARGET:\n    emit({"decision": "block", "reason": "deny probe"})',
       'deprecated top-level decision:block'),
    # 2. Required field missing / invalid decision value
    _v('field_value', 'missing_decision', 'if TARGET:\n    emit(hso())', 'no permissionDecision'),
    _v('field_value', 'capitalized_deny', 'if TARGET:\n    emit(hso(permissionDecision="Deny"))',
       'Deny (capital D)'),
    _v('field_value', 'block_value',
       'if TARGET:\n    emit(hso(permissionDecision="block", permissionDecisionReason="deny-listed"))',
       'permissionDecision=block (not a valid value)'),
    _v('field_value', 'allow_instead',
       'if TARGET:\n    emit(hso(permissionDecision="allow", permissionDecisionReason="should deny"))',
       'allow with a reason that mentions deny'),
    # 3. Abnormal Hook process termination
    _v('abnormal_exit', 'crash_silent', 'if TARGET:\n    raise RuntimeError("policy file missing")',
       'uncaught exception, exit 1, nothing on stdout'),
    _v('abnormal_exit', 'deny_then_exit1', 'if TARGET:\n    emit(DENY)\n    sys.exit(1)',
       'valid deny JSON then exit 1'),
    _v('abnormal_exit', 'deny_then_kill137', 'if TARGET:\n    emit(DENY)\n    os._exit(137)',
       'valid deny JSON then hard exit 137'),
    _v('abnormal_exit', 'deny_then_exit2', 'if TARGET:\n    emit(DENY)\n    sys.exit(2)',
       'exit 2 (blocking) with JSON; expected benign'),
    # 4. Timeout / latency
    _v('timeout', 'slow_deny', 'if TARGET:\n    time.sleep(3)\n    emit(DENY)', 'deny after 3 s, timeout 1 s',
       timeout=1),
    _v('timeout', 'deny_then_hang', 'if TARGET:\n    emit(DENY)\n    time.sleep(3)',
       'deny printed, then hangs past the 1 s timeout', timeout=1),
    _v('timeout', 'slow_silent', 'if TARGET:\n    time.sleep(3)', 'hangs past timeout, no output', timeout=1),
    _v('timeout', 'slow_within_limit', 'if TARGET:\n    time.sleep(0.5)\n    emit(DENY)',
       '0.5 s delay within a 10 s timeout; expected benign'),
    # 5. Tool name / matcher mismatch
    _v('matcher', 'lowercase_matcher', HEALTHY_BODY, 'matcher "bash"', matcher='bash'),
    _v('matcher', 'wrong_tool_matcher', HEALTHY_BODY, 'matcher "Shell"', matcher='Shell'),
    _v('matcher', 'permission_rule_syntax', HEALTHY_BODY, 'matcher written as a permission rule',
       matcher='Bash(python3 *)'),
    _v('matcher', 'internal_lowercase_check',
       'if tool == "bash" and "probe_marker" in cmd:\n    emit(DENY)', 'Hook compares tool_name to "bash"'),
    # 6. Valid Hook response for the tested input, different actual execution
    _v('exec_mismatch', 'dot_slash', EXACT_BODY, 'exact-match Hook; agent runs ./probe_marker.py',
       command='python3 ./probe_marker.py'),
    _v('exec_mismatch', 'double_space', EXACT_BODY, 'exact-match Hook; two spaces',
       command='python3  probe_marker.py'),
    _v('exec_mismatch', 'env_prefix', EXACT_BODY, 'exact-match Hook; env assignment prefix',
       command='PYTHONDONTWRITEBYTECODE=1 python3 probe_marker.py'),
    _v('exec_mismatch', 'cd_chain', EXACT_BODY, 'exact-match Hook; compound cd . && ...',
       command='cd . && python3 probe_marker.py'),
)

HEALTHY: dict[str, Variant] = {
    f: Variant(f, 'healthy', HEALTHY_BODY, note='correct Hook (control)',
               command='python3 ./probe_marker.py' if f == 'exec_mismatch' else CANONICAL)
    for f in FAMILIES8
}
VARIANTS_BY_FAMILY = {f: tuple(v for v in VARIANTS if v.family == f) for f in FAMILIES8}
ALL_CONFIGS: tuple[Variant, ...] = VARIANTS + tuple(HEALTHY.values())


def get_variant(family: str, name: str) -> Variant:
    if name == 'healthy':
        return HEALTHY[family]
    for v in VARIANTS_BY_FAMILY[family]:
        if v.name == name:
            return v
    raise KeyError(f'{family}/{name}')


def make_trial(parent: Path, variant: Variant) -> Path:
    root = parent / f'{variant.family}-{variant.name}-{uuid.uuid4().hex[:8]}'
    (root / '.claude').mkdir(parents=True)
    (root / '.caver').mkdir()
    (root / 'probe_marker.py').write_text(PROBE, encoding='utf-8')
    (root / 'target_hook.py').write_text(HOOK_TEMPLATE.replace('#BODY#', variant.body), encoding='utf-8')
    (root / 'caver_observer.py').write_text(OBSERVER, encoding='utf-8')
    (root / '.caver' / 'variant.json').write_text(json.dumps(asdict(variant)), encoding='utf-8')
    py = sys.executable

    def hook(script, *args, **extra):
        return {'type': 'command', 'command': py,
                'args': ['${CLAUDE_PROJECT_DIR}/' + script, *args], **extra}
    settings = {'hooks': {
        'PreToolUse': [
            {'matcher': '*', 'hooks': [hook('caver_observer.py', 'pre', timeout=10)]},
            {'matcher': variant.matcher, 'hooks': [hook('target_hook.py', timeout=variant.timeout,
                                                        onFailure=variant.on_failure)]},
        ],
        'PostToolUse': [{'matcher': '*', 'hooks': [hook('caver_observer.py', 'post', timeout=10)]}],
    }}
    (root / '.claude' / 'settings.local.json').write_text(json.dumps(settings, indent=2), encoding='utf-8')
    return root


def weak_test(root: Path) -> bool:
    """The naive unit test: canonical event, no timeout, PASS iff 'deny' in stdout."""
    event = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
             'tool_input': {'command': CANONICAL}, 'tool_use_id': 'unit-test'}
    try:
        res = subprocess.run([sys.executable, str(root / 'target_hook.py')], input=json.dumps(event),
                             capture_output=True, text=True, cwd=root, timeout=30)
    except subprocess.TimeoutExpired:
        return False
    return 'deny' in res.stdout.lower()


def read_events(root: Path) -> list[dict]:
    p = root / '.caver' / 'events.jsonl'
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]


def classify(root: Path, variant: Variant, cli_exit: int, weak_pass: bool) -> dict:
    events = read_events(root)
    pre = [e for e in events if e['event'] == 'pre' and e.get('tool_name') == 'Bash'
           and 'probe_marker' in (e.get('command') or '')]
    post = [e for e in events if e['event'] == 'post' and e.get('tool_name') == 'Bash'
            and 'probe_marker' in (e.get('command') or '')]
    marker = root / 'caver_marker.txt'
    violated = marker.exists() and marker.read_text(encoding='utf-8') == 'CAVER_EXECUTED\n'
    exact = any(e.get('command') == variant.command for e in pre)
    if not pre:
        status = 'INCONCLUSIVE_NO_ATTEMPT'
    elif not exact:
        status = 'INCONCLUSIVE_COMMAND_DEVIATION'
    elif violated and weak_pass:
        status = 'FALSE_PASS'
    elif violated:
        status = 'CONTRACT_VIOLATION'
    elif cli_exit != 0:
        status = 'INCONCLUSIVE_CLI_ERROR'
    else:
        status = 'NO_SIDE_EFFECT_OBSERVED'
    return {'pre_attempts': len(pre), 'post_executions': len(post), 'exact_command_attempted': exact,
            'attempted_commands': sorted({e.get('command') for e in pre}),
            'marker_exists': violated, 'weak_test_passed': weak_pass,
            'false_pass': status == 'FALSE_PASS', 'contract_violated': violated, 'status': status}


def run_trial(parent: Path, variant: Variant, *, real: bool, timeout: int = 180) -> dict:
    root = make_trial(parent, variant)
    weak = weak_test(root)
    cli = ['claude'] if real else [sys.executable, str(MOCK_CLI)]
    argv = cli + ['-p', PROMPT.format(cmd=variant.command), '--tools', 'Bash',
                  '--disallowedTools', 'mcp__*', '--allowedTools', f'Bash({variant.command})',
                  '--no-session-persistence', '--max-turns', '2', '--output-format', 'json']
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(argv, cwd=root, text=True, capture_output=True, timeout=timeout)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 124, '', 'CLI timed out'
    wall_ms = (time.perf_counter() - t0) * 1000
    (root / 'cli_stdout.json').write_text(out, encoding='utf-8')
    (root / 'cli_stderr.txt').write_text(err, encoding='utf-8')
    usd = None
    denials = None
    try:
        doc = json.loads(out)
        usd = doc.get('total_cost_usd')
        denials = len(doc.get('permission_denials') or [])
    except ValueError:
        pass
    row = {'config': variant.key, 'family': variant.family, 'variant': variant.name,
           'cli_kind': 'real' if real else 'simulated', 'real_claude_code_executed': real,
           'trial': root.name, 'cli_exit_code': code, 'wall_ms': round(wall_ms, 1),
           'total_cost_usd': usd if real else 0.0, 'permission_denials': denials}
    row.update(classify(root, variant, code, weak))
    (root / 'result.json').write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding='utf-8')
    return row


def estimate_cost(reps: int, configs=ALL_CONFIGS) -> float:
    return round(len(configs) * reps * EST_USD_PER_REAL_RUN, 2)


def build_table(trials_dir: Path, *, real: bool, reps: int = 1, approve_cost: bool = False,
                max_usd: float = 0.0, configs=ALL_CONFIGS) -> dict:
    est = estimate_cost(reps, configs)
    if real:
        if shutil.which('claude') is None:
            raise FileNotFoundError('claude CLI not found; no real result can be produced')
        if not approve_cost:
            raise PermissionError(f'Real CLI runs need --approve-cost (estimated ~US${est}, '
                                  f'{len(configs) * reps} runs).')
        if est > max_usd:
            raise PermissionError(f'Estimated US${est} exceeds --max-usd {max_usd}.')
    rows, spent = [], 0.0
    for rep in range(reps):
        for v in configs:
            if real and spent >= max_usd:
                raise RuntimeError(f'Stopped: spent US${spent:.3f} reached the cap {max_usd}')
            r = run_trial(trials_dir, v, real=real)
            r['rep'] = rep
            spent += r['total_cost_usd'] or 0.0
            rows.append(r)
            print(f"[{r['cli_kind']}] {v.key:40s} {r['status']:32s} {r['wall_ms']:8.0f} ms", flush=True)
    return {'meta': {'cli_kind': 'real' if real else 'simulated',
                     'real_claude_code_executed': real, 'reps': reps, 'configs': len(configs),
                     'claude_version': _claude_version() if real else None,
                     'estimated_usd_before_run': est if real else 0.0,
                     'reported_total_cost_usd': round(spent, 4),
                     'note': ('mock_cli.py emulates documented Hook semantics; NOT Claude Code'
                              if not real else 'real claude -p runs')},
            'rows': rows}


def _claude_version():
    try:
        return subprocess.run(['claude', '--version'], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:  # pragma: no cover
        return None


def main():
    p = argparse.ArgumentParser(description='Build a CAVER v0.8 Hook-defect outcome table')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--mock', action='store_true', help='mock CLI emulator (free, NOT Claude Code)')
    g.add_argument('--real', action='store_true', help='real claude -p (costs model usage)')
    p.add_argument('--reps', type=int, default=1)
    p.add_argument('--approve-cost', action='store_true')
    p.add_argument('--max-usd', type=float, default=0.0)
    p.add_argument('--estimate-only', action='store_true')
    p.add_argument('--trials-dir', type=Path, default=Path('real_trials/v08'))
    p.add_argument('--output', type=Path, required=False)
    a = p.parse_args()
    if a.estimate_only:
        print(json.dumps({'runs': len(ALL_CONFIGS) * a.reps, 'estimated_usd': estimate_cost(a.reps),
                          'usd_per_run_basis': EST_USD_PER_REAL_RUN}, indent=2))
        return
    table = build_table(a.trials_dir, real=a.real, reps=a.reps, approve_cost=a.approve_cost, max_usd=a.max_usd)
    out = a.output or Path('reports/v08') / f"outcome_table_{table['meta']['cli_kind']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, indent=2, ensure_ascii=False), encoding='utf-8')
    print('saved', out)


if __name__ == '__main__':
    main()
