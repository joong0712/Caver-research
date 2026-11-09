"""CAVER v0.11 Agent C: unique-defect-focused selection, and an audit of de-duplication.

Two independent parts. Policies never import or call the audit part.

1. **Candidate policies** (constants pre-declared in ``docs/V011_AGENT_C.md`` before any dev run).
   They follow the shared interface: ``select(case_id) -> arm``, ``update(case_id, arm, violated,
   newly_found, learn)``, optional ``begin_evaluation()``. They see only the opaque case id (used as
   a dictionary key, never parsed), the arm and the two booleans. They respect ``available()``.

   * ``PopBayesUCB`` (C-A): per-arm Beta posterior of the new-FALSE_PASS rate, estimated from the
     probes made on the **currently active case population** (the distinct case ids seen in the last
     ``W_POP`` probes, with their whole probe history), shrunk towards the all-time per-arm rate with
     ``LAMBDA`` pseudo-observations. Bayes-UCB score: mean + ``KAPPA`` x posterior sd.
   * ``PopDivBUCB`` (C-B): C-A plus a diversity choice among near-optimal arms (score within
     ``DELTA`` of the best): pick the arm with the largest expected gain in Shannon entropy of the
     per-arm counts of FALSE_PASS findings in the current phase (q-gram-ART-inspired, q = 1).
   * ``C2Div`` (C-C): C2 (``caver9.exploration.UCBMeanCAVER``) unchanged, plus the same diversity
     choice among arms within ``DELTA`` of C2's best score.

   Prior art, no novelty claim: Bayes-UCB (Kaufmann, Cappe, Garivier 2012), empirical-Bayes
   shrinkage, entropy-maximising candidate selection (Biagiola, Feldt, Tonella 2025, q-gram ART).
   The mapping and the deviations are documented in ``docs/V011_AGENT_C.md``.

2. **Evaluation-side audit** (``audit_*`` functions). It re-implements the probe loop of
   ``caver11.devkit.run_one_ext`` independently (own outcome lookup from the raw table JSON, own
   opaque ids, own exhaustion check) and records a per-probe trace **including hidden variants**, to
   recompute ``unique_false_pass``, ``unique_variant_false_pass`` and ``duplicate_rate`` and to add
   variant-level duplicate metrics. It also recomputes summary statistics from ``runs.csv.gz``.
   This code reads hidden case defects; it is used only to measure, never by a policy.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import random
from collections import deque
from pathlib import Path
from statistics import mean, stdev

from caver5.fixtures import FAMILIES
from caver5.policies import BasePolicy
from caver9.exploration import UCBMeanCAVER

# ============================================================================================
# Part 1: candidate policies (see docs/V011_AGENT_C.md for every constant)
# ============================================================================================


def _entropy(counts) -> float:
    tot = sum(counts)
    return -sum((c / tot) * math.log(c / tot) for c in counts if c > 0)


class _DiversityMixin:
    """Entropy-gain choice among near-optimal arms (shared by C-B and C-C).

    ``found[f]``: number of new FALSE_PASS findings on arm f in the current phase (reset by
    ``begin_evaluation``). The expected gain of arm f is ``p_f * (H(found + s + e_f) - H(found + s))``,
    with ``s = DIV_SMOOTH`` added to every arm, where p_f is the arm's estimated new-FALSE_PASS rate.
    """
    DELTA = 0.05
    DIV_SMOOTH = 0.5

    def _div_init(self):
        self.found = {f: 0 for f in FAMILIES}
        self.div_choices = 0          # diagnostics: picks that differ from the plain argmax

    def _div_reset(self):
        self.found = {f: 0 for f in FAMILIES}

    def _div_count(self, arm, newly_found):
        if newly_found:
            self.found[arm] += 1

    def entropy_gain(self, f) -> float:
        base = [self.found[g] + self.DIV_SMOOTH for g in FAMILIES]
        plus = [self.found[g] + self.DIV_SMOOTH + (1.0 if g == f else 0.0) for g in FAMILIES]
        return _entropy(plus) - _entropy(base)

    def _div_pick(self, order, scores, rates):
        """order: shuffled available arms; scores/rates: dicts. Returns the chosen arm."""
        best = max(order, key=lambda f: scores[f])
        top = scores[best]
        if math.isinf(top):
            near = [f for f in order if math.isinf(scores[f])]
        else:
            near = [f for f in order if scores[f] >= top - self.DELTA]
        pick = max(near, key=lambda f: (rates[f] * self.entropy_gain(f), scores[f]))
        self.div_choices += int(pick != best)
        return pick


class PopBayesUCB(BasePolicy):
    """C-A: population-matched novelty posterior with Bayes-UCB selection."""
    name = 'C11C-PopBUCB'
    W_POP = 20            # active population: distinct case ids seen in the last W_POP learned probes
    LAMBDA = 4.0          # pseudo-observations of the all-time per-arm prior
    KAPPA = 1.0           # Bayes-UCB width (posterior sd multiplier)
    PRIOR_A = 1.0         # Beta(1, 1) for the all-time per-arm rate
    PRIOR_B = 1.0

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self.t = 0
        self.recent = deque(maxlen=self.W_POP)     # case ids of the last W_POP learned probes
        self.case_obs: dict[str, dict[str, int]] = {}  # case id -> {arm: newly_found of first probe}
        self.n_all = {f: 0 for f in FAMILIES}
        self.s_all = {f: 0 for f in FAMILIES}
        self.in_eval = False

    # ----- interface ------------------------------------------------------------------------
    def begin_evaluation(self):
        self.in_eval = True

    def select(self, case_id: str) -> str:
        avail = self.available(case_id)
        stats = self.posterior(case_id)
        scores = {f: self.score_from(*stats[f]) for f in avail}
        order = list(avail)
        self.rng.shuffle(order)
        return self.choose(order, scores, {f: stats[f][0] for f in avail})

    def update(self, case_id, arm, violated, newly_found, learn=True):
        BasePolicy.update(self, case_id, arm, violated, newly_found, learn)
        if not learn:
            return
        self.t += 1
        self.recent.append(case_id)
        obs = self.case_obs.setdefault(case_id, {})
        if arm not in obs:                  # first probe of (case, arm) only; repeats are duplicates
            obs[arm] = int(bool(newly_found))
            self.n_all[arm] += 1
            self.s_all[arm] += int(bool(newly_found))

    # ----- estimator ------------------------------------------------------------------------
    def active_cases(self, case_id=None) -> list:
        ids = dict.fromkeys(self.recent)            # insertion order: deterministic
        if case_id is not None:
            ids.setdefault(case_id, None)
        return list(ids)

    def posterior(self, case_id=None) -> dict:
        """{arm: (mean, sd)} of the shrunk Beta posterior on the active population."""
        n = {f: 0 for f in FAMILIES}
        s = {f: 0 for f in FAMILIES}
        for c in self.active_cases(case_id):
            for f, r in self.case_obs.get(c, {}).items():
                n[f] += 1
                s[f] += r
        out = {}
        for f in FAMILIES:
            g = (self.s_all[f] + self.PRIOR_A) / (self.n_all[f] + self.PRIOR_A + self.PRIOR_B)
            a = s[f] + self.LAMBDA * g
            b = (n[f] - s[f]) + self.LAMBDA * (1.0 - g)
            m = a / (a + b)
            sd = math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1.0)))
            out[f] = (m, sd)
        return out

    def score_from(self, m, sd) -> float:
        return m + self.KAPPA * sd

    def choose(self, order, scores, rates):
        return max(order, key=lambda f: scores[f])


class PopDivBUCB(_DiversityMixin, PopBayesUCB):
    """C-B: C-A plus the entropy-gain choice among arms within DELTA of the best score."""
    name = 'C11C-PopBUCB-Div'

    def __init__(self, rng):
        super().__init__(rng)
        self._div_init()

    def begin_evaluation(self):
        super().begin_evaluation()
        self._div_reset()

    def update(self, case_id, arm, violated, newly_found, learn=True):
        super().update(case_id, arm, violated, newly_found, learn)
        if learn:
            self._div_count(arm, newly_found)

    def choose(self, order, scores, rates):
        return self._div_pick(order, scores, rates)


class C2Div(_DiversityMixin, UCBMeanCAVER):
    """C-C: C2 (UCBMeanCAVER, c = 0.5, confirmed detector, local reset) unchanged, plus the
    entropy-gain choice among arms within DELTA of C2's best score. RNG call order equals C2's."""
    name = 'C11C-C2-Div'

    def __init__(self, rng):
        super().__init__(rng)
        self._div_init()

    def begin_evaluation(self):
        super().begin_evaluation()
        self._div_reset()

    def select(self, case_id):
        avail = self.available(case_id)
        self.eval_steps += int(self.detector.in_evaluation)   # as ExploreCAVER (no sentinel, eps 0)
        order = list(avail)
        self.rng.shuffle(order)
        self.last_source = 'score'
        scores = {f: self.score(f) for f in avail}
        rates = {f: self.posterior_mean(f) for f in avail}
        return self._div_pick(order, scores, rates)

    def update(self, case_id, arm, violated, newly_found, learn=True):
        super().update(case_id, arm, violated, newly_found, learn)
        if learn:
            self._div_count(arm, newly_found)


CANDIDATES = (PopBayesUCB, PopDivBUCB, C2Div)


# ============================================================================================
# Part 2: evaluation-side audit (reads hidden variants; never used by any policy)
# ============================================================================================
AUDIT_FAMILIES = ('schema', 'field_value', 'abnormal_exit', 'timeout', 'matcher', 'exec_mismatch')


class AuditTable:
    """Minimal independent outcome lookup from the raw table JSON (rows grouped in file order)."""

    def __init__(self, doc: dict):
        self.rows: dict = {}
        for r in doc['rows']:
            self.rows.setdefault((r['family'], r['variant']), []).append(r)

    @classmethod
    def load(cls, path) -> 'AuditTable':
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    def outcome(self, fam, variant, crn_key) -> tuple[bool, bool]:
        rows = self.rows[(fam, variant)]
        r = rows[0] if len(rows) == 1 else random.Random(crn_key).choice(rows)
        violated = bool(r['contract_violated']) and not str(r['status']).startswith('INCONCLUSIVE')
        return violated, bool(r['false_pass'])

    def fp_config(self, fam, variant) -> bool:
        rows = self.rows[(fam, variant)]
        return 2 * sum(bool(r['false_pass']) for r in rows) > len(rows)


def audit_trace(cls, salt, seed, train, hold, table: AuditTable) -> list[dict]:
    """Independent probe loop. Returns one dict per eval probe with hidden fields
    (case, family, variant, violated, false_pass, new_case_family). Train probes are run (the
    policy learns) but not returned."""
    arms = list(FAMILIES)
    arm_fam = dict(zip(arms, AUDIT_FAMILIES))
    policy = cls(random.Random(f'{salt}:{seed}:policy'))
    observe = getattr(policy, 'observe_outcome', None)
    alias, probed, occ = {}, {}, {}
    trace = []

    def one(case, phase, seen):
        cid = alias.get(case.id)
        if cid is None:
            cid = alias[case.id] = 'c%03d' % len(alias)
        left = [a for a in arms if a not in probed.get(cid, set())] or arms
        arm = policy.select(cid)
        if arm not in left:
            raise AssertionError('exhaustion rule broken')
        probed.setdefault(cid, set()).add(arm)
        fam = arm_fam[arm]
        variant = 'healthy'
        for f, v in case.defects:
            if f == fam:
                variant = v
        k = occ[(phase, case.id, fam)] = occ.get((phase, case.id, fam), 0) + 1
        violated, fp = table.outcome(fam, variant, f'{salt}:{seed}:outcome9:{phase}:{case.id}:{fam}:{k}')
        new = violated and (case.id, fam) not in seen
        if new:
            seen[(case.id, fam)] = fp
        if callable(observe):
            observe(false_pass=fp, violated=violated, new_defect=new)
        policy.update(cid, arm, violated, bool(new and fp), learn=True)
        return {'case': case.id, 'family': fam, 'variant': variant, 'violated': violated,
                'false_pass': fp, 'new': bool(new)}

    seen: dict = {}
    for c in train:
        one(c, 'train', seen)
    if callable(getattr(policy, 'begin_evaluation', None)):
        policy.begin_evaluation()
    seen = {}
    for step, c in enumerate(hold, 1):
        row = one(c, 'eval', seen)
        row['step'] = step
        trace.append(row)
    return trace


def audit_metrics(trace: list[dict], hold, table: AuditTable) -> dict:
    """Metrics recomputed from an eval trace, independently of devkit.

    * unique_false_pass: distinct (case, family) whose FIRST violation in eval was a FALSE_PASS;
    * unique_variant_false_pass: distinct (family, variant) among those;
    * duplicate_rate (devkit definition): violating probes on an already-found (case, family) /
      violating probes (0.0 when there is no violating probe);
    * variant_duplicate_rate: violating probes whose (family, variant) had already been found as a
      violation earlier in eval / violating probes (None when there is none);
    * fp_variant_duplicate_share: share of new (case, family) FALSE_PASS findings whose (family,
      variant) was already found earlier in eval (None when there is none);
    * available_variant_false_pass: distinct FALSE_PASS (family, variant) configs in the hold cases.
    """
    first = {}
    viol = dup = vdup = 0
    found_viol_var = set()
    fp_var, fp_new, fp_new_dup = set(), 0, 0
    for r in trace:
        key = (r['case'], r['family'])
        var = (r['family'], r['variant'])
        if r['violated']:
            viol += 1
            if key in first:
                dup += 1
            else:
                first[key] = r['false_pass']
                if r['false_pass']:
                    fp_new += 1
                    fp_new_dup += int(var in fp_var)
                    fp_var.add(var)
            vdup += int(var in found_viol_var)
            found_viol_var.add(var)
    cases = {c.id: c for c in hold}
    avail_var = {(f, v) for c in cases.values() for f, v in c.defects if table.fp_config(f, v)}
    return {'unique_false_pass': sum(first.values()), 'unique_variant_false_pass': len(fp_var),
            'duplicate_rate': round(dup / viol, 4) if viol else 0.0,
            'variant_duplicate_rate': round(vdup / viol, 4) if viol else None,
            'fp_variant_duplicate_share': round(fp_new_dup / fp_new, 4) if fp_new else None,
            'available_variant_false_pass': len(avail_var), 'violating_probes': viol}


def _ci(d):
    d = [x for x in d if x is not None]
    if len(d) < 2:
        return (round(mean(d), 4) if d else None), None
    m = mean(d)
    h = 1.96 * stdev(d) / len(d) ** 0.5
    return round(m, 4), [round(m - h, 4), round(m + h, 4)]


def read_runs(path) -> list[dict]:
    num = ('seed', 'unique_false_pass', 'unique_variant_false_pass', 'unique_defects')
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in num:
            r[k] = int(r[k])
        r['duplicate_rate'] = float(r['duplicate_rate'])
    return rows


def recompute_from_runs(rows: list[dict], refs=('CAVER-v0.6', 'C9-UCBMean')) -> dict:
    """Per-scenario means, paired CIs vs refs, and pooled per-seed mean differences, recomputed
    from runs.csv.gz rows (independent of devkit.evaluate)."""
    by = {}
    for r in rows:
        by.setdefault((r['scenario'], r['policy']), {})[r['seed']] = r
    scen = list(dict.fromkeys(r['scenario'] for r in rows))
    pols = list(dict.fromkeys(r['policy'] for r in rows))
    seeds = sorted({r['seed'] for r in rows})
    out = {'scenario': {}, 'pooled': {}}
    for sc in scen:
        out['scenario'][sc] = {}
        for p in pols:
            m = {}
            for k in ('unique_false_pass', 'unique_variant_false_pass', 'duplicate_rate'):
                m[k] = _ci([by[(sc, p)][s][k] for s in seeds])[0]
                for ref in refs:
                    if ref != p and (sc, ref) in by:
                        m[f'diff_{k}_vs_{ref}'] = _ci([by[(sc, p)][s][k] - by[(sc, ref)][s][k] for s in seeds])
            out['scenario'][sc][p] = m
    for p in pols:
        out['pooled'][p] = {}
        for ref in refs:
            if ref == p:
                continue
            for k in ('unique_false_pass', 'unique_variant_false_pass'):
                out['pooled'][p][f'diff_{k}_vs_{ref}'] = _ci(
                    [mean(by[(sc, p)][s][k] - by[(sc, ref)][s][k] for sc in scen) for s in seeds])
    return out


def kendall_tau(a: list, b: list) -> float:
    """Kendall tau-a between two rankings given as ordered lists of the same items."""
    pa = {x: i for i, x in enumerate(a)}
    pb = {x: i for i, x in enumerate(b)}
    items = list(a)
    conc = disc = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            s = (pa[items[i]] - pa[items[j]]) * (pb[items[i]] - pb[items[j]])
            conc += s > 0
            disc += s < 0
    n = len(items) * (len(items) - 1) / 2
    return round((conc - disc) / n, 4)


def ranking_audit(summary: dict, policies: list, scenarios: list) -> dict:
    """Policy rankings by case-level vs variant-level unique FALSE_PASS (means from summary)."""
    out = {}
    for sc in scenarios:
        case = sorted(policies, key=lambda p: -summary[sc][p]['unique_false_pass'])
        var = sorted(policies, key=lambda p: -summary[sc][p]['unique_variant_false_pass'])
        out[sc] = {'case_rank': case, 'variant_rank': var, 'kendall_tau': kendall_tau(case, var),
                   'top_case': case[0], 'top_variant': var[0]}
    return out


def _audit_task(t):
    spec_list, seed, sc, table_path = t
    from caver9 import evaluation as ev
    from caver11 import devkit as dk
    table = AuditTable.load(table_path)
    train, hold, _ = dk.build_schedule(dk.DEV_SALT, seed, sc)
    out = []
    for spec in spec_list:
        cls = ev.resolve_policy(spec)
        m = audit_metrics(audit_trace(cls, dk.DEV_SALT, seed, train, hold, table), hold, table)
        out.append({'scenario': sc, 'seed': seed, 'policy': cls.name, **m})
    return out


def run_audit(dev_dir: Path, out_path: Path, seeds=range(300), jobs: int = 2) -> dict:
    """Full audit against a devkit output directory (summary.json + runs.csv.gz)."""
    from concurrent.futures import ProcessPoolExecutor
    from caver11 import devkit as dk
    dev_dir = Path(dev_dir)
    summ = json.loads((dev_dir / 'summary.json').read_text(encoding='utf-8'))
    specs, names = summ['meta']['specs'], summ['meta']['policies']
    scen = summ['meta']['scenarios']
    rows = read_runs(dev_dir / 'runs.csv.gz')
    # (1) recompute summary statistics from runs.csv.gz and compare to summary.json
    rec = recompute_from_runs(rows)
    mism = []
    for sc in scen:
        for p in names:
            for k in ('unique_false_pass', 'unique_variant_false_pass', 'duplicate_rate'):
                if rec['scenario'][sc][p][k] != summ['summary'][sc][p][k]:
                    mism.append(('mean', sc, p, k, rec['scenario'][sc][p][k], summ['summary'][sc][p][k]))
                for ref in ('CAVER-v0.6', 'C9-UCBMean'):
                    if ref == p:
                        continue
                    mine = list(rec['scenario'][sc][p][f'diff_{k}_vs_{ref}'])
                    theirs = [summ['summary'][sc][p][f'diff_{k}_vs_{ref}'], summ['summary'][sc][p][f'diff_{k}_vs_{ref}_ci']]
                    if mine != theirs:
                        mism.append(('diff', sc, p, k, ref, mine, theirs))
    for p in names:
        for ref in ('CAVER-v0.6', 'C9-UCBMean'):
            if ref == p:
                continue
            for k in ('unique_false_pass', 'unique_variant_false_pass'):
                mine = list(rec['pooled'][p][f'diff_{k}_vs_{ref}'])
                theirs = [summ['pooled'][p][f'diff_{k}_vs_{ref}'], summ['pooled'][p][f'diff_{k}_vs_{ref}_ci']]
                if mine != theirs:
                    mism.append(('pooled', p, k, ref, mine, theirs))
    # (2) independent per-run re-implementation, compared run by run
    tasks = [(specs, s, sc, str(dk.TABLE_PATH)) for sc in scen for s in seeds]
    if jobs <= 1:
        mine = [r for t in tasks for r in _audit_task(t)]
    else:
        with ProcessPoolExecutor(max_workers=min(jobs, 2)) as pool:
            mine = [r for rs in pool.map(_audit_task, tasks, chunksize=8) for r in rs]
    dev = {(r['scenario'], r['seed'], r['policy']): r for r in rows}
    run_mism = []
    for r in mine:
        d = dev[(r['scenario'], r['seed'], r['policy'])]
        for k in ('unique_false_pass', 'unique_variant_false_pass', 'duplicate_rate'):
            if r[k] != d[k]:
                run_mism.append((r['scenario'], r['seed'], r['policy'], k, r[k], d[k]))
    # (3) variant-level summaries per scenario and policy
    agg = {}
    for r in mine:
        agg.setdefault((r['scenario'], r['policy']), []).append(r)
    per = {}
    for sc in scen:
        per[sc] = {}
        for p in names:
            rs = agg[(sc, p)]
            per[sc][p] = {k: _ci([r[k] for r in rs])[0] for k in (
                'unique_false_pass', 'unique_variant_false_pass', 'duplicate_rate', 'variant_duplicate_rate',
                'fp_variant_duplicate_share', 'available_variant_false_pass')}
            per[sc][p]['variant_to_case_ratio'] = round(
                per[sc][p]['unique_variant_false_pass'] / per[sc][p]['unique_false_pass'], 4)
    pooled_means = {p: {k: round(mean(per[sc][p][k] for sc in scen), 4) for k in (
        'unique_false_pass', 'unique_variant_false_pass', 'duplicate_rate', 'variant_duplicate_rate',
        'fp_variant_duplicate_share')} for p in names}
    ranks = ranking_audit(summ['summary'], names, scen)
    pooled_case = sorted(names, key=lambda p: -pooled_means[p]['unique_false_pass'])
    pooled_var = sorted(names, key=lambda p: -pooled_means[p]['unique_variant_false_pass'])
    rep = {'meta': {'evidence_type': 'REPLAY audit of devkit metrics (dev salt v011dev)',
                    'dev_dir': str(dev_dir), 'n_seeds_reimplemented': len(list(seeds)),
                    'n_runs_compared': len(mine)},
           'summary_recompute_mismatches': mism,
           'per_run_reimplementation_mismatches': run_mism[:50],
           'n_per_run_mismatches': len(run_mism),
           'per_scenario': per, 'pooled_means': pooled_means,
           'pooled_rank_case': pooled_case, 'pooled_rank_variant': pooled_var,
           'pooled_kendall_tau': kendall_tau(pooled_case, pooled_var),
           'rankings': ranks,
           'pooled_diffs_from_runs': rec['pooled']}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rep, indent=1), encoding='utf-8')
    return rep


def main(argv=None):
    p = argparse.ArgumentParser(description='Agent C de-duplication audit (evaluation side, dev salt only)')
    p.add_argument('dev_dir', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seeds', type=int, default=300)
    p.add_argument('--jobs', type=int, default=2)
    a = p.parse_args(argv)
    rep = run_audit(a.dev_dir, a.output, seeds=range(a.seeds), jobs=a.jobs)
    print('summary mismatches', len(rep['summary_recompute_mismatches']),
          'per-run mismatches', rep['n_per_run_mismatches'], 'runs', rep['meta']['n_runs_compared'])
    print('pooled tau', rep['pooled_kendall_tau'])


if __name__ == '__main__':
    main()
