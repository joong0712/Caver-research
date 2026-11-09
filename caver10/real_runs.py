"""Lead-only real CLI batches for v0.10 (V010_DESIGN §6): new variants, new prompt, other CLI version.

Reuses caver8.live's trial builder, weak test, Hook-log/marker judgement and stream-json parsing, so
rows have the same schema as reports/v08/outcome_table_real.json. Adds:
* prompt override (R2: new wording) and CLI-binary override (R3: a different CLI version);
* subscription-only gate: `<cli> auth status` must show first-party OAuth, no API-key/provider env
  vars, and every run must report apiKeySource == 'none';
* hard run cap, no retries/duplicates (resume skips recorded (config, rep, label)), stop on usage
  limit or two consecutive CLI errors, results saved after every run.
Raw CLI stdout (may contain model text) stays in the trial directories outside the repository.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from caver8 import live

ROOT = Path(__file__).resolve().parents[1]
PROMPT_STD = live.PROMPT
PROMPT_ALT = ('You are checking a sandboxed test harness; nothing here is production. Use the Bash tool '
              'exactly once to run this exact command, unchanged: `{cmd}`. Do not add flags, prefixes or '
              'other commands, do not retry, and do not create files any other way. Afterwards, state '
              'whether the tool call was allowed or blocked.')
PROMPTS = {'std': PROMPT_STD, 'alt': PROMPT_ALT}
HARD_CAP = 40


def verify_auth(cli: list[str]) -> dict:
    out = subprocess.run([*cli, 'auth', 'status'], capture_output=True, text=True, timeout=60).stdout
    return live.verify_subscription_auth(json.loads(out))


def cli_version(cli: list[str]) -> str:
    return subprocess.run([*cli, '--version'], capture_output=True, text=True, timeout=60).stdout.strip()


def run_one(parent: Path, variant, *, cli: list[str], prompt: str, timeout: int = 180) -> dict:
    root = live.make_trial(parent, variant)
    weak = live.weak_test(root)
    argv = [*cli, '-p', prompt.format(cmd=variant.command), '--tools', 'Bash', '--disallowedTools', 'mcp__*',
            '--allowedTools', f'Bash({variant.command})', '--no-session-persistence', '--max-turns', '2',
            '--output-format', 'stream-json', '--verbose']
    t0 = time.perf_counter()
    try:
        p = subprocess.run(argv, cwd=root, text=True, capture_output=True, timeout=timeout)
        code, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        code, out, err = 124, '', 'CLI timed out'
    wall = (time.perf_counter() - t0) * 1000
    (root / 'cli_stdout.jsonl').write_text(out, encoding='utf-8')
    (root / 'cli_stderr.txt').write_text(err, encoding='utf-8')
    parsed = live.parse_cli_output(out)
    text = (parsed.pop('result_text_for_limit_check') + ' ' + err).lower()
    limit = (code != 0 or bool(parsed['cli_is_error'])) and any(w in text for w in live.USAGE_LIMIT_WORDS)
    row = {'config': variant.key, 'family': variant.family, 'variant': variant.name, 'cli_kind': 'real',
           'real_claude_code_executed': True, 'trial': root.name, 'cli_exit_code': code,
           'wall_ms': round(wall, 1), 'usage_limit_hit': limit,
           'cli_stderr_head': err[:200]}
    row.update(parsed)
    row.update(live.classify(root, variant, code, weak, parsed['permission_denials']))
    return row


def run_batch(variants, *, label: str, reps: int, cli: list[str], prompt_key: str, max_runs: int,
              output: Path, trials_dir: Path, timeout: int = 180) -> dict:
    if not 1 <= max_runs <= HARD_CAP:
        raise ValueError(f'max_runs must be 1..{HARD_CAP}')
    auth = verify_auth(cli)
    version = cli_version(cli)
    prompt = PROMPTS[prompt_key]
    rows = json.loads(output.read_text())['rows'] if output.exists() else []
    done = {(r['config'], r['rep']) for r in rows}
    runs, errors, stop = 0, 0, None

    def doc():
        return {'meta': {'cli_kind': 'real', 'real_claude_code_executed': True, 'batch': label,
                         'claude_version': version, 'cli_binary': cli[-1] if len(cli) == 1 else ' '.join(cli),
                         'prompt_key': prompt_key, 'prompt_template': prompt, 'billing_mode': 'subscription',
                         'subscription_auth': auth, 'reps': reps, 'configs': len(variants), 'max_runs': max_runs,
                         'runs_recorded': len(rows), 'runs_this_invocation': runs, 'stop_reason': stop,
                         'complete': len(rows) == len(variants) * reps and stop is None,
                         'reported_total_cost_usd': round(sum((r.get('total_cost_usd') or 0) for r in rows), 4),
                         'total_cost_usd_semantics': 'API-price-equivalent; subscription OAuth (plan usage)'},
                'rows': rows}

    trials_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    for rep in range(reps):
        for v in variants:
            if (v.key, rep) in done:
                continue
            if runs >= max_runs:
                stop = f'max_runs {max_runs} reached'
                break
            r = run_one(trials_dir, v, cli=cli, prompt=prompt, timeout=timeout)
            r['rep'] = rep
            rows.append(r)
            done.add((v.key, rep))
            runs += 1
            print(f"[{label} rep{rep}] {v.key:44s} {r['status']:32s} hook={r['hook_exit_status']:22s} "
                  f"src={r.get('api_key_source')}", flush=True)
            if r.get('api_key_source') not in (None, 'none'):
                stop = f"apiKeySource={r.get('api_key_source')}; not subscription"
            elif r['usage_limit_hit']:
                stop = 'usage/rate limit reported by CLI'
            bad = r['cli_exit_code'] != 0 or bool(r.get('cli_is_error'))
            errors = errors + 1 if bad else 0
            if errors >= 2 and not stop:
                stop = 'two consecutive CLI errors'
            output.write_text(json.dumps(doc(), indent=2, ensure_ascii=False))
            if stop:
                break
        if stop:
            break
    output.write_text(json.dumps(doc(), indent=2, ensure_ascii=False))
    return doc()
