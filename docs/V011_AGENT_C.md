# CAVER v0.11 Agent C: unique-defect-focused selection and de-duplication audit

Branch `v011/agent-c` (from `research/caver-v011` @ `8bf9b8f`). Own files: `caver11/agent_c.py`,
`tests/test_v011_agent_c.py`, this document, `reports/v011/agent_c/`. Everything below is **REPLAY**
of the stored real outcome table (`reports/v010/outcome_table_extended_real.json`, 42 configs) on the
dev salt `v011dev`, seeds 0–299, through `caver11.devkit`. No final-environment file was opened.

## 1. Audit of de-duplication and defect fingerprints (done first)

**Order of work.** The audit ran the devkit with the 7 baselines only
(`python3 -m caver11.devkit --output reports/v011/agent_c/audit_baselines --jobs 2`). No candidate
was run before the candidates in §2 were committed. The baseline numbers did inform the design. That
is stated here because §2 was written after seeing them.

### 1.1 What is counted today

* `unique_false_pass` counts distinct **(case, family)** pairs whose first eval violation was a
  FALSE_PASS (`caver9.evaluation.run_one`).
* The table is **deterministic**: every one of the 42 configs has identical repetitions, so the
  outcome of a probe depends only on (family, variant). 21 configs are FALSE_PASS, 5 are violations
  without FALSE_PASS, and the rest (including all 6 healthy configs and all of `abnormal_exit` except
  `crash_silent`) do not violate. `abnormal_exit` has no FALSE_PASS variant at all.
* Cases are drawn from a small catalogue of variants (`make_cases`, `make_cases_ext`). The same
  (family, variant) occurs in several cases of one cohort and again in every later cohort. On dev,
  the hold cases contain on average **2.0 cases per distinct FALSE_PASS variant** (1.4 in
  `f_stat_flat` up to 2.7 in `recovery`/`double`): `available_false_pass` / distinct FALSE_PASS
  variants in the hold cases.

### 1.2 Independent verification of the devkit metrics

`caver11/agent_c.py` (Part 2) re-implements the probe loop without calling the devkit: its own
outcome lookup from the raw JSON, its own opaque ids and exhaustion check, and a per-probe trace
that includes the hidden variant. From the trace it recomputes `unique_false_pass`,
`unique_variant_false_pass` and `duplicate_rate`. It also recomputes the per-scenario means, the
paired CIs and the pooled per-seed differences from `runs.csv.gz` alone.

| check | runs compared | mismatches |
|---|---|---|
| per-run re-implementation vs `run_one_ext` (7 baselines × 19 scenarios × 300 seeds) | 39,900 | **0** (all three metrics) |
| summary means, paired diffs/CIs vs v0.6 and C2, pooled diffs, recomputed from `runs.csv.gz` | 19 × 7 policies | **0** |

The counting code is correct for what it is defined to count. Output:
`reports/v011/agent_c/audit_baselines/dedup_audit.json`.

### 1.3 Findings: metric validity (no code is changed here; the devkit belongs to the lead)

**F1 – `duplicate_rate` is structurally near zero and cannot measure duplicate discovery.** It counts
violating eval probes that re-hit an already-found (case, family). The `available()` rule forbids
re-probing a (case, family) until all 6 arms of that case are used, so a re-hit can only happen on an
exhausted case. Pooled over the 19 scenarios it is 0.008 (Random) to 0.014 (C2); in 9 scenarios it
rounds to 0.00 (< 0.005) for every policy. The duplication that matters is at variant level:

| policy | case-level `duplicate_rate` | **variant-level duplicate rate** (violating probes whose (family, variant) was already found as a violation in eval) | share of new (case, family) FALSE_PASS that re-find a known variant |
|---|---|---|---|
| Random | 0.008 | 0.245 | 0.230 |
| UCB1 | 0.015 | 0.348 | 0.329 |
| SW-UCB | 0.011 | 0.294 | 0.279 |
| D-UCB | 0.012 | 0.304 | 0.288 |
| CAVER-v0.6 | 0.013 | 0.364 | 0.367 |
| C2 | 0.014 | 0.363 | 0.365 |
| L1 | 0.014 | 0.366 | 0.367 |

(means of per-scenario means, 19 scenarios × 300 seeds).

**F2 – `duplicate_rate` returns 0.0 when a run has no violating probe.** The ratio is undefined
there. It should be `None` and excluded, as `_ci` already does for `None`. It is rare on dev (every
run has violating probes), so the effect on the reported means is nil here. It could matter in an
environment with sparse defects.

**F3 – there is no variant-level denominator.** `available_false_pass` counts (case, family). For
variant-level recall the matching denominator is the number of distinct FALSE_PASS (family, variant)
configs in the hold cases. On dev that is 9.1–15.7 per run.

**Suggested fix for the lead** (in `run_one_ext`, keeping every existing field):
keep a set `viol_var` of (family, variant) found as violations in eval; add
`variant_duplicate_rate = (# violating eval probes whose (family, variant) ∈ viol_var before the probe) / violating probes`
(None when there are none); set `duplicate_rate = None` when `vp == 0`; add
`available_variant_false_pass = |{(f, v) in hold cases : table.is_fp_defect(f, v)}|`. The functions
`audit_metrics` and the tests in `tests/test_v011_agent_c.py` give a reference implementation.

### 1.4 Findings: how much the results change when uniqueness is per variant

Pooled per-seed mean differences over the 19 scenarios (paired 95% CI):

| comparison | Δ unique FALSE_PASS (case, family) | Δ unique FALSE_PASS (family, variant) |
|---|---|---|
| v0.6 − Random | **+2.11** [2.02, 2.21] | **+0.00** [−0.05, 0.05] |
| C2 − v0.6 | +0.37 [0.30, 0.45] | +0.18 [0.14, 0.23] |
| L1 − v0.6 | +0.40 [0.32, 0.47] | +0.16 [0.12, 0.20] |
| UCB1 − v0.6 | **−0.25** [−0.34, −0.17] | **+0.15** [0.10, 0.21] |
| SW-UCB − v0.6 | −1.22 [−1.30, −1.14] | +0.12 [0.07, 0.16] |
| D-UCB − v0.6 | −1.05 [−1.14, −0.97] | +0.12 [0.06, 0.17] |
| L1 − C2 | +0.03 [−0.04, 0.09] | −0.02 [−0.07, 0.02] |

* **Level.** Variant-level counts are 51–77% (v0.6) and 46–77% (C2) of case-level counts per scenario,
  against 67–83% for Random. Pooled means: v0.6 11.24 → 6.82, C2 11.61 → 7.01, Random 9.12 → 6.83.
* **Ranking.** Pooled case-level ranking: L1 > C2 > v0.6 > UCB1 > D-UCB > SW-UCB > Random. Pooled
  variant-level ranking: C2 > L1 > UCB1 > D-UCB > SW-UCB > Random > **v0.6 (last)**. Kendall τ = 0.52.
  Per scenario τ ranges from −0.71 (`c_uniform`) to 1.00 (`f_gradual`). The sign of Δ vs v0.6 flips
  between the two levels in 5 (C2, L1) to 10 (Random, D-UCB) of the 19 scenarios.
* **Interpretation.** v0.6's case-level lead comes from concentrating on the family that is richest
  *now*. That family re-yields the same few variants (v0.6 re-finds a known variant in 37% of its new
  FALSE_PASS findings, Random in 23%). At variant level v0.6 is no better than Random. C2's gain over
  v0.6 survives at variant level, at about half the size. **The study objective ("more unique
  FALSE_PASS") depends on which uniqueness is meant.** The dev rule (§5 of the design) uses the
  case-level count. This document reports both and changes neither the rule nor the devkit.
* **Caveat.** Policies cannot observe variants (only booleans and an opaque case id). A deterministic
  table means a variant re-found in a new case is a genuine repeat of the same Hook behaviour, so
  variant-level is the more defensible notion of a *distinct defect*. Case-level still measures the
  number of defective test targets found. Both are REPLAY on 42 configs.

## 2. Candidates (pre-declared; committed before any candidate dev run)

All candidates use the shared interface, respect `available()`, use the opaque case id only as a
dictionary key (never parsed), and learn only from their own `(case_id, arm, newly_found)` updates.
The reward is `newly_found` (new FALSE_PASS), as for v0.6 and C2. Variants are not visible to any
policy, so variant-level diversity can only be pursued through arm-level proxies.

### C-A `caver11.agent_c:PopBayesUCB` (name `C11C-PopBUCB`)

* **Active population.** At each select, the active cases are the distinct case ids seen in the last
  `W_POP = 20` learned probes, plus the current case. For every active case, the *first* probe of
  each (case, arm) contributes one observation (newly_found ∈ {0, 1}), whenever it was made. Repeat
  probes of an exhausted case are ignored for estimation.
* **Shrunk posterior.** Per arm f: n_f, s_f = observations and successes over the active cases;
  g_f = (S_f + 1) / (N_f + 2) is the all-time rate over all first probes (Beta(1, 1), `PRIOR_A =
  PRIOR_B = 1`); posterior Beta(a, b) with a = s_f + `LAMBDA`·g_f and b = (n_f − s_f) +
  `LAMBDA`·(1 − g_f), `LAMBDA = 4`.
* **Selection.** Bayes-UCB score = mean + `KAPPA`·sd, `KAPPA = 1.0`; argmax over the available arms
  in a shuffled order (ties at random). No detector, no sentinel, no ε.
* **Rationale.** The expected *new* coverage of probing arm f is the rate of unfound arm-f defects
  in the population the cases are currently drawn from. Defects are attributes of cases. So the
  relevant evidence is the history of the cases that are currently being drawn, however old that
  history is. In a stable regime, recurring cases keep their old evidence in the estimate (long
  memory). When the drawn population changes, the old cases stop recurring and their evidence leaves
  the estimate within `W_POP` probes (short memory). No alarm is raised.
* **Risk, stated beforehand.** v0.10 Agent A flagged the *rate of new case ids* as a benchmark
  artefact (fresh case pools per regime). C-A does not use the new-id rate as a change signal. Its
  memory is still keyed on case recurrence. If a final environment keeps the case pool and changes
  only which cases are drawn, C-A still tracks the drawn population, but more slowly (up to
  `W_POP` probes). If an environment changed a case's defects while keeping its id, the evidence
  would be stale. The harness's `available()` rule already assumes fixed defects per case.

### C-B `caver11.agent_c:PopDivBUCB` (name `C11C-PopBUCB-Div`)

C-A plus a diversity choice among near-optimal arms.
* Near-optimal set A* = available arms with score ≥ max score − `DELTA`, `DELTA = 0.05`.
* found_f = new FALSE_PASS findings on arm f in the current phase (reset by `begin_evaluation`).
* Pick argmax over A* of p_f · [H(found + s + e_f) − H(found + s)], where H is the Shannon entropy of
  the count vector, s = `DIV_SMOOTH = 0.5` is added to every arm, and p_f is the posterior mean. Ties
  go to the higher score, then to the shuffled order.
* **Aim.** Spend near-ties on families with few findings so far. A family with many findings re-yields
  known variants (F1), so this targets variant-level uniqueness at a small case-level cost.

### C-C `caver11.agent_c:C2Div` (name `C11C-C2-Div`)

C2 (`caver9.exploration.UCBMeanCAVER`, c = 0.5, confirmed detector and local reset) **unchanged**.
The only change is the same entropy-gain choice as C-B (`DELTA = 0.05`, `DIV_SMOOTH = 0.5`) among
arms within `DELTA` of C2's best score, with p_f = C2's posterior mean. When untried arms give
infinite scores, A* is the set of untried arms. The RNG call order is C2's. C-C isolates the
diversity component on a known base.

### Constants (complete list)

| candidate | constant | value |
|---|---|---|
| C-A, C-B | `W_POP` | 20 learned probes |
| C-A, C-B | `LAMBDA` | 4.0 pseudo-observations |
| C-A, C-B | `KAPPA` | 1.0 |
| C-A, C-B | `PRIOR_A`, `PRIOR_B` | 1.0, 1.0 |
| C-B, C-C | `DELTA` | 0.05 |
| C-B, C-C | `DIV_SMOOTH` | 0.5 |
| C-C | C2 constants | c = 0.5, no sentinel, ε = 0, `ConfirmedFamilyDetector` defaults (inherited) |

### Mapping to the literature (inspired by; not implementations of the published methods)

| idea | source | what is used | deviations |
|---|---|---|---|
| aggregate counts + entropy-maximising candidate choice | Q-gram ART (Biagiola, Feldt, Tonella 2025) | C-B/C-C keep an aggregate count vector and pick the candidate that most increases its Shannon entropy | q = 1 over *arms with a FALSE_PASS finding*, not q-grams of test-sequence tokens; candidates are the ≤ 6 available arms, not generated test sequences; entropy gain is weighted by the estimated hit rate and applied only among near-optimal arms (a tie-break, not the primary objective); no claim about ART's results transfers |
| per-test failure history as state | RETECS (Spieker et al. 2017) | C-A keeps per-case (per test target) outcome history | no RL agent, no network, no CI cycles; the history feeds a Beta estimate |
| volatile arm set (tests appear/disappear) | COLEMAN (Prado Lima & Vergilio 2022), **repository docs only** | C-A treats cases that stop recurring as leaving the population | the paper's formulas were not verified; COLEMAN prioritises test cases, while here cases are given and arms are chosen |
| posterior-quantile index | Bayes-UCB (Kaufmann et al. 2012) | mean + κ·sd of a Beta posterior | sd instead of a quantile; fixed κ; empirical-Bayes shrinkage prior |

## 3. Dev results

The candidates were committed in `2f6f10e` and then run once:
`python3 -m caver11.devkit --candidates caver11.agent_c:PopBayesUCB caver11.agent_c:PopDivBUCB
caver11.agent_c:C2Div --output reports/v011/agent_c/dev --jobs 2` (salt `v011dev`, seeds 0–299,
19 scenarios, REPLAY). The full per-scenario tables are in `reports/v011/agent_c/dev/dev_table.md`.
The de-duplication audit was re-run on this output (`dev/dedup_audit.json`). It again found
**0 mismatches** over 57,000 runs, so the devkit metrics are exact for the candidates as well.

### 3.1 Pooled (per-seed mean difference over the 19 scenarios, 95% CI)

| candidate | Δ case-level vs v0.6 | Δ case-level vs C2 | Δ variant-level vs v0.6 | Δ variant-level vs C2 | dev_rule |
|---|---|---|---|---|---|
| C-A `C11C-PopBUCB` | **+0.68** [+0.60, +0.76] | **+0.31** [+0.23, +0.39] | +0.12 [+0.08, +0.17] | −0.06 [−0.11, −0.01] | **10/126 failed** |
| C-B `C11C-PopBUCB-Div` | **+0.66** [+0.58, +0.74] | **+0.29** [+0.21, +0.37] | **+0.28** [+0.23, +0.32] | **+0.10** [+0.05, +0.14] | **6/126 failed** |
| C-C `C11C-C2-Div` | −0.42 [−0.50, −0.34] | −0.79 [−0.88, −0.71] | +0.30 [+0.25, +0.35] | +0.12 [+0.07, +0.17] | 60/142 failed |

U (pooled vs v0.6 and vs C2, lower bounds > 0) **passes** for C-A and C-B.

### 3.2 Per scenario (case-level unique FALSE_PASS; Δ = paired mean, CI lower bound in brackets)

| scenario | type | v0.6 | C2 | C-A | C-B | C-A Δ v0.6 (lo) | C-A Δ C2 (lo) | C-B Δ v0.6 (lo) | C-B Δ C2 (lo) |
|---|---|---|---|---|---|---|---|---|---|
| stationary | stable | 11.68 | 11.51 | 11.91 | 11.60 | +0.23 (+0.03) | +0.40 (+0.21) | −0.08 (**−0.28**) | +0.09 (−0.12) |
| f_stat_skew | stable | 9.82 | 9.62 | 10.09 | 9.82 | +0.27 (+0.09) | +0.46 (+0.26) | +0.00 (−0.17) | +0.20 (−0.02) |
| f_stat_flat | stable | 9.30 | 8.90 | 9.48 | 9.26 | +0.19 (−0.03) | +0.58 (+0.35) | −0.03 (**−0.26**) | +0.36 (+0.13) |
| c_uniform | stable | 11.97 | 11.31 | 12.11 | 12.01 | +0.14 (−0.18) | +0.81 (+0.46) | +0.04 (**−0.28**) | +0.71 (+0.36) |
| f_flat_shift | stable | 10.70 | 10.55 | 10.85 | 10.87 | +0.15 (−0.14) | +0.30 (−0.01) | +0.17 (−0.13) | +0.32 (+0.02) |
| abrupt | abrupt | 12.36 | 13.45 | 13.49 | 13.58 | +1.13 (+0.84) | +0.04 (−0.25) | +1.21 (+0.95) | +0.13 (−0.14) |
| delayed | abrupt | 12.05 | 13.30 | 13.73 | 13.99 | +1.68 (+1.28) | +0.43 (+0.02) | +1.94 (+1.54) | +0.69 (+0.32) |
| early | abrupt | 12.58 | 13.79 | 13.94 | 14.05 | +1.36 (+1.02) | +0.14 (−0.20) | +1.47 (+1.12) | +0.26 (−0.08) |
| single | abrupt | 11.79 | 12.75 | 12.89 | 12.90 | +1.11 (+0.76) | +0.14 (−0.24) | +1.11 (+0.74) | +0.15 (−0.23) |
| c_late | abrupt | 10.96 | 11.48 | 11.90 | 11.78 | +0.94 (+0.63) | +0.42 (+0.09) | +0.82 (+0.50) | +0.30 (−0.02) |
| c_reverse | abrupt | 9.69 | 10.15 | 10.40 | 10.39 | +0.72 (+0.46) | +0.25 (−0.00) | +0.70 (+0.45) | +0.24 (−0.01) |
| f_abrupt_boundary | abrupt | 8.17 | 8.50 | 8.78 | 8.59 | +0.61 (+0.37) | +0.28 (+0.04) | +0.41 (+0.18) | +0.08 (−0.15) |
| f_abrupt_after | abrupt | 11.83 | 11.94 | 12.43 | 12.52 | +0.61 (+0.30) | +0.50 (+0.18) | +0.69 (+0.38) | +0.58 (+0.24) |
| recovery | other | 12.51 | 13.04 | 13.04 | 13.26 | +0.53 (+0.13) | +0.00 (−0.42) | +0.74 (+0.31) | +0.22 (−0.21) |
| gradual | other | 12.09 | 12.65 | 13.11 | 13.09 | +1.03 (+0.64) | +0.46 (+0.08) | +1.00 (+0.61) | +0.44 (+0.02) |
| double | other | 11.58 | 13.19 | 12.79 | 13.32 | +1.21 (+0.82) | −0.40 (−0.86) | +1.74 (+1.35) | +0.13 (−0.32) |
| c_oscillate | other | 11.82 | 12.25 | 12.20 | 12.04 | +0.39 (+0.02) | −0.05 (−0.43) | +0.23 (−0.13) | −0.21 (−0.61) |
| f_spike | other | 11.14 | 11.03 | 11.36 | 11.25 | +0.22 (−0.12) | +0.33 (−0.05) | +0.11 (−0.27) | +0.23 (−0.17) |
| f_gradual | other | 11.49 | 11.16 | 11.91 | 11.76 | +0.42 (+0.14) | +0.75 (+0.44) | +0.27 (−0.05) | +0.60 (+0.28) |

### 3.3 `devkit.dev_rule` outcome

* **C-A (10 failed / 126):** K_recovery vs v0.6 in all 8 abrupt scenarios (CI upper bounds +0.03 in
  `c_late` to +5.67 in `f_abrupt_boundary`; recovery is not faster than v0.6). G vs UCB1 in `double`
  (−0.30) and `single` (−0.30). All 5 S checks pass (minimum lower bound −0.18, `c_uniform`). All
  K vs v0.6, K vs C2 and U checks pass.
* **C-B (6 failed / 126):** S vs v0.6 in `stationary` (−0.277), `f_stat_flat` (−0.259) and
  `c_uniform` (−0.280), each just below the −0.25 threshold. K_recovery vs v0.6 in `c_reverse`
  (+1.17) and `f_abrupt_boundary` (+3.29). G vs UCB1 in `single` (−0.27). The other 6 abrupt
  scenarios pass recovery with a significantly faster mean (−1.9 to −2.8 steps vs v0.6).
* **C-C (60 failed / 142):** the diversity tie-break on C2's large UCB scores overrides exploitation
  too often. It fails S, K, G and U broadly, while giving the largest variant-level gain.
* FA is not checked for C-A/C-B (no detector). For C-C, FA passes.

**No candidate is eligible.** Under §4 of the design, nothing is nominated. For the lead's
information only: the fewest failed checks is C-B (6/126). It is the only candidate that improves
both case-level (pooled vs v0.6 and C2) and variant-level (pooled vs v0.6 and C2) uniqueness with all
four lower bounds > 0.

### 3.4 Other metrics (mean of the 19 scenario means)

| policy | case uFP | variant uFP | duplicate_rate | variant dup rate | FP re-find share | entropy | first find | CPU µs/probe | USD/probe |
|---|---|---|---|---|---|---|---|---|---|
| CAVER-v0.6 | 11.237 | 6.825 | 0.0129 | 0.364 | 0.367 | 0.888 | 6.15 | 9.6 | 0.02372 |
| C2 | 11.609 | 7.006 | 0.0140 | 0.363 | 0.365 | 0.926 | 6.59 | 9.6 | 0.02385 |
| L1 | 11.634 | 6.984 | 0.0142 | 0.366 | 0.366 | 0.918 | 6.15 | 11.8 | 0.02391 |
| C-A | 11.917 | 6.945 | 0.0164 | 0.390 | 0.389 | 0.873 | 6.18 | 19.7 | 0.02368 |
| C-B | 11.898 | 7.101 | 0.0165 | 0.375 | 0.373 | 0.896 | 6.29 | 31.7 | 0.02366 |
| C-C | 10.814 | 7.129 | 0.0129 | 0.312 | 0.306 | 0.951 | 6.66 | 25.1 | 0.02364 |

Replayed API-equivalent cost per probe is the same for all policies (±1%). The per-probe wall time
is about 10.5 s for every policy. The policies' own CPU cost (20–32 µs/probe) is negligible next to
a real probe.

### 3.5 Post-hoc exploratory ablations (NOT pre-declared, NOT eligible)

These were added after the dev run, to find where C-A's gain comes from. Its memory is keyed on case
recurrence, which v0.10 flagged as an artefact risk.
`reports/v011/agent_c/posthoc_ablation/` (same devkit command; `ablation_comparison.json`).

| arm | change vs C-A | pooled Δ vs v0.6 | pooled Δ vs C2 | dev_rule failed | C-A minus arm, pooled |
|---|---|---|---|---|---|
| PH-1 `PH-C11C-ProbeWindow` | estimate from the last 20 probes (not case-keyed) | +0.64 | +0.26 | 14/126 | +0.04 [−0.02, +0.11] |
| PH-2 `PH-C11C-AllHistory` | active population = every case ever seen | +0.29 | −0.09 | 41/126 | +0.39 [+0.32, +0.47] |

* **Most of C-A's gain does not depend on case recurrence.** A plain 20-probe window with the same
  shrunk Bayes-UCB recovers +0.64 of C-A's +0.68 vs v0.6. Case-keying adds +0.04 pooled (CI includes
  0). Its sign is mixed by scenario: −0.51 `double`, −0.46 `recovery`, +0.36 `gradual`, +0.33
  `c_oscillate`.
* **The short memory matters.** Without a window (PH-2), C-A loses 0.39 pooled. PH-2 is better in the
  stable scenarios (for example +0.26 in `stationary`) but much worse after shifts.
* The working ingredient is therefore a **short-memory, empirical-Bayes-shrunk Bayes-UCB on the
  new-FALSE_PASS reward**. It has no detector, sentinel or ε. Its weakness is the K_recovery
  criterion. Diversity (C-B) repairs most of the recovery failures but costs about 0.2–0.3 in the
  stable scenarios.

## 4. Caveats

* Everything is REPLAY of 42 deterministic configs on one dev salt. The dev scenarios include the
  spent v0.9c/v0.10 scenarios. No final-environment data was seen.
* The baselines-only audit run happened before §2 was written, so the candidate design was informed
  by baseline dev numbers (§1). No candidate was run before `2f6f10e`.
* The post-hoc ablations are not eligible and were not tuned. No constant of C-A/C-B/C-C was changed
  after the dev run.
* C-A/C-B's case-keyed memory could behave differently in an environment whose shifts keep the case
  pool. The ablation suggests that little of the gain depends on it, but this was not tested on such
  an environment.
* Variant-level uniqueness is not observable by any policy. Its improvement in C-B/C-C comes only
  from spreading findings over families.
