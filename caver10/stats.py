"""CAVER v0.10 (Agent C): statistics for the final run and the V010_DESIGN section 5 criteria.

Pure Python (deterministic everywhere, no numpy dependency).

* paired normal-approximation CI (mean +/- 1.96 sd/sqrt(n)) and two-sided p-value;
* paired percentile bootstrap CI over seeds (fixed seed, 2000 resamples by default; the same
  resampled seed sets are reused for every comparison, so all comparisons are jointly paired);
* Holm-Bonferroni adjustment;
* Kaplan-Meier survival, median and restricted mean (RMST) for censored recovery times;
* ``paired_summary``: per scenario / policy summary with all candidate-vs-reference deltas;
* ``evaluate_criteria``: S1, S2, K1, K2, G, FA, RV exactly as in V010_DESIGN section 5.
"""
from __future__ import annotations

import math
import random
from functools import lru_cache
from statistics import mean, stdev

Z95 = 1.959963984540054
BOOT_N = 2000
BOOT_SEED = 20101          # fixed before any final data exist
ON_HOLD = '채택 보류 (adoption on hold)'
ADOPT = 'adopt'


# --------------------------------------------------------------------------------------
# Paired differences
# --------------------------------------------------------------------------------------
def _get(r, k):
    return r[k] if isinstance(r, dict) else getattr(r, k)


def p_two_sided_normal(m: float, se: float) -> float:
    if se == 0:
        return 1.0 if m == 0 else 0.0
    return math.erfc(abs(m / se) / math.sqrt(2))


def paired_normal(diffs) -> dict:
    """mean, 95% CI (normal approximation), se, z and two-sided p of paired differences."""
    d = [x for x in diffs if x is not None]
    if not d:
        return {'n': 0, 'mean': None, 'ci': None, 'se': None, 'p': None}
    m = mean(d)
    if len(d) < 2:
        return {'n': 1, 'mean': m, 'ci': None, 'se': None, 'p': None}
    se = stdev(d) / math.sqrt(len(d))
    return {'n': len(d), 'mean': m, 'ci': [m - Z95 * se, m + Z95 * se], 'se': se,
            'p': p_two_sided_normal(m, se)}


@lru_cache(maxsize=16)
def bootstrap_indices(n: int, n_boot: int = BOOT_N, seed: int = BOOT_SEED) -> tuple:
    rng = random.Random(f'caver10-bootstrap:{seed}:{n}')
    return tuple(tuple(rng.choices(range(n), k=n)) for _ in range(n_boot))


def _quantile(sorted_vals, q: float) -> float:
    """Linear interpolation quantile (numpy 'linear' / type 7)."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def paired_bootstrap(diffs, n_boot: int = BOOT_N, seed: int = BOOT_SEED, level: float = 0.95) -> dict:
    """Percentile bootstrap CI of the mean paired difference (resampling seeds) and a two-sided
    bootstrap p-value 2*min(P*(mean <= 0), P*(mean >= 0)) with the +1 correction."""
    d = list(diffs)
    if any(x is None for x in d):
        raise ValueError('bootstrap needs complete pairs (no None)')
    n = len(d)
    if n < 2:
        return {'n': n, 'mean': (d[0] if d else None), 'ci': None, 'p': None, 'n_boot': n_boot, 'seed': seed}
    means = sorted(sum(d[i] for i in idx) / n for idx in bootstrap_indices(n, n_boot, seed))
    a = (1 - level) / 2
    le = sum(1 for x in means if x <= 0)
    ge = sum(1 for x in means if x >= 0)
    p = min(1.0, 2 * (min(le, ge) + 1) / (n_boot + 1))
    return {'n': n, 'mean': mean(d), 'ci': [_quantile(means, a), _quantile(means, 1 - a)], 'p': p,
            'n_boot': n_boot, 'seed': seed}


def holm(pvalues: dict) -> dict:
    """Holm-Bonferroni step-down adjusted p-values (monotone, capped at 1). None stays None."""
    items = sorted(((p, k) for k, p in pvalues.items() if p is not None), key=lambda x: (x[0], str(x[1])))
    m = len(items)
    out, running = {k: None for k, p in pvalues.items() if p is None}, 0.0
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


# --------------------------------------------------------------------------------------
# Censored recovery times
# --------------------------------------------------------------------------------------
def kaplan_meier(times, censored) -> list[tuple[float, float]]:
    """KM survival steps [(t, S(t))] at each distinct event time. ``censored[i]`` True means
    T_i > times[i] (still not recovered at times[i])."""
    data = list(zip(times, censored))
    if not data:
        return []
    event_times = sorted({t for t, c in data if not c})
    s, out = 1.0, []
    for t in event_times:
        at_risk = sum(1 for u, _ in data if u >= t)
        d = sum(1 for u, c in data if u == t and not c)
        if at_risk:
            s *= 1 - d / at_risk
        out.append((t, s))
    return out


def km_median(times, censored):
    """Smallest t with S(t) <= 0.5, or None if the KM curve never reaches 0.5 (median not reached)."""
    for t, s in kaplan_meier(times, censored):
        if s <= 0.5 + 1e-12:
            return t
    return None


def rmst(times, censored, tau: float) -> float:
    """Restricted mean survival time: integral of the KM curve from 0 to ``tau``."""
    area, prev_t, s = 0.0, 0.0, 1.0
    for t, s_new in kaplan_meier(times, censored):
        if t >= tau:
            break
        area += s * (t - prev_t)
        prev_t, s = t, s_new
    return area + s * (tau - prev_t)


def parse_recovery_events(txt: str) -> list[tuple[int, bool, int | None]]:
    """caver9 Run9.recovery_events ('12;31+') -> [(time, censored, cap_if_censored)].
    A censored entry 'c+' means no recovery within the horizon: T > c - 1."""
    out = []
    for part in (txt or '').split(';'):
        if not part:
            continue
        if part.endswith('+'):
            cap = int(part[:-1])
            out.append((cap - 1, True, cap))
        else:
            out.append((int(part), False, None))
    return out


def recovery_km(runs, caps) -> list[dict]:
    """Per shift event: KM median, RMST up to the cap (= horizon - change + 1) and censoring rate."""
    per = [[] for _ in caps]
    for r in runs:
        ev = parse_recovery_events(_get(r, 'recovery_events'))
        for i, e in enumerate(ev):
            per[i].append(e)
    out = []
    for i, cap in enumerate(caps):
        ts = [e[0] for e in per[i]]
        cs = [e[1] for e in per[i]]
        med = km_median(ts, cs)
        out.append({'event': i, 'n': len(ts), 'cap': cap, 'censored_rate': (sum(cs) / len(cs)) if cs else None,
                    'km_median': med, 'km_median_note': None if med is not None else f'not reached (> {cap - 1})',
                    'rmst': rmst(ts, cs, cap) if ts else None})
    return out


# --------------------------------------------------------------------------------------
# Summary over runs
# --------------------------------------------------------------------------------------
def _round(x, k=4):
    if x is None:
        return None
    if isinstance(x, list):
        return [_round(v, k) for v in x]
    return round(x, k)


def compare(a_vals, b_vals, n_boot=BOOT_N, seed=BOOT_SEED) -> dict:
    pairs = [(x, y) for x, y in zip(a_vals, b_vals) if x is not None and y is not None]
    d = [x - y for x, y in pairs]
    if not d:
        return {'n': 0, 'mean': None, 'ci': None, 'p': None, 'boot_ci': None, 'boot_p': None}
    nrm = paired_normal(d)
    bt = paired_bootstrap(d, n_boot, seed)
    return {'n': nrm['n'], 'mean': _round(nrm['mean']), 'ci': _round(nrm['ci']), 'se': _round(nrm['se'], 5),
            'p': nrm['p'], 'boot_ci': _round(bt['ci']), 'boot_p': bt['p']}


def paired_summary(runs, names, scenario_caps: dict, references, *, fa_defined: dict,
                   n_boot: int = BOOT_N, seed: int = BOOT_SEED) -> dict:
    """``scenario_caps[sc]`` = list of recovery caps per shift event ([] for stationary);
    ``fa_defined[sc]`` = whether the scenario has a false-alarm window.
    Output: summary[sc][policy] = {n, unique_false_pass, recovery_rmst, recovery_events_km,
    false_alarm_rate, has_detector, diff: {ref: {unique_false_pass: {...}, recovery_steps: {...}}}}."""
    out = {}
    for sc, caps in scenario_caps.items():
        rs = [r for r in runs if _get(r, 'scenario') == sc]
        if not rs:
            continue
        by = {n: sorted((r for r in rs if _get(r, 'policy') == n), key=lambda r: _get(r, 'seed')) for n in names}
        seeds0 = [_get(r, 'seed') for r in by[names[0]]]
        block = {}
        for n, pieces in by.items():
            if [_get(r, 'seed') for r in pieces] != seeds0:
                raise AssertionError(f'unpaired seeds for {n} in {sc}')
            det = bool(pieces and _get(pieces[0], 'has_detector'))
            m = {'n': len(pieces), 'has_detector': det,
                 'unique_false_pass': _round(mean(_get(r, 'unique_false_pass') for r in pieces)),
                 'unique_false_pass_ci': _round(paired_normal([_get(r, 'unique_false_pass') for r in pieces])['ci'])}
            if caps:
                m['recovery_rmst'] = _round(mean(_get(r, 'recovery_steps') for r in pieces))
                m['recovery_censored_rate'] = _round(mean(bool(_get(r, 'recovery_censored')) for r in pieces))
                m['recovery_events_km'] = [{k: _round(v) if isinstance(v, float) else v for k, v in e.items()}
                                           for e in recovery_km(pieces, caps)]
            else:
                m['recovery_rmst'] = m['recovery_censored_rate'] = m['recovery_events_km'] = None
            if fa_defined.get(sc):
                # a policy without a detector raises no alarm: false-alarm rate 0 by definition
                m['false_alarm_rate'] = _round(mean(float((_get(r, 'prechange_alarms') or 0) > 0) for r in pieces)) \
                    if det else 0.0
                m['false_alarm_note'] = None if det else 'no detector: no alarms (rate 0 by definition)'
            else:
                m['false_alarm_rate'] = None
            m['diff'] = {}
            for ref in references:
                if ref == n or ref not in by:
                    continue
                d = {'unique_false_pass': compare([_get(r, 'unique_false_pass') for r in pieces],
                                                  [_get(r, 'unique_false_pass') for r in by[ref]], n_boot, seed)}
                if caps:
                    d['recovery_steps'] = compare([_get(r, 'recovery_steps') for r in pieces],
                                                  [_get(r, 'recovery_steps') for r in by[ref]], n_boot, seed)
                m['diff'][ref] = d
            block[n] = m
        out[sc] = block
    return out


def holm_table(summary: dict, candidate: str, metrics=('unique_false_pass', 'recovery_steps')) -> dict:
    """Holm-adjusted p-values across ALL reported candidate-vs-reference comparisons."""
    raw = {}
    for sc, block in summary.items():
        for ref, d in (block.get(candidate, {}).get('diff') or {}).items():
            for k in metrics:
                if k in d:
                    raw[f'{sc}|{ref}|{k}'] = d[k]['p']
    adj = holm(raw)
    return {k: {'p': raw[k], 'p_holm': adj[k]} for k in raw}


# --------------------------------------------------------------------------------------
# Criteria (V010_DESIGN section 5)
# --------------------------------------------------------------------------------------
def _ci(summary, sc, cand, ref, metric, method):
    m = summary.get(sc, {}).get(cand)
    if m is None:
        return None
    if 'diff' in m:
        d = (m['diff'].get(ref) or {}).get(metric)
        if not d:
            return None
        return d.get('boot_ci' if method == 'bootstrap' else 'ci')
    return m.get(f'diff_{metric}_vs_{ref}_ci')    # caver9.evaluation.summarize format


def _check(checks, sc, test, ci, side, thr):
    """side 'lo>' : CI lower bound > thr ; 'hi<' : CI upper bound < thr."""
    if ci is None:
        checks.append({'scenario': sc, 'test': test, 'value': None, 'threshold': thr, 'pass': False,
                       'note': 'missing'})
        return
    v = ci[0] if side == 'lo>' else ci[1]
    ok = v > thr if side == 'lo>' else v < thr
    checks.append({'scenario': sc, 'test': test, 'value': v, 'threshold': thr, 'pass': bool(ok)})


def evaluate_criteria(summary: dict, bindings: dict, *, candidate: str, v06: str = 'CAVER-v0.6',
                      c2: str = 'C9-UCBMean', g_baselines=('Random', 'SW-UCB', 'D-UCB'), rv: dict | None = None,
                      ci_method: str = 'normal') -> dict:
    """``bindings``: {'stationary': [...], 'flat_shift': [...], 'abrupt': [...], 'all': [...],
    'false_alarm': [...] (optional; default = scenarios of 'all' with a false-alarm rate)}.
    ``rv``: ``caver10.variants_ext.agreement`` output (or {'all_multi_measured_agree': bool}).
    Missing data fail the check (conservative). Adoption requires every criterion."""
    if ci_method not in ('normal', 'bootstrap'):
        raise ValueError(ci_method)
    stat = list(bindings.get('stationary', ())) + list(bindings.get('flat_shift', ()))
    abrupt = list(bindings.get('abrupt', ()))
    allsc = list(bindings.get('all', ()))
    if not bindings.get('stationary') or not bindings.get('flat_shift') or not abrupt or not allsc:
        raise ValueError('bindings need non-empty stationary, flat_shift, abrupt and all lists')
    if not set(stat + abrupt) <= set(allsc):
        raise ValueError('every bound scenario must also be in "all"')
    fa = bindings.get('false_alarm')
    if fa is None:
        fa = [sc for sc in allsc if summary.get(sc, {}).get(v06, {}).get('false_alarm_rate') is not None]
    cr = {k: [] for k in ('S1', 'S2', 'K1', 'K2', 'G', 'FA', 'RV')}
    for sc in stat:
        _check(cr['S1'], sc, f'dFP vs {v06} lo > -0.25', _ci(summary, sc, candidate, v06, 'unique_false_pass', ci_method), 'lo>', -0.25)
        _check(cr['S2'], sc, f'dFP vs {c2} lo > 0', _ci(summary, sc, candidate, c2, 'unique_false_pass', ci_method), 'lo>', 0.0)
    for sc in abrupt:
        _check(cr['K1'], sc, f'dFP vs {c2} lo > -0.3', _ci(summary, sc, candidate, c2, 'unique_false_pass', ci_method), 'lo>', -0.3)
        _check(cr['K1'], sc, f'dFP vs {v06} lo > 0', _ci(summary, sc, candidate, v06, 'unique_false_pass', ci_method), 'lo>', 0.0)
        _check(cr['K2'], sc, f'dRecovery vs {v06} hi < 0', _ci(summary, sc, candidate, v06, 'recovery_steps', ci_method), 'hi<', 0.0)
        _check(cr['K2'], sc, f'dRecovery vs {c2} hi < +1.5', _ci(summary, sc, candidate, c2, 'recovery_steps', ci_method), 'hi<', 1.5)
    for sc in allsc:
        for b in g_baselines:
            _check(cr['G'], sc, f'dFP vs {b} lo > 0', _ci(summary, sc, candidate, b, 'unique_false_pass', ci_method), 'lo>', 0.0)
        _check(cr['G'], sc, f'dFP vs {v06} lo > -0.5', _ci(summary, sc, candidate, v06, 'unique_false_pass', ci_method), 'lo>', -0.5)
    for sc in fa:
        c = summary.get(sc, {}).get(candidate, {}).get('false_alarm_rate')
        r = summary.get(sc, {}).get(v06, {}).get('false_alarm_rate')
        ok = c is not None and r is not None and c <= r + 0.05 + 1e-12
        cr['FA'].append({'scenario': sc, 'test': f'FA rate <= {v06} + 0.05', 'value': c,
                         'threshold': None if r is None else round(r + 0.05, 4), 'pass': bool(ok),
                         **({} if (c is not None and r is not None) else {'note': 'missing'})})
    if rv is None:
        cr['RV'].append({'test': 'repeated real runs agree', 'value': None, 'pass': False, 'note': 'RV not provided'})
    else:
        ok = bool(rv.get('all_multi_measured_agree'))
        cr['RV'].append({'test': 'repeated real runs agree', 'value': rv.get('disagreeing_configs', []), 'pass': ok,
                         'configs_measured_twice_or_more': rv.get('configs_measured_twice_or_more')})
    result = {k: {'pass': all(c['pass'] for c in v), 'checks': v} for k, v in cr.items()}
    adopt = all(v['pass'] for v in result.values())
    return {'criteria': result, 'adopt': adopt, 'verdict': ADOPT if adopt else ON_HOLD,
            'failed': [k for k, v in result.items() if not v['pass']], 'ci_method': ci_method,
            'candidate': candidate, 'references': {'v06': v06, 'c2': c2, 'g_baselines': list(g_baselines)},
            'bindings': {**{k: list(v) for k, v in bindings.items()}, 'false_alarm': list(fa)}}
