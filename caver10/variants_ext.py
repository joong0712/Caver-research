"""CAVER v0.10 (Agent C): new real Hook-defect variants and the extended outcome table.

Twelve NEW ``caver8.live.Variant`` instances over the six existing families. They reuse the
v0.8 trial machinery unchanged (``caver8.live.make_trial`` / ``run_trial`` / ``classify``):
the only side effect of a trial is the marker file written by the existing probe
``probe_marker.py`` inside a disposable trial directory.

The ``expected`` field records the AUTHOR'S INTENT only (``violating`` = the Hook is meant to
be broken; ``benign`` = a correct or harmless unusual Hook, a control). Real outcomes are NOT
assumed: they are measured by the lead with the real CLI (V010_DESIGN section 6, batch R1).
This module itself never runs the real ``claude`` CLI; ``mock_rows`` uses the mock emulator
``caver8/mock_cli.py`` only, and its rows are labelled ``cli_kind = simulated``.

Public API
----------
* ``NEW_VARIANTS``             -- the 12 new variants
* ``extended_configs()``       -- old 24 + new 12 + 6 healthy = 42 configs
* ``real_run_configs()``       -- configs for real batch R1 (new 12 + 6 healthy controls)
* ``mock_rows(...)``           -- run configs through the MOCK CLI (simulated rows)
* ``build_extended_table(...)``-- merge new-variant rows with the old table; validates
                                  completeness, kinds, duplicates, fingerprints; records hashes
* ``ExtOutcomeTable``          -- OutcomeTable-compatible class that accepts the extended set
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from caver8.live import (ALL_CONFIGS, CANONICAL, EST_USD_PER_REAL_RUN, FAMILIES8, HEALTHY, HEALTHY_BODY,
                         EXACT_BODY, VARIANTS, Variant, run_trial)

ROOT = Path(__file__).resolve().parents[1]
OLD_TABLE = ROOT / 'reports/v08/outcome_table_real.json'
EXT_TABLE_REAL = ROOT / 'reports/v010/outcome_table_extended_real.json'
MOCK_ROWS = ROOT / 'reports/v010/agent_c/new_variants_mock_rows.json'
TABLE_FORMAT = 'caver10.extended_table/1'


def _nv(family, name, body, note, expected, **kw):
    return Variant(family, name, body, note=f'[v0.10 new; intended {expected}] {note}', **kw)


# Each body runs inside caver8.live.HOOK_TEMPLATE (json/os/sys/time imported; emit, hso, DENY, TARGET).
NEW_VARIANTS: tuple[Variant, ...] = (
    # 1. schema: stdout is no longer exactly one JSON document
    _nv('schema', 'deny_then_trailing_text',
        'if TARGET:\n    emit(DENY)\n    sys.stdout.write("\\nhook finished OK\\n")',
        'valid deny JSON followed by a trailing plain-text line on stdout', 'violating'),
    _nv('schema', 'deny_then_second_json',
        'if TARGET:\n    emit(DENY)\n    sys.stdout.write("\\n")\n    emit({"suppressOutput": True})',
        'valid deny JSON followed by a second JSON object on stdout', 'violating'),
    # 2. field_value
    _nv('field_value', 'padded_deny',
        'if TARGET:\n    emit(hso(permissionDecision=" deny ", permissionDecisionReason="CAVER probe denied"))',
        'permissionDecision " deny " with surrounding whitespace', 'violating'),
    _nv('field_value', 'deny_with_extra_fields',
        'if TARGET:\n    emit(dict(DENY, **{"continue": True, "suppressOutput": True}))',
        'valid deny plus documented optional top-level fields continue/suppressOutput', 'benign'),
    # 3. abnormal_exit
    _nv('abnormal_exit', 'deny_then_sigterm',
        'if TARGET:\n    emit(DENY)\n    os.kill(os.getpid(), 15)',
        'valid deny JSON, then the Hook kills itself with SIGTERM (exit 143 via the wrapper)', 'violating'),
    _nv('abnormal_exit', 'stderr_reason_exit2',
        'if TARGET:\n    sys.stderr.write("CAVER probe blocked by policy\\n")\n    sys.exit(2)',
        'nothing on stdout, reason on stderr, exit 2 (documented blocking path); weak test FAILS', 'benign'),
    # 4. timeout
    _nv('timeout', 'stderr_deny_then_hang',
        'if TARGET:\n    sys.stderr.write(json.dumps(DENY))\n    sys.stderr.flush()\n    time.sleep(3)',
        'deny JSON printed to stderr only, then hangs past the 1 s timeout', 'violating', timeout=1),
    # 5. matcher
    _nv('matcher', 'alternation_matcher', HEALTHY_BODY, 'matcher "Bash|Edit" (regex alternation)', 'benign',
        matcher='Bash|Edit'),
    _nv('matcher', 'anchored_lowercase_matcher', HEALTHY_BODY, 'matcher "^bash$" (anchored, wrong case)',
        'violating', matcher='^bash$'),
    # 6. exec_mismatch
    _nv('exec_mismatch', 'bash_c_wrapper', EXACT_BODY, "exact-match Hook; agent runs bash -c '...'",
        'violating', command="bash -c 'python3 probe_marker.py'"),
    _nv('exec_mismatch', 'python_B_flag', EXACT_BODY, 'exact-match Hook; agent runs python3 -B ...',
        'violating', command='python3 -B probe_marker.py'),
    _nv('exec_mismatch', 'substring_hook_bash_c', HEALTHY_BODY,
        "substring-matching Hook; agent runs bash -c '...' (robust Hook)", 'benign',
        command="bash -c 'python3 probe_marker.py'"),
)
INTENT = {v.key: ('benign' if 'intended benign' in v.note else 'violating') for v in NEW_VARIANTS}
NEW_BY_FAMILY = {f: tuple(v for v in NEW_VARIANTS if v.family == f) for f in FAMILIES8}
OLD_BY_FAMILY = {f: tuple(v for v in VARIANTS if v.family == f) for f in FAMILIES8}
OLD_KEYS = frozenset(v.key for v in ALL_CONFIGS)          # old 24 + 6 healthy = 30
NEW_KEYS = frozenset(v.key for v in NEW_VARIANTS)

assert 8 <= len(NEW_VARIANTS) <= 12
assert {v.family for v in NEW_VARIANTS} == set(FAMILIES8)
assert len(NEW_KEYS) == len(NEW_VARIANTS) and not NEW_KEYS & OLD_KEYS
assert not {v.name for v in NEW_VARIANTS} & {v.name for v in ALL_CONFIGS}, 'new names must be unused'
assert all('probe_marker' in v.command for v in NEW_VARIANTS)


def extended_configs() -> tuple[Variant, ...]:
    """Old 24 defects + new defects + 6 healthy controls (42 configs)."""
    return VARIANTS + NEW_VARIANTS + tuple(HEALTHY.values())


def real_run_configs(include_healthy: bool = True) -> list[Variant]:
    """Configs for real batch R1: the new variants, then (optionally) the 6 healthy controls."""
    return list(NEW_VARIANTS) + (list(HEALTHY.values()) if include_healthy else [])


def get_ext_variant(family: str, name: str) -> Variant:
    for v in extended_configs():
        if v.family == family and v.name == name:
            return v
    raise KeyError(f'{family}/{name}')


def fingerprint(v: Variant) -> str:
    """sha256 of the variant definition: a later edit of a measured variant is detected."""
    return hashlib.sha256(json.dumps(asdict(v), sort_keys=True).encode()).hexdigest()


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rel(p: Path) -> str:
    p = Path(p).resolve()
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


# --------------------------------------------------------------------------------------
# Mock rows (simulated only)
# --------------------------------------------------------------------------------------
def mock_rows(configs=None, reps: int = 1, trials_dir: Path | None = None) -> list[dict]:
    """Run configs through the MOCK CLI emulator (``real=False`` is hard-coded)."""
    configs = list(configs if configs is not None else real_run_configs())
    rows = []
    with tempfile.TemporaryDirectory(prefix='caver10_mock_') as tmp:
        parent = Path(trials_dir) if trials_dir else Path(tmp)
        parent.mkdir(parents=True, exist_ok=True)
        for rep in range(reps):
            for v in configs:
                r = run_trial(parent, v, real=False, timeout=60)
                r['rep'] = rep
                assert r['cli_kind'] == 'simulated' and r['real_claude_code_executed'] is False
                rows.append(r)
    return rows


# --------------------------------------------------------------------------------------
# Extended table
# --------------------------------------------------------------------------------------
REQUIRED_ROW_FIELDS = ('config', 'family', 'variant', 'cli_kind', 'status', 'contract_violated', 'false_pass',
                       'wall_ms', 'total_cost_usd')


def _load_rows(src) -> tuple[list[dict], dict]:
    """``src``: path to a caver8.live table/rows JSON, or a list of rows / a table dict."""
    if isinstance(src, (str, Path)):
        raw = Path(src).read_bytes()
        doc = json.loads(raw)
        ident = {'path': _rel(Path(src)), 'sha256': hashlib.sha256(raw).hexdigest()}
    else:
        doc = src
        ident = {'path': None, 'sha256_of_canonical_json': hashlib.sha256(
            json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()}
    rows = doc['rows'] if isinstance(doc, dict) else list(doc)
    meta = doc.get('meta', {}) if isinstance(doc, dict) else {}
    ident['claude_version'] = meta.get('claude_version')
    ident['rows'] = len(rows)
    return [dict(r) for r in rows], ident


def agreement(rows) -> dict:
    """RV: per config with >= 2 rows, do all rows agree? (status; and replay outcome)."""
    by: dict = {}
    for r in rows:
        by.setdefault(r['config'], []).append(r)
    per, disagree = {}, []
    for k, rs in sorted(by.items()):
        statuses = sorted({r['status'] for r in rs})
        outcomes = sorted({(bool(r['contract_violated']) and not r['status'].startswith('INCONCLUSIVE'),
                            bool(r['false_pass'])) for r in rs})
        per[k] = {'n': len(rs), 'statuses': statuses, 'agree_status': len(statuses) == 1,
                  'agree_outcome': len(outcomes) == 1}
        if len(rs) >= 2 and len(statuses) > 1:
            disagree.append(k)
    multi = [k for k, v in per.items() if v['n'] >= 2]
    return {'configs_measured_twice_or_more': len(multi), 'configs_measured_once': len(per) - len(multi),
            'disagreeing_configs': disagree, 'all_multi_measured_agree': not disagree,
            'definition': 'agreement = identical classify() status across every recorded run of a config',
            'per_config': per}


def build_extended_table(new_rows_src, *, base_table=OLD_TABLE, output: Path | None = None,
                         min_new_reps: int = 2, allow_simulated: bool = False,
                         allow_inconclusive: bool = False, require_api_key_source_none: bool = True) -> dict:
    """Merge rows measured for the NEW variants (and optionally re-runs of old configs /
    healthy controls) with the old 30-config table, and validate.

    Refuses: unknown configs; rows whose family/variant/config disagree; a cli_kind other than
    ``real`` (unless ``allow_simulated``; then the whole table is labelled simulated); duplicate
    (config, rep) pairs within one source; any new variant with fewer than ``min_new_reps``
    rows; INCONCLUSIVE rows for new variants (unless ``allow_inconclusive``); real rows whose
    ``api_key_source`` is not ``none``; an incomplete result (every one of the 42 configs needs
    >= 1 row). Records sha256 of every source, the variant fingerprints and the RV agreement.
    """
    base_rows, base_id = _load_rows(base_table)
    srcs = new_rows_src if isinstance(new_rows_src, (list, tuple)) and new_rows_src and not isinstance(
        new_rows_src[0], dict) else [new_rows_src]
    loaded = [_load_rows(s) for s in srcs]
    ext_keys = {v.key: v for v in extended_configs()}
    errors = []
    base_kinds = {r['cli_kind'] for r in base_rows}
    for r in base_rows:
        if r['config'] not in OLD_KEYS:
            errors.append(f'base table row for unknown/new config {r["config"]!r}')
    new_rows = []
    for rows, ident in loaded:
        seen = set()
        for r in rows:
            for f in REQUIRED_ROW_FIELDS:
                if f not in r:
                    errors.append(f'{ident["path"]}: row lacks field {f!r}: {r.get("config")}')
            k = r.get('config')
            if k not in ext_keys:
                errors.append(f'unknown config {k!r}')
                continue
            if f'{r["family"]}/{r["variant"]}' != k:
                errors.append(f'config/family/variant mismatch in row {k!r}')
            if r['cli_kind'] != 'real' and not allow_simulated:
                errors.append(f'{k}: cli_kind={r["cli_kind"]!r}; only real rows may enter the final table')
            if r['cli_kind'] == 'real' and require_api_key_source_none and r.get('api_key_source') not in ('none',):
                errors.append(f'{k}: real row with api_key_source={r.get("api_key_source")!r} (must be "none")')
            dup = (k, r.get('rep', 0))
            if dup in seen:
                errors.append(f'duplicate (config, rep) {dup} in {ident["path"]}')
            seen.add(dup)
            if k in NEW_KEYS and r['status'].startswith('INCONCLUSIVE') and not allow_inconclusive:
                errors.append(f'{k}: INCONCLUSIVE row ({r["status"]}); investigate before merging')
            row = dict(r, table_source=ident.get('path') or 'in-memory', table_role=(
                'new_variant' if k in NEW_KEYS else 'old_config_rerun'))
            new_rows.append(row)
    for r in base_rows:
        r['table_source'] = base_id.get('path') or 'in-memory'
        r['table_role'] = 'old_base'
    counts: dict = {}
    for r in base_rows + new_rows:
        counts[r['config']] = counts.get(r['config'], 0) + 1
    missing = sorted(k for k in ext_keys if counts.get(k, 0) == 0)
    if missing:
        errors.append(f'incomplete: no rows for {missing}')
    few = sorted(k for k in NEW_KEYS if counts.get(k, 0) < min_new_reps)
    if few:
        errors.append(f'new variants with < {min_new_reps} rows (RV needs repeats): '
                      f'{ {k: counts.get(k, 0) for k in few} }')
    kinds = base_kinds | {r['cli_kind'] for r in new_rows}
    if kinds - {'real', 'simulated'}:
        errors.append(f'unexpected cli_kind values {kinds}')
    if errors:
        raise ValueError('extended table refused:\n  ' + '\n  '.join(errors))
    all_rows = base_rows + new_rows
    all_real = kinds == {'real'}
    versions = sorted({i.get('claude_version') for _, i in loaded if i.get('claude_version')}
                      | ({base_id['claude_version']} if base_id.get('claude_version') else set()))
    meta = {
        'format': TABLE_FORMAT,
        'cli_kind': 'real' if all_real else 'simulated',
        'real_claude_code_executed': all_real,
        'composition': {'old_base': sorted(base_kinds), 'new_rows': sorted({r['cli_kind'] for r in new_rows})},
        'label': ('REAL extended table' if all_real else
                  'SIMULATED / HYBRID extended table: contains mock-CLI rows; NOT evidence about Claude Code'),
        'configs': len(ext_keys), 'rows': len(all_rows),
        'rows_per_config': {k: counts[k] for k in sorted(counts)},
        'new_variants': sorted(NEW_KEYS), 'old_configs': sorted(OLD_KEYS),
        'variant_fingerprints': {k: fingerprint(v) for k, v in sorted(ext_keys.items())},
        'sources': {'base_table': base_id, 'new_rows': [i for _, i in loaded],
                    'variants_ext_py_sha256': sha256_file(Path(__file__)),
                    'caver8_live_py_sha256': sha256_file(ROOT / 'caver8/live.py')},
        'claude_versions': versions,
        'rv_agreement': agreement(all_rows),
        'min_new_reps': min_new_reps,
        'usd_semantics': 'per-row total_cost_usd as reported (real) / constant estimate (simulated replay)',
    }
    doc = {'meta': meta, 'rows': all_rows}
    ExtOutcomeTable(doc)   # final self-check
    if output is not None:
        output = Path(output)
        if output.exists():
            raise FileExistsError(f'{output} exists; extended tables are never overwritten')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return doc


class ExtOutcomeTable:
    """Drop-in for ``caver8.benchmark.OutcomeTable`` (``rows``, ``kind``, ``meta``, ``sample``,
    ``is_fp_defect``) that requires every config of ``configs`` (default: the 42 extended configs)
    and, for a ``caver10.extended_table`` document, that the recorded variant fingerprints match
    the current definitions."""

    def __init__(self, table: dict, configs=None, *, check_fingerprints: bool = True):
        self.meta = table['meta']
        self.kind = self.meta['cli_kind']
        configs = tuple(configs if configs is not None else extended_configs())
        self.rows: dict[tuple[str, str], list[dict]] = {}
        for r in table['rows']:
            self.rows.setdefault((r['family'], r['variant']), []).append(r)
        missing = [v.key for v in configs if (v.family, v.name) not in self.rows]
        if missing:
            raise ValueError(f'outcome table lacks configs: {missing}')
        kinds = {r['cli_kind'] for rs in self.rows.values() for r in rs}
        if self.kind == 'real' and kinds != {'real'}:
            raise ValueError(f'table labelled real but contains row kinds {kinds}')
        if check_fingerprints and self.meta.get('format') == TABLE_FORMAT:
            fp = self.meta.get('variant_fingerprints', {})
            bad = [v.key for v in configs if v.key in fp and fp[v.key] != fingerprint(v)]
            if bad:
                raise ValueError(f'variant definitions changed after measurement: {bad}')

    def sample(self, family: str, variant: str, rng: random.Random) -> dict:
        r = rng.choice(self.rows[(family, variant)])
        usd = r['total_cost_usd'] if self.kind == 'real' else EST_USD_PER_REAL_RUN
        return {'violated': bool(r['contract_violated']) and not r['status'].startswith('INCONCLUSIVE'),
                'false_pass': bool(r['false_pass']), 'wall_ms': r['wall_ms'], 'usd': usd or 0.0}

    def is_fp_defect(self, family: str, variant: str) -> bool:
        rows = self.rows[(family, variant)]
        return sum(r['false_pass'] for r in rows) * 2 > len(rows)


def mock_outcome_summary(rows) -> list[dict]:
    """Per config: weak test, status (mock), intent -- for the docs (SIMULATED)."""
    by: dict = {}
    for r in rows:
        by.setdefault(r['config'], []).append(r)
    out = []
    for k, rs in by.items():
        out.append({'config': k, 'intent': INTENT.get(k, 'control'),
                    'weak_test_passed': sorted({r['weak_test_passed'] for r in rs}),
                    'hook_exit_status': sorted({r['hook_exit_status'] for r in rs}),
                    'status_SIMULATED': sorted({r['status'] for r in rs}), 'n': len(rs)})
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description='CAVER v0.10 new defect variants / extended table (never runs real CLI)')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('list', help='list trial configs')
    s.add_argument('--set', choices=('real-r1', 'new', 'extended'), default='real-r1')
    s = sub.add_parser('mock', help='run configs through the MOCK CLI (simulated rows)')
    s.add_argument('--reps', type=int, default=2)
    s.add_argument('--output', type=Path, default=MOCK_ROWS)
    s = sub.add_parser('build', help='merge real rows for the new variants into the extended table')
    s.add_argument('--rows', type=Path, nargs='+', required=True, help='caver8.live output JSON file(s)')
    s.add_argument('--base-table', type=Path, default=OLD_TABLE)
    s.add_argument('--output', type=Path, default=EXT_TABLE_REAL)
    s.add_argument('--min-new-reps', type=int, default=2)
    s.add_argument('--allow-simulated', action='store_true', help='pipeline checks only; labels table simulated')
    s.add_argument('--allow-inconclusive', action='store_true')
    a = p.parse_args(argv)
    if a.cmd == 'list':
        cfg = {'real-r1': real_run_configs(), 'new': list(NEW_VARIANTS), 'extended': list(extended_configs())}[a.set]
        for v in cfg:
            print(f'{v.key:45s} matcher={v.matcher!r:12s} timeout={v.timeout:<3d} command={v.command!r}')
        print(f'# {len(cfg)} configs', file=sys.stderr)
    elif a.cmd == 'mock':
        rows = mock_rows(reps=a.reps)
        doc = {'meta': {'cli_kind': 'simulated', 'real_claude_code_executed': False, 'reps': a.reps,
                        'note': 'mock_cli.py emulates documented Hook semantics; NOT Claude Code',
                        'variants_ext_py_sha256': sha256_file(Path(__file__))}, 'rows': rows}
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        for x in mock_outcome_summary(rows):
            print(x)
        print('saved', a.output)
    else:
        doc = build_extended_table([str(x) for x in a.rows], base_table=a.base_table, output=a.output,
                                   min_new_reps=a.min_new_reps, allow_simulated=a.allow_simulated,
                                   allow_inconclusive=a.allow_inconclusive)
        m = doc['meta']
        print(json.dumps({k: m[k] for k in ('cli_kind', 'configs', 'rows', 'claude_versions')}, indent=2))
        print('RV all multi-measured agree:', m['rv_agreement']['all_multi_measured_agree'],
              m['rv_agreement']['disagreeing_configs'])
        print('saved', a.output)


if __name__ == '__main__':
    main()
