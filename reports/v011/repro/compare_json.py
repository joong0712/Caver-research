"""Compare two report/summary JSON files and two runs.csv.gz files (reproduction verifier).

Usage: python3 reports/v011/repro/compare_json.py A.json B.json [A_runs.csv.gz B_runs.csv.gz]
Lists every differing leaf path (JSON) and compares the decompressed CSV bytes and rows.
Paths whose last key is in VOLATILE are reported separately (timing, paths, commit, wall clock).
"""
import csv
import gzip
import hashlib
import io
import json
import sys

VOLATILE = {'git_commit', 'wall_seconds', 'argv', 'cpu_us_per_probe', 'cpu_us_ci', 'output', 'time_utc',
            'written_utc', 'started_utc', 'finished_utc', 'pid', 'host'}


def leaves(o, path=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, path + (str(k),))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, path + (i,))
    else:
        yield path, o


def volatile(path):
    return any(isinstance(p, str) and (p in VOLATILE or p.startswith('cpu_') or 'wall' in p) for p in path)


def cmp_json(a, b):
    A = dict(leaves(json.load(open(a, encoding='utf-8'))))
    B = dict(leaves(json.load(open(b, encoding='utf-8'))))
    diffs, vol = [], []
    for k in sorted(set(A) | set(B), key=lambda p: tuple(map(str, p))):
        va, vb = A.get(k, '<missing>'), B.get(k, '<missing>')
        if va != vb:
            (vol if volatile(k) else diffs).append(('/'.join(map(str, k)), va, vb))
    return {'n_leaves_a': len(A), 'n_leaves_b': len(B), 'substantive_diffs': diffs, 'volatile_diffs': vol}


def cmp_runs(a, b):
    ra, rb = gzip.open(a).read(), gzip.open(b).read()
    out = {'gz_sha_a': hashlib.sha256(open(a, 'rb').read()).hexdigest(),
           'gz_sha_b': hashlib.sha256(open(b, 'rb').read()).hexdigest(),
           'csv_sha_a': hashlib.sha256(ra).hexdigest(), 'csv_sha_b': hashlib.sha256(rb).hexdigest(),
           'csv_bytes_identical': ra == rb}
    la = list(csv.DictReader(io.StringIO(ra.decode())))
    lb = list(csv.DictReader(io.StringIO(rb.decode())))
    out['rows_a'], out['rows_b'] = len(la), len(lb)
    if not out['csv_bytes_identical']:
        cols = [c for c in (la[0] if la else {}) if not c.startswith('cpu') and 'wall' not in c]
        out['rows_identical_excl_timing_cols'] = [{c: r.get(c) for c in cols} for r in la] == \
            [{c: r.get(c) for c in cols} for r in lb]
        out['first_row_diffs'] = [(i, {c: (x.get(c), y.get(c)) for c in x if x.get(c) != y.get(c)})
                                  for i, (x, y) in enumerate(zip(la, lb)) if x != y][:5]
    return out


if __name__ == '__main__':
    res = {'json': cmp_json(sys.argv[1], sys.argv[2])}
    if len(sys.argv) > 4:
        res['runs'] = cmp_runs(sys.argv[3], sys.argv[4])
    print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
