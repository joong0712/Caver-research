"""Freeze manifest for the confirmation study: hashes of the candidate, the harness and the data.

The final holdout runner refuses to run if any hash differs from the committed manifest, so the
candidate cannot change between pre-registration and the final evaluation.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'reports/v09c/freeze_manifest.json'
CANDIDATE = 'caver9.exploration:UCBMeanCAVER'
FROZEN_FILES = (
    'caver9/exploration.py',      # candidate C2 (and its base class ExploreCAVER)
    'caver9/evaluation.py',       # audited single-run machinery reused by the study
    'caver8/benchmark.py',        # case generator, OutcomeTable, legacy schedules
    'caver5/policies.py', 'caver5/advanced_policies.py', 'caver6/policies.py', 'caver6/confirmation.py',
    'reports/v08/outcome_table_real.json',          # primary real outcome table (30 runs)
    'reports/v09/outcome_table_real_2reps.json',    # secondary real outcome table (60 runs)
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_constants() -> dict:
    sys.path.insert(0, str(ROOT))
    from caver9.exploration import UCBMeanCAVER as C
    return {'name': C.name, 'C': C.C, 'SENTINEL': C.SENTINEL, 'epsilon': 0.0,
            'detector': 'caver6.confirmation.ConfirmedFamilyDetector', 'reset': 'local'}


def compute() -> dict:
    return {'candidate': CANDIDATE, 'constants': candidate_constants(),
            'files': {f: sha256(ROOT / f) for f in FROZEN_FILES}}


def verify(manifest_path: Path = MANIFEST) -> dict:
    committed = json.loads(manifest_path.read_text())
    now = compute()
    bad = {f: (committed['files'].get(f), h) for f, h in now['files'].items() if committed['files'].get(f) != h}
    if bad or committed['constants'] != now['constants'] or committed['candidate'] != now['candidate']:
        raise RuntimeError(f'freeze manifest mismatch -- candidate/harness/data changed after pre-registration: {bad}')
    return committed


if __name__ == '__main__':
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    if MANIFEST.exists() and '--write' not in sys.argv:
        print(json.dumps(verify(), indent=2)); print('manifest OK')
    else:
        MANIFEST.write_text(json.dumps(compute(), indent=2) + '\n'); print('written', MANIFEST)
