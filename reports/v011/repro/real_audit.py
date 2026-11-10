"""Read-only audit of the v0.11 real-CLI artifacts (reproduction verifier). Never runs the CLI.

Usage: python3 reports/v011/repro/real_audit.py   -> JSON on stdout
"""
import collections
import hashlib
import json
from pathlib import Path

R1 = Path('reports/v011/real/R1_v011_variants.json')
TABLE = Path('reports/v011/outcome_table_v011_real.json')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def outcome_key(r):
    return (r.get('false_pass'), r.get('contract_violated'), r.get('status'))


def audit_r1():
    d = json.loads(R1.read_text(encoding='utf-8'))
    rows = d['rows']
    by = collections.defaultdict(list)
    for r in rows:
        by[r['config']].append(r)
    agree = {c: len({outcome_key(r) for r in rs}) == 1 for c, rs in by.items()}
    return {
        'sha256': sha(R1),
        'n_rows': len(rows),
        'api_key_source_values': dict(collections.Counter(r.get('api_key_source') for r in rows)),
        'cli_kind_values': dict(collections.Counter(r.get('cli_kind') for r in rows)),
        'usage_limit_hit_any': any(r.get('usage_limit_hit') for r in rows),
        'n_configs': len(by),
        'reps_per_config': dict(collections.Counter(len(v) for v in by.values())),
        'rep_ids_per_config_ok': all(sorted(r['rep'] for r in rs) == [0, 1] for rs in by.values()),
        'configs_agreeing': sum(agree.values()),
        'disagreeing': [c for c, a in agree.items() if not a],
        'per_config_outcome': {c: [outcome_key(r) for r in rs] for c, rs in sorted(by.items())},
        'meta': {k: d['meta'].get(k) for k in ('cli_kind', 'billing_mode', 'subscription_auth', 'reps',
                                                 'configs', 'max_runs', 'runs_recorded', 'complete',
                                                 'stop_reason')},
    }


def audit_table():
    d = json.loads(TABLE.read_text(encoding='utf-8'))
    out = {'sha256': sha(TABLE), 'top_keys': list(d)}
    meta = d.get('meta', {})
    out['meta_keys'] = list(meta)
    rows = d.get('rows') or []
    out['n_rows'] = len(rows)
    cfgs = collections.Counter(r.get('config') or f"{r.get('family')}/{r.get('variant')}" for r in rows)
    out['n_configs_from_rows'] = len(cfgs)
    out['rows_per_config_hist'] = dict(collections.Counter(cfgs.values()))
    out['cli_kind_values'] = dict(collections.Counter(r.get('cli_kind') for r in rows))
    out['api_key_source_values'] = dict(collections.Counter(r.get('api_key_source') for r in rows))
    for k in ('configs', 'outcomes', 'table'):
        if k in d and hasattr(d[k], '__len__'):
            out[f'n_{k}'] = len(d[k])
    # recorded hashes (any meta key mentioning sha / hash), checked against files on disk where a path is given
    recorded = {}

    def find(o, path=''):
        if isinstance(o, dict):
            for k, v in o.items():
                p = f'{path}.{k}' if path else k
                if isinstance(v, str) and len(v) == 64 and all(c in '0123456789abcdef' for c in v):
                    recorded[p] = v
                else:
                    find(v, p)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                find(v, f'{path}[{i}]')
    find(meta, 'meta')
    out['recorded_hashes'] = recorded
    out['meta'] = meta
    return out


if __name__ == '__main__':
    print(json.dumps({'R1': audit_r1(), 'table': audit_table()}, indent=1, default=str))
