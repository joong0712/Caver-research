"""Read-only audit of the v0.10 real CLI batches and the extended real table (never runs the CLI)."""
import hashlib
import json
from collections import Counter, defaultdict

R = 'reports/v010/real/'
files = {'R1': R + 'R1_new_variants.json', 'R2': R + 'R2_alt_prompt.json', 'R3': R + 'R3_cli_2_1_300.json'}
docs = {k: json.load(open(v)) for k, v in files.items()}
total = 0
all_rows = []
for k, d in docs.items():
    m, rows = d['meta'], d['rows']
    total += len(rows)
    all_rows += rows
    print(f'== {k} {files[k]}')
    print('  rows:', len(rows), ' configs:', len({r["config"] for r in rows}))
    print('  meta.cli_kind:', m.get('cli_kind'), ' real_claude_code_executed:', m.get('real_claude_code_executed'))
    print('  meta.claude_version:', m.get('claude_version'), ' prompt_key:', m.get('prompt_key'),
          ' billing_mode:', m.get('billing_mode'), ' complete:', m.get('complete'))
    sa = m.get('subscription_auth') or {}
    print('  meta.subscription_auth:', {x: sa.get(x) for x in ('loggedIn', 'authMethod', 'apiKeySource') if x in sa})
    print('  meta keys:', sorted(m))
    print('  row api_key_source:', dict(Counter(r.get('api_key_source') for r in rows)))
    print('  row cli_kind:', dict(Counter(r.get('cli_kind') for r in rows)),
          ' real_executed:', dict(Counter(r.get('real_claude_code_executed') for r in rows)))
    print('  row usage_limit_hit:', dict(Counter(r.get('usage_limit_hit') for r in rows)),
          ' cli_is_error:', dict(Counter(r.get('cli_is_error') for r in rows)),
          ' cli_exit_code:', dict(Counter(r.get('cli_exit_code') for r in rows)))
    print('  row status:', dict(Counter(r.get('status') for r in rows)))
    print('  distinct cli_model values:', len({r.get('cli_model') for r in rows}))
    print('  reps:', dict(Counter(r.get('rep') for r in rows)))
    # per-config agreement across reps
    by = defaultdict(list)
    for r in rows:
        by[r['config']].append((r.get('false_pass'), r.get('contract_violated'), r.get('status')))
    multi = {c: v for c, v in by.items() if len(v) > 1}
    disagree = {c: v for c, v in multi.items() if len({x[:2] for x in v}) > 1}
    print('  configs measured >1x:', len(multi), ' disagreeing on (false_pass, contract_violated):', len(disagree),
          disagree if disagree else '')
    dstat = {c: v for c, v in multi.items() if len({x[2] for x in v}) > 1}
    print('  configs disagreeing on status label:', len(dstat))
print('TOTAL real runs across R1+R2+R3:', total)
print('all api_key_source:', dict(Counter(r.get('api_key_source') for r in all_rows)))

print('== extended table')
p = 'reports/v010/outcome_table_extended_real.json'
raw = open(p, 'rb').read()
print('  sha256:', hashlib.sha256(raw).hexdigest())
t = json.loads(raw)
m, rows = t['meta'], t['rows']
print('  meta.configs:', m.get('configs'), ' meta.rows:', m.get('rows'), ' actual rows:', len(rows),
      ' actual configs:', len({r["config"] for r in rows}))
print('  rows_per_config min:', min(Counter(r['config'] for r in rows).values()),
      ' matches meta:', dict(Counter(r['config'] for r in rows)) == m.get('rows_per_config'))
print('  new_variants:', len(m.get('new_variants', [])), ' old_configs:', len(m.get('old_configs', [])))
print('  row cli_kind:', dict(Counter(r.get('cli_kind') for r in rows)),
      ' api_key_source:', dict(Counter(r.get('api_key_source') for r in rows)))
for k in sorted(m):
    if k not in ('rows_per_config', 'new_variants', 'old_configs', 'variant_fingerprints'):
        print('  meta.' + k + ':', json.dumps(m[k], ensure_ascii=False)[:700])
# stated source hashes vs actual files
src = m.get('sources') or m.get('source_hashes') or {}
print('  source entries:', json.dumps(src)[:1500])
