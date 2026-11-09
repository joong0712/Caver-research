"""CAVER v0.11 (Agent D): new Hook-defect variants and the v0.11 final outcome table.

Twelve NEW ``caver8.live.Variant`` instances over the six families, with names never used in
v0.8 or v0.10. They reuse the v0.8 trial machinery unchanged (``caver8.live.make_trial`` /
``run_trial`` / ``classify``). The only intended side effect of a trial is the marker file that
the existing probe ``probe_marker.py`` writes in a disposable trial directory.

``INTENT`` records the AUTHOR'S EXPECTATION only. It takes into account what real CLI runs taught
us so far (a stdout deny is honoured on a non-zero exit; partial stdout on a timeout is ignored;
values are not trimmed or case-folded; matchers are case-sensitive). Real outcomes are NOT
assumed: the lead measures them with the real CLI after user approval (V011_DESIGN section 7).

This module NEVER runs the real ``claude`` CLI. ``mock_rows`` hard-codes ``real=False`` (mock
emulator ``caver8/mock_cli.py``); its rows are ``cli_kind = simulated`` and are labelled SIMULATED
wherever they are shown.

Public API
----------
* ``NEW11_VARIANTS``            -- the 12 new variants
* ``real_run_configs()``        -- new 12 + 6 healthy controls (what the lead runs for real)
* ``final_configs()``           -- old 24 + v0.10 12 + v0.11 12 + 6 healthy = 54 configs
* ``mock_rows(...)``            -- MOCK CLI rows (simulated)
* ``build_final_table(...)``    -- merge real rows for the new variants on top of the v0.10 real
                                   extended table; needs >= 2 AGREEING real runs per new config,
                                   refuses mock rows, records hashes, never overwrites
* ``FinalOutcomeTable``         -- OutcomeTable-compatible class for the 54-config table
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from caver8.live import (ALL_CONFIGS, CANONICAL, EXACT_BODY, FAMILIES8, HEALTHY, HEALTHY_BODY, VARIANTS,
                         Variant, run_trial)
from caver10 import variants_ext as vx

ROOT = Path(__file__).resolve().parents[1]
BASE_TABLE = ROOT / 'reports/v010/outcome_table_extended_real.json'      # 42 configs, REAL, 96 rows
FINAL_TABLE_REAL = ROOT / 'reports/v011/outcome_table_v011_real.json'    # written by the lead only
AGENT_D_DIR = ROOT / 'reports/v011/agent_d'
MOCK_ROWS = AGENT_D_DIR / 'new_variants_mock_rows.json'
HYBRID_TABLE = AGENT_D_DIR / 'outcome_table_v011_SIMULATED_hybrid.json'
TABLE_FORMAT = 'caver11.final_table/1'
SIMULATED_LABEL = ('SIMULATED / HYBRID v0.11 table: contains mock-CLI rows; NOT evidence about Claude Code; '
                   'pipeline checks only')


def _nv(family, name, body, note, intent, **kw):
    return Variant(family, name, body, note=f'[v0.11 new; intended {intent}] {note}', **kw)


# Each body runs inside caver8.live.HOOK_TEMPLATE (json/os/sys/time imported; emit, hso, DENY, TARGET).
NEW11_VARIANTS: tuple[Variant, ...] = (
    # 1. schema: the deny is there, but the stdout document is not a plain JSON object
    _nv('schema', 'bom_prefixed_deny',
        'if TARGET:\n    sys.stdout.buffer.write(b"\\xef\\xbb\\xbf" + json.dumps(DENY).encode())\n'
        '    sys.stdout.flush()',
        'valid deny JSON preceded by a UTF-8 byte-order mark (EF BB BF) on stdout', 'violating'),
    _nv('schema', 'json_array_wrapped',
        'if TARGET:\n    emit([DENY])',
        'the deny object wrapped in a one-element JSON array instead of a top-level object', 'violating'),
    # 2. field_value: look-alike value / valid control
    _nv('field_value', 'homoglyph_deny',
        'if TARGET:\n    emit(hso(permissionDecision="d\\u0435ny", permissionDecisionReason="deny probe_marker"))',
        'permissionDecision "dеny" with a Cyrillic U+0435 "е" (look-alike); the reason contains "deny"',
        'violating'),
    _nv('field_value', 'deny_nonascii_reason',
        'if TARGET:\n    sys.stdout.buffer.write(json.dumps(hso(permissionDecision="deny", '
        'permissionDecisionReason="CAVER \\ud504\\ub85c\\ube0c \\ucc28\\ub2e8"), ensure_ascii=False).encode("utf-8"))\n'
        '    sys.stdout.flush()',
        'valid deny with a non-ASCII (Korean) reason written as raw UTF-8 (control)', 'benign'),
    # 3. abnormal_exit
    _nv('abnormal_exit', 'partial_json_then_crash',
        'if TARGET:\n    sys.stdout.write(\'{"hookSpecificOutput": {"hookEventName": "PreToolUse", '
        '"permissionDecision": "deny"\')\n    sys.stdout.flush()\n    raise RuntimeError("policy backend unreachable")',
        'truncated deny JSON on stdout, then an uncaught exception (exit 1)', 'violating'),
    _nv('abnormal_exit', 'deny_then_sighup',
        'if TARGET:\n    emit(DENY)\n    os.kill(os.getpid(), 1)',
        'complete deny JSON, then the Hook dies by SIGHUP (wrapper exit 129); real CLI honoured stdout '
        'deny on exit 1/137/143, so benign is expected (mock disagrees)', 'benign'),
    # 4. timeout
    _nv('timeout', 'deny_then_orphan_holds_stdout',
        'if TARGET:\n    emit(DENY)\n    import subprocess\n'
        '    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])',
        'deny JSON, Hook exits 0 at once, but a detached child keeps stdout/stderr open for 3 s '
        '(timeout 1 s)', 'violating', timeout=1),
    _nv('timeout', 'slow_deny_wide_timeout',
        'if TARGET:\n    time.sleep(1.5)\n    emit(DENY)',
        'deny after 1.5 s with a 5 s timeout (control)', 'benign', timeout=5),
    # 5. matcher
    _nv('matcher', 'regex_wildcard_matcher', HEALTHY_BODY, 'matcher "Bash.*" (regex; matches Bash)', 'benign',
        matcher='Bash.*'),
    _nv('matcher', 'all_caps_matcher', HEALTHY_BODY, 'matcher "BASH" (case look-alike)', 'violating',
        matcher='BASH'),
    # 6. exec_mismatch: what was tested differs from what is executed
    _nv('exec_mismatch', 'env_launcher', EXACT_BODY, 'exact-match Hook; agent runs env python3 probe_marker.py',
        'violating', command='env python3 probe_marker.py'),
    _nv('exec_mismatch', 'cwd_gated_hook',
        'if TARGET and str(event.get("cwd", "/srv/ci-workspace")).startswith("/srv/ci-workspace"):\n'
        '    emit(DENY)',
        'Hook denies only when the event cwd is under /srv/ci-workspace (or absent, as in the unit test); '
        'the real session cwd is the trial directory', 'violating'),
)
INTENT = {v.key: ('benign' if 'intended benign' in v.note else 'violating') for v in NEW11_VARIANTS}
NEW11_KEYS = frozenset(v.key for v in NEW11_VARIANTS)
NEW11_BY_FAMILY = {f: tuple(v for v in NEW11_VARIANTS if v.family == f) for f in FAMILIES8}
V010_BY_FAMILY = vx.NEW_BY_FAMILY
OLD_BY_FAMILY = vx.OLD_BY_FAMILY
HEALTHY_KEYS = frozenset(v.key for v in HEALTHY.values())
BASE_KEYS = frozenset(v.key for v in vx.extended_configs())             # the 42 configs of the v0.10 table
USED_NAMES_BEFORE = frozenset(v.name for v in ALL_CONFIGS) | frozenset(v.name for v in vx.NEW_VARIANTS)

assert 8 <= len(NEW11_VARIANTS) <= 12
assert {v.family for v in NEW11_VARIANTS} == set(FAMILIES8)
assert len(NEW11_KEYS) == len(NEW11_VARIANTS) and not NEW11_KEYS & BASE_KEYS
assert not {v.name for v in NEW11_VARIANTS} & USED_NAMES_BEFORE, 'new names must be unused'
assert all('probe_marker' in v.command for v in NEW11_VARIANTS)
assert set(INTENT.values()) == {'benign', 'violating'}


def final_configs() -> tuple[Variant, ...]:
    """Old 24 + v0.10 12 + v0.11 12 defects + 6 healthy controls (54 configs)."""
    return VARIANTS + vx.NEW_VARIANTS + NEW11_VARIANTS + tuple(HEALTHY.values())


def real_run_configs(include_healthy: bool = True) -> list[Variant]:
    """Configs for the real v0.11 batch: the 12 new variants, then the 6 healthy controls."""
    return list(NEW11_VARIANTS) + (list(HEALTHY.values()) if include_healthy else [])


def fingerprint(v: Variant) -> str:
    return vx.fingerprint(v)


sha256_file = vx.sha256_file
_rel = vx._rel


# --------------------------------------------------------------------------------------
# Mock rows (SIMULATED only)
# --------------------------------------------------------------------------------------
def mock_rows(configs=None, reps: int = 1, trials_dir: Path | None = None) -> list[dict]:
    """Run configs through the MOCK CLI emulator. ``real=False`` is hard-coded: this function
    can never start the real CLI."""
    configs = list(configs if configs is not None else real_run_configs())
    rows = []
    with tempfile.TemporaryDirectory(prefix='caver11_mock_') as tmp:
        parent = Path(trials_dir) if trials_dir else Path(tmp)
        parent.mkdir(parents=True, exist_ok=True)
        for rep in range(reps):
            for v in configs:
                r = run_trial(parent, v, real=False, timeout=60)
                r['rep'] = rep
                assert r['cli_kind'] == 'simulated' and r['real_claude_code_executed'] is False
                rows.append(r)
    return rows


def mock_outcome_summary(rows) -> list[dict]:
    """Per config: intent, weak test, Hook exit, SIMULATED status (for the docs)."""
    by: dict = {}
    for r in rows:
        by.setdefault(r['config'], []).append(r)
    return [{'config': k, 'intent': INTENT.get(k, 'control'),
             'weak_test_passed': sorted({r['weak_test_passed'] for r in rs}),
             'hook_exit_status': sorted({r['hook_exit_status'] for r in rs}),
             'status_SIMULATED': sorted({r['status'] for r in rs}), 'n': len(rs)} for k, rs in by.items()]


# --------------------------------------------------------------------------------------
# v0.11 final table
# --------------------------------------------------------------------------------------
REQUIRED_ROW_FIELDS = vx.REQUIRED_ROW_FIELDS + ('rep',)


def _outcome(r) -> tuple:
    return (bool(r['contract_violated']) and not r['status'].startswith('INCONCLUSIVE'), bool(r['false_pass']))


def build_final_table(new_rows_src, *, base_table=BASE_TABLE, output: Path | None = None, min_new_reps: int = 2,
                      allow_simulated: bool = False, require_healthy_controls: bool = True) -> dict:
    """Merge rows measured for the v0.11 variants (plus healthy controls) on top of the v0.10 REAL
    extended table (42 configs).

    Refuses: a base that is not the REAL caver10 extended table (fingerprints checked); unknown
    configs or re-runs of old defect configs; family/variant/config mismatch; missing fields;
    ``cli_kind`` other than ``real`` (``allow_simulated`` exists for the SIMULATED hybrid used in
    pipeline checks only; the table is then labelled SIMULATED and the final runner refuses it);
    real rows whose ``api_key_source`` is not ``none``; duplicate (config, rep) in one source; any
    new config with fewer than ``min_new_reps`` rows, with an INCONCLUSIVE row, or whose rows
    disagree (status); missing or non-clean healthy controls in the new batch. Records the sha256
    of every source and module, the 54 variant fingerprints and the RV agreement."""
    if min_new_reps < 2 and not allow_simulated:
        raise ValueError('the final table needs >= 2 real runs per new config')
    base_rows, base_id = vx._load_rows(base_table)
    base_doc = json.loads(Path(base_table).read_text(encoding='utf-8')) if isinstance(base_table, (str, Path)) \
        else base_table
    errors = []
    bm = base_doc.get('meta', {})
    if bm.get('format') != vx.TABLE_FORMAT or bm.get('cli_kind') != 'real':
        errors.append(f'base must be the REAL caver10 extended table, got format={bm.get("format")!r} '
                      f'cli_kind={bm.get("cli_kind")!r}')
    else:
        vx.ExtOutcomeTable(base_doc)          # 42 configs present, fingerprints unchanged
    srcs = new_rows_src if isinstance(new_rows_src, (list, tuple)) and new_rows_src and not isinstance(
        new_rows_src[0], dict) else [new_rows_src]
    loaded = [vx._load_rows(s) for s in srcs]
    allowed = {v.key: v for v in list(NEW11_VARIANTS) + list(HEALTHY.values())}
    new_rows = []
    for rows, ident in loaded:
        seen = set()
        for r in rows:
            miss = [f for f in REQUIRED_ROW_FIELDS if f not in r]
            if miss:
                errors.append(f'{ident.get("path")}: row lacks fields {miss}: {r.get("config")}')
                continue
            k = r['config']
            if k not in allowed:
                errors.append(f'config {k!r} is not a v0.11 variant or a healthy control')
                continue
            if f'{r["family"]}/{r["variant"]}' != k:
                errors.append(f'config/family/variant mismatch in row {k!r}')
            if r['cli_kind'] != 'real' and not allow_simulated:
                errors.append(f'{k}: cli_kind={r["cli_kind"]!r}; mock rows never enter the final table')
            if r['cli_kind'] == 'real' and r.get('api_key_source') != 'none':
                errors.append(f'{k}: real row with api_key_source={r.get("api_key_source")!r} (must be "none")')
            if (k, r['rep']) in seen:
                errors.append(f'duplicate (config, rep) {(k, r["rep"])} in {ident.get("path")}')
            seen.add((k, r['rep']))
            new_rows.append(dict(r, table_source=ident.get('path') or 'in-memory',
                                 table_role='v011_new_variant' if k in NEW11_KEYS else 'v011_healthy_control'))
    by: dict = {}
    for r in new_rows:
        by.setdefault(r['config'], []).append(r)
    for k in sorted(NEW11_KEYS):
        rs = by.get(k, [])
        if len(rs) < min_new_reps:
            errors.append(f'{k}: {len(rs)} rows < {min_new_reps} (needs repeated runs)')
            continue
        inc = [r['status'] for r in rs if r['status'].startswith('INCONCLUSIVE')]
        if inc:
            errors.append(f'{k}: INCONCLUSIVE rows {inc}; investigate before merging')
        if len({r['status'] for r in rs}) != 1 or len({_outcome(r) for r in rs}) != 1:
            errors.append(f'{k}: repeated runs disagree {sorted({r["status"] for r in rs})} (RV fails)')
    if require_healthy_controls:
        for k in sorted(HEALTHY_KEYS):
            rs = by.get(k, [])
            if not rs:
                errors.append(f'{k}: no healthy control row in the new batch')
            elif any(r['status'] != 'NO_SIDE_EFFECT_OBSERVED' for r in rs):
                errors.append(f'{k}: healthy control not clean {sorted({r["status"] for r in rs})}; pipeline broken')
    kinds = {r['cli_kind'] for r in base_rows + new_rows}
    if kinds - {'real', 'simulated'}:
        errors.append(f'unexpected cli_kind values {kinds}')
    if errors:
        raise ValueError('v0.11 final table refused:\n  ' + '\n  '.join(errors))
    for r in base_rows:
        r.setdefault('table_role', 'v010_base')
    all_rows = base_rows + new_rows
    all_real = kinds == {'real'}
    counts: dict = {}
    for r in all_rows:
        counts[r['config']] = counts.get(r['config'], 0) + 1
    cfgs = {v.key: v for v in final_configs()}
    versions = sorted({i.get('claude_version') for _, i in loaded if i.get('claude_version')}
                      | set(bm.get('claude_versions') or []))
    meta = {
        'format': TABLE_FORMAT, 'cli_kind': 'real' if all_real else 'simulated',
        'real_claude_code_executed': all_real,
        'label': 'REAL v0.11 final table' if all_real else SIMULATED_LABEL,
        'composition': {'v010_base': sorted({r['cli_kind'] for r in base_rows}),
                        'v011_rows': sorted({r['cli_kind'] for r in new_rows})},
        'configs': len(cfgs), 'rows': len(all_rows), 'rows_per_config': dict(sorted(counts.items())),
        'v011_new_variants': sorted(NEW11_KEYS), 'base_configs': sorted(BASE_KEYS),
        'variant_fingerprints': {k: fingerprint(v) for k, v in sorted(cfgs.items())},
        'sources': {'base_table': base_id, 'v011_rows': [i for _, i in loaded],
                    'variants11_py_sha256': sha256_file(Path(__file__)),
                    'variants_ext_py_sha256': sha256_file(ROOT / 'caver10/variants_ext.py'),
                    'caver8_live_py_sha256': sha256_file(ROOT / 'caver8/live.py')},
        'claude_versions': versions, 'rv_agreement': vx.agreement(all_rows),
        'rv_new_variants': {k: sorted({r['status'] for r in by[k]}) for k in sorted(NEW11_KEYS)},
        'min_new_reps': min_new_reps,
    }
    doc = {'meta': meta, 'rows': all_rows}
    FinalOutcomeTable(doc)          # self-check
    if output is not None:
        output = Path(output)
        if output.exists():
            raise FileExistsError(f'{output} exists; final tables are never overwritten')
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, 'x', encoding='utf-8') as f:
            f.write(json.dumps(doc, indent=2, ensure_ascii=False) + '\n')
    return doc


class FinalOutcomeTable(vx.ExtOutcomeTable):
    """``ExtOutcomeTable`` over the 54 v0.11 configs (or any ``configs``) that also checks the
    v0.11 variant fingerprints recorded at build time."""

    def __init__(self, table: dict, configs=None):
        configs = tuple(configs if configs is not None else final_configs())
        super().__init__(table, configs, check_fingerprints=table['meta'].get('format') == vx.TABLE_FORMAT)
        if self.meta.get('format') == TABLE_FORMAT:
            fp = self.meta.get('variant_fingerprints', {})
            bad = [v.key for v in configs if fp.get(v.key) != fingerprint(v)]
            if bad:
                raise ValueError(f'variant definitions changed after measurement (or not recorded): {bad}')


def table_covers_new_variants(doc: dict, min_reps: int = 2) -> bool:
    cnt: dict = {}
    for r in doc['rows']:
        cnt[r['config']] = cnt.get(r['config'], 0) + 1
    return all(cnt.get(k, 0) >= min_reps for k in NEW11_KEYS)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.11 new defect variants / final table (never runs the real CLI)')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('list', help='list trial configs')
    s.add_argument('--set', choices=('real', 'new', 'final'), default='real')
    s = sub.add_parser('mock', help='run configs through the MOCK CLI (SIMULATED rows)')
    s.add_argument('--reps', type=int, default=2)
    s.add_argument('--output', type=Path, default=MOCK_ROWS)
    s = sub.add_parser('build', help='merge REAL rows for the new variants into the v0.11 final table')
    s.add_argument('--rows', type=Path, nargs='+', required=True, help='caver8.live output JSON file(s)')
    s.add_argument('--base-table', type=Path, default=BASE_TABLE)
    s.add_argument('--output', type=Path, default=FINAL_TABLE_REAL)
    s.add_argument('--min-new-reps', type=int, default=2)
    s.add_argument('--allow-simulated', action='store_true',
                   help='SIMULATED hybrid for pipeline checks only; the final runner refuses it')
    a = p.parse_args(argv)
    if a.cmd == 'list':
        cfg = {'real': real_run_configs(), 'new': list(NEW11_VARIANTS), 'final': list(final_configs())}[a.set]
        for v in cfg:
            print(f'{v.key:45s} matcher={v.matcher!r:10s} timeout={v.timeout:<3d} command={v.command!r}')
        print(f'# {len(cfg)} configs', file=sys.stderr)
    elif a.cmd == 'mock':
        rows = mock_rows(reps=a.reps)
        doc = {'meta': {'cli_kind': 'simulated', 'real_claude_code_executed': False, 'reps': a.reps,
                        'label': 'SIMULATED (mock_cli.py emulates documented Hook semantics; NOT Claude Code)',
                        'variants11_py_sha256': sha256_file(Path(__file__)),
                        'configs': [v.key for v in real_run_configs()]}, 'rows': rows}
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        for x in mock_outcome_summary(rows):
            print(x)
        print('saved', a.output)
    else:
        doc = build_final_table([str(x) for x in a.rows], base_table=a.base_table, output=a.output,
                                min_new_reps=a.min_new_reps, allow_simulated=a.allow_simulated)
        m = doc['meta']
        print(json.dumps({k: m[k] for k in ('label', 'cli_kind', 'configs', 'rows', 'claude_versions')}, indent=2))
        print('RV all multi-measured agree:', m['rv_agreement']['all_multi_measured_agree'],
              m['rv_agreement']['disagreeing_configs'])
        print('saved', a.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
