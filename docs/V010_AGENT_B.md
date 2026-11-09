# CAVER v0.10 — Agent B: adaptive exploration coefficient

Branch `v010/agent-b`, from `research/caver-v010-adaptive` @ `e588637`. Design: `docs/V010_DESIGN.md`.

**Status of this document.** Sections 1–5 were written and committed **before the first dev run**.
They hold the analysis, the candidates with all constants, and the dev selection rule. Results
(section 6 onward) are added after the dev run. Anything added later that was not declared here
is labelled **post-hoc, not eligible**. Constants are not changed after seeing dev data.

Prior art and no novelty claim: UCB1 (Auer, Cesa-Bianchi & Fischer 2002); variance-aware bonuses
UCB1-Tuned (same paper) and UCB-V (Audibert, Munos & Szepesvári 2009); posterior-scaled bonuses
in the spirit of Bayes-UCB (Kaufmann, Cappé & Garivier 2012); Page's CUSUM (Page 1954);
change-point-triggered restarts of UCB exploration such as CUSUM-UCB (Liu, Lee & Shroff 2018) and
M-UCB (Cao et al. 2019); discounting and sliding windows (Garivier & Moulines 2011); decaying
exploration schedules. **Agent B makes no novelty claim.** The candidates are configurations of
these known ideas on top of C2.

## 1. Problem

C2 (`caver9.exploration:UCBMeanCAVER`, `C9-UCBMean`) scores an arm as
`m_f + C·√(2 ln max(2,t) / n_f)`, where m_f is the Beta(s+1, f+1) posterior mean of the
novelty reward and C = 0.5 is fixed. In v0.9c it gained under abrupt and delayed shifts but lost to
v0.6 in `stationary` (−0.19 [−0.35, −0.03]) and `c_uniform` (−0.31 [−0.59, −0.04]). It only tied
D-UCB in `c_reverse` (+0.15 [−0.05, 0.35]).

## 2. Pre-dev analysis (analytic; uses only committed v0.9 data and the generator/table)

**Per-arm novelty yield of one fresh probe.** This is P(defect in family) × FALSE_PASS-variant
fraction, from `caver8.benchmark.make_cases` and the real table. No seeds are used.

| arm (family) | W_BASE | W_SHIFT | uniform |
|---|---|---|---|
| canonical (schema) | 0.231 | 0.032 | 0.125 |
| case_shift (field_value) | 0.179 | 0.047 | 0.125 |
| leading_space (abnormal_exit) | 0.000 | 0.000 | 0.000 |
| tool_alias (timeout) | 0.062 | 0.092 | 0.083 |
| nested_wrapper (matcher) | 0.078 | 0.208 | 0.125 |
| extra_metadata (exec_mismatch) | 0.063 | 0.328 | 0.167 |

**Observations.**

1. **The value of C is a trade-off.** The committed v0.9 dev data (`v09dev`, 200 seeds) shows it:

   | C | stationary | abrupt recovery | delayed recovery |
   |---|---|---|---|
   | 0.25 | 12.21 | 16.2 | 19.0 |
   | 0.5 | 11.65 | 12.3 | 12.5 |
   | 1.0 | 10.87 | 8.6 | 8.6 |

   A lower C helps when nothing changes. Recovery, however, is driven by how often the policy
   probes the later up-weighted (mid-yield) arms **before** the change.
2. **The `abnormal_exit` arm has zero novelty yield in every regime**, because the table has no
   FALSE_PASS variant for it. Yet C2 spends about 9.4% of stationary evaluation probes on it
   (v0.9 dev arm shares; 7.8% at C = 0.25). A bonus scaled by the arm's Bernoulli standard deviation
   (UCB1-Tuned / UCB-V idea) shrinks exploration of confidently-near-zero arms. It keeps
   exploration of mid-yield arms, which recovery depends on.
3. **Yield signals are slow.** A Bernoulli CUSUM on the aggregate novelty yield, for a drop from
   ~0.18 to ~0.05, gains only ~0.05–0.1 nats per probe. It therefore needs ~15–30 probes to signal,
   which is longer than C2's ~12-probe recovery. The confirmed detector also rarely fires on these
   shifts: per-arm `violated` gaps are mostly below its 0.35 absolute gap. **Purely reactive
   boosts are expected to lag C2's recovery in `delayed`-type shifts.** A cohort switch
   (`begin_evaluation`) is the only change point that is announced, and B1/B3 treat it as one.
4. **Training-phase exploration is not scored** (only unique evaluation FALSE_PASS counts). A
   high coefficient early in training costs nothing in the metric and improves the boundary
   posterior.

**Predeclared expectation (not a criterion).**

* B2 should beat C2 slightly in stationary and `c_uniform`, while keeping recovery close to C2's.
* B1 should gain more in stationary but lag C2's recovery in `delayed`, `single` and `c_late`.
* B3 should land in between.
* The joint requirement "significantly better than C2 when stationary **and** recovery within
  +1.5 probes of C2" may not be achievable with these signals. If no candidate meets it, none is
  nominated.

## 3. Candidates (eligible for nomination; exactly 3)

All candidates are classes in `caver10/adaptive.py`, built on `AdaptiveCUCB(UCBMeanCAVER)`, and
keep everything else of C2:

* the Beta(s+1, f+1) posterior on `newly_found`;
* no sentinel and no ε;
* the v0.6 confirmed detector (`caver6.confirmation.ConfirmedFamilyDetector`) with local reset;
* unseen arms first (n = 0 → +∞);
* random tie-breaking (identical RNG call order);
* the `available()` rule inherited from `BasePolicy`.

The score is `m_f + coef(f)·√(2 ln max(2,t) / n_f)`. With `ADAPT = False`, `coef(f) = C = 0.5`
and the class reproduces C2 run for run (unit test).

### 3.1 Shared evidence trackers (every candidate maintains them; B2 does not read them)

* `tau` counts learned probes since the last **evidence event**. The run starts with tau = 0.
* An **evidence event** is any of the following, and it sets tau = 0 and resets the CUSUM to 0:
  * (a) `begin_evaluation` (a new case cohort);
  * (b) a confirmed detector alarm (the same alarm that triggers v0.6's local reset);
  * (c) a yield-drop CUSUM alarm.
* **Yield-drop CUSUM** (Page 1954), evaluation probes only:
  * p0 = max(0.02, training novelty yield), where the training yield is the mean `newly_found` over
    the 90 training probes; p0 is capped at 0.95;
  * p1 = ρ·p0;
  * S ← max(0, S + ln(p1/p0)) on a hit (`newly_found`), and S ← max(0, S + ln((1−p1)/(1−p0))) on
    a miss;
  * an alarm fires when S ≥ H.
* **Regime uncertainty** e_t = M / (M + tau), in (0, 1]. It is 1 right after an event.
* **Bernoulli sd factor** v_f = 2·√(m_f (1 − m_f)), in (0, 1]. m_f is the posterior mean.

| shared constant | value |
|---|---|
| `REGIME_M` (M) | 10 |
| `CUSUM_RHO` (ρ) | 0.3 |
| `CUSUM_H` (H) | 2.0 |
| `P0_FLOOR` | 0.02 |
| C2 constant `C` (used only when `ADAPT = False`) | 0.5 |

### 3.2 Candidate definitions

| id | class / name | coefficient | constants | signals used |
|---|---|---|---|---|
| **B1** | `EvidenceUCB` / `C10-EvidenceUCB` | C_t = C_LO + (C_HI − C_LO)·e_t (global, the same for all arms) | C_LO = 0.25, C_HI = 0.75 (+ shared) | change evidence (detector, cohort switch), recent reward distribution (CUSUM) |
| **B2** | `VarUCB` / `C10-VarUCB` | C_f = C_V·v_f (per arm) | C_V = 0.75 | uncertainty (posterior Bernoulli sd); a flat or low-yield landscape gets less exploration |
| **B3** | `HybridUCB` / `C10-HybridUCB` | C_f = v_f·(S_LO + (S_HI − S_LO)·e_t) | S_LO = 0.40, S_HI = 1.10 (+ shared) | all three |

**Why these values (a priori).**

* **B1.** C_LO = 0.25 is the v0.9 M4 point with the best stationary result. C_HI = 0.75 is
  between C2 and the over-exploring C = 1.0. With M = 10, the coefficient falls to C2's 0.5 ten
  probes after an event, and the eval-average is ≈ 0.38 when no further event occurs.
* **B2.** C_V = 0.75 gives about C2's 0.5 to mid-yield arms (m ≈ 0.12–0.14, v ≈ 0.65–0.69). It
  gives ≈ 0.40 to a zero-success arm with n ≈ 11 (m ≈ 0.077, v ≈ 0.53), and ≈ 0.63 to an incumbent with
  m ≈ 0.23.
* **B3.** S_LO/S_HI equal B1's C_LO/C_HI divided by v ≈ 0.67 (a typical mid-yield arm), rounded.
* **CUSUM.** ρ = 0.3 targets a drop to under a third of the training yield. With p0 ≈ 0.17,
  H = 2.0 needs ≈ 15 consecutive misses from S = 0.

Constants are fixed here and are not changed after the dev run.

## 4. Dev protocol and predeclared selection rule

**Data.**

* Salt `v010dev` only, seeds 0–299, the 12 v0.9c scenarios.
* Table `reports/v08/outcome_table_real.json`, train 90 + eval 90.
* Every run goes through `caver9.evaluation.run_one` and `summarize`.
* Schedules come from `caver9c.confirm.build_schedule`. Its `ALLOWED_SALTS` is replaced with
  `{'v010dev'}` inside `caver10/agent_b_dev.py` only.
* At most 2 worker processes.

**Policies.**

* Baselines: Random, UCB1, SW-UCB, D-UCB, CAVER-v0.6 and C2 (`caver9.exploration:UCBMeanCAVER`).
* Candidates: B1–B3.

**Reported.**

* Unique FALSE_PASS, with paired 95% CIs (mean ± 1.96·sd/√n) vs v0.6, C2, UCB1, Random, SW-UCB and
  D-UCB.
* Recovery steps: restricted mean, censoring rate, Kaplan–Meier median, and paired Δ vs v0.6 and C2.
* False-alarm rate, alarm rate, exploration entropy and CPU µs per probe.
* Candidate diagnostics (descriptive): mean evaluation coefficient, and how often the CUSUM and the
  alarm events fire.
* Key regression scenarios: `stationary`, `c_uniform` and `c_reverse`.

**Dev scenario types, used to bind V010_DESIGN §5 to dev.**

| type | dev scenarios |
|---|---|
| stationary-type | `stationary` |
| flat-shift | `c_uniform` |
| abrupt-type (sudden shift at or after the train/eval boundary) | `abrupt`, `delayed`, `early`, `single`, `c_late`, `c_reverse` |
| other non-stationary | `recovery`, `gradual`, `double`, `c_oscillate` |

**Selection rule.** A candidate is **eligible** only if **every** check below holds on dev (Δ =
paired unique-FALSE_PASS difference, 95% CI, n = 300):

| id | scenarios | check |
|---|---|---|
| S1 | stationary, c_uniform | Δ vs CAVER-v0.6: CI lower bound > −0.25 |
| S2 | stationary, c_uniform | Δ vs C2: CI lower bound > 0 |
| K1 | each abrupt-type scenario | Δ vs C2: CI lower bound > −0.3, **and** Δ vs v0.6: CI lower bound > 0 |
| K2 | each abrupt-type scenario | recovery Δ vs v0.6: CI upper bound < 0, **and** recovery Δ vs C2: CI upper bound < +1.5 probes (restricted means) |
| G | all 12 scenarios | Δ vs Random, SW-UCB and D-UCB: CI lower bound > 0, **and** Δ vs v0.6: CI lower bound > −0.5 |
| FA | every scenario with a false-alarm window | candidate false-alarm rate ≤ v0.6's rate + 0.05 |

* **Nomination.**
  * If one or more candidates are eligible, nominate the one with the largest value of
    min(S2 lower bound in stationary, S2 lower bound in c_uniform).
  * Ties are broken by the larger mean of (abrupt Δ vs C2, delayed Δ vs C2).
* **If none is eligible, no candidate is nominated.**
  * The candidate with the fewest failed checks is reported as "closest" for information only,
    not as a nomination.
  * Ties for "closest" are broken by the larger min S2 lower bound.
* The rule is implemented in `caver10/agent_b_dev.py::apply_rule`, and the output is
  `reports/v010/agent_b/dev/selection.json`.
* **RV is not applicable to Agent B**: Agent B makes no real CLI runs.

## 5. Information hygiene and tests

* Policies receive only the arguments listed below. A spy test checks the types.
  * `update(case_id: str, arm: str, violated: bool, newly_found: bool, learn)`
  * `begin_evaluation()`, once
* No class reads case defects, weights, change points, scenario names, or outcomes of probes it
  did not make.
* `tests/test_v010_adaptive.py` checks:
  * that the base and each candidate with `ADAPT = False` reproduce C2;
  * determinism;
  * the formulas and the CUSUM;
  * the `available()` rule;
  * that the dev runner refuses any other salt;
  * the selection rule on synthetic summaries.

---

*Everything below was written after the dev run. Sections 1–5 were committed as predeclared in
commit `15a86ed`, before any dev run. One runner bug was fixed before the dev run: the rule was
skipped for scenario subsets. Constants were not changed.*

## 6. Dev results (salt `v010dev`, seeds 0–299, 12 scenarios, REPLAY)

**Data.**

* Files are in `reports/v010/agent_b/dev/`:
  * `summary.json` and `summary.csv`;
  * `runs.csv`, with 32,400 runs;
  * `selection.json`, `diagnostics.json`;
  * `dev_tables.md`, with every scenario, every policy, Kaplan–Meier medians, and CIs vs all six
    references.
* Reproduce with `python3 -m caver10.agent_b_dev` (about 50 s with 2 workers). A second run
  reproduced all 32,400 runs exactly, apart from CPU time.
* This is a **REPLAY** of the 30 stored real outcomes. Seed CIs do not cover the uncertainty of
  those outcomes.

**Key scenarios.** Unique FALSE_PASS, with paired Δ and 95% CI. Recovery is the restricted mean,
with the censoring rate in brackets.

| scenario | policy | FP | Δ vs v0.6 | Δ vs C2 | recovery (cens.) | Δ rec. vs v0.6 | Δ rec. vs C2 |
|---|---|---|---|---|---|---|---|
| stationary | v0.6 | 11.66 | – | +0.02 [−0.18, +0.22] | – | – | – |
| stationary | C2 | 11.64 | −0.02 [−0.22, +0.18] | – | – | – | – |
| stationary | B1 EvidenceUCB | 11.61 | −0.05 [−0.26, +0.16] | −0.03 [−0.25, +0.19] | – | – | – |
| stationary | B2 VarUCB | 11.93 | +0.27 [+0.10, +0.45] | **+0.29 [+0.09, +0.50]** | – | – | – |
| stationary | B3 HybridUCB | 12.05 | +0.39 [+0.21, +0.57] | **+0.41 [+0.21, +0.61]** | – | – | – |
| c_uniform | v0.6 | 12.15 | – | +0.42 [+0.10, +0.75] | 30.3 (0.13) | – | +4.71 [+2.05, +7.37] |
| c_uniform | C2 | 11.73 | −0.42 [−0.75, −0.10] | – | 25.6 (0.09) | −4.71 [−7.37, −2.05] | – |
| c_uniform | B1 | 11.96 | −0.19 [−0.50, +0.12] | +0.23 [−0.07, +0.53] | 29.3 (0.11) | −0.98 [−3.51, +1.54] | +3.72 [+1.00, +6.45] |
| c_uniform | B2 | 12.43 | +0.28 [−0.03, +0.58] | **+0.70 [+0.39, +1.01]** | 30.8 (0.14) | +0.46 [−2.22, +3.14] | +5.17 [+2.49, +7.84] |
| c_uniform | B3 | 12.56 | +0.40 [+0.10, +0.70] | **+0.83 [+0.50, +1.15]** | 33.0 (0.16) | +2.72 [+0.30, +5.15] | +7.43 [+4.80, +10.06] |
| c_reverse | v0.6 | 9.92 | – | −0.44 [−0.70, −0.19] | 26.2 (0.00) | – | +3.12 [+0.91, +5.34] |
| c_reverse | C2 | 10.37 | +0.44 [+0.19, +0.70] | – | 23.0 (0.00) | −3.12 [−5.34, −0.91] | – |
| c_reverse | B1 | 10.37 | +0.44 [+0.19, +0.70] | +0.00 [−0.25, +0.25] | **18.6** (0.00) | −7.56 [−9.99, −5.13] | **−4.44 [−6.49, −2.38]** |
| c_reverse | B2 | 10.20 | +0.28 [+0.04, +0.52] | −0.16 [−0.42, +0.09] | 30.9 (0.01) | +4.75 [+2.36, +7.14] | +7.88 [+5.57, +10.18] |
| c_reverse | B3 | 10.26 | +0.33 [+0.07, +0.59] | −0.11 [−0.38, +0.16] | 30.3 (0.00) | +4.17 [+1.91, +6.44] | +7.30 [+5.02, +9.57] |
| abrupt | v0.6 | 12.37 | – | −0.93 [−1.23, −0.64] | 16.6 (0.00) | – | +5.87 [+4.32, +7.42] |
| abrupt | C2 | 13.30 | +0.93 [+0.64, +1.23] | – | 10.8 (0.00) | −5.87 [−7.42, −4.32] | – |
| abrupt | B1 | 13.42 | +1.06 [+0.77, +1.35] | +0.12 [−0.13, +0.38] | **10.0** (0.00) | −6.66 [−8.28, −5.04] | −0.79 [−2.04, +0.45] |
| abrupt | B2 | 12.95 | +0.58 [+0.31, +0.85] | −0.35 [−0.63, −0.08] | 16.6 (0.00) | −0.07 [−1.60, +1.47] | +5.80 [+4.36, +7.24] |
| abrupt | B3 | 12.97 | +0.60 [+0.29, +0.92] | −0.33 [−0.63, −0.03] | 15.2 (0.00) | −1.42 [−3.10, +0.26] | +4.45 [+3.00, +5.90] |
| delayed | v0.6 | 12.20 | – | −0.87 [−1.25, −0.50] | 16.0 (0.03) | – | +2.51 [+0.83, +4.18] |
| delayed | C2 | 13.07 | +0.87 [+0.50, +1.25] | – | 13.5 (0.02) | −2.51 [−4.18, −0.83] | – |
| delayed | B1 | 12.88 | +0.68 [+0.30, +1.06] | −0.20 [−0.57, +0.17] | 15.6 (0.03) | −0.41 [−2.06, +1.25] | +2.10 [+0.71, +3.49] |
| delayed | B2 | 12.93 | +0.73 [+0.34, +1.12] | −0.15 [−0.52, +0.23] | 19.4 (0.04) | +3.44 [+1.82, +5.07] | +5.95 [+4.49, +7.41] |
| delayed | B3 | 12.88 | +0.68 [+0.29, +1.07] | −0.19 [−0.58, +0.20] | 19.0 (0.03) | +2.97 [+1.40, +4.54] | +5.47 [+3.94, +7.01] |

**Stationary secondary metrics.**

| policy | false-alarm rate | exploration entropy | CPU µs/probe |
|---|---|---|---|
| CAVER-v0.6 | 0.140 | 0.942 | 9.0 |
| C2 | 0.147 | 0.948 | 8.8 |
| B1 | 0.160 | 0.944 | 10.8 |
| B2 | 0.160 | 0.922 | 11.7 |
| B3 | 0.183 | 0.921 | 12.2 |

* CPU time is noisy, so it is only an order-of-magnitude comparison.
* Every candidate's false-alarm rate stays within v0.6 + 0.05 in every scenario with a
  false-alarm window, so FA passes.

**Candidate diagnostics (descriptive).**

* **Mean evaluation C:** B1 0.41–0.47; B2 0.54–0.58 (on the arms actually selected, which are
  mostly high-mean arms); B3 0.46–0.54.
* **The yield-drop CUSUM fires in 41–47% of `stationary` runs.** That is far more than intended:
  ≈ 15 consecutive misses. It fires in 48–54% of `delayed` runs and 73–80% of `c_reverse` runs,
  so it discriminates only weakly.
* Mean p0 ≈ 0.12 (0.16 in `c_reverse`).

## 7. Predeclared rule: outcome

| candidate | failed checks (of 86) | which |
|---|---|---|
| B1 `C10-EvidenceUCB` | 17 | S1 and S2 in stationary and c_uniform; G vs v0.6 in c_uniform (lower bound −0.50); K1 vs C2 in delayed, early, single and c_late; K1 vs v0.6 in early; K2 vs C2 in delayed, early, single and c_late; K2 vs v0.6 in delayed, single and c_late |
| B2 `C10-VarUCB` | 17 | K1 vs C2 in abrupt, delayed, c_late and c_reverse; K2 (vs v0.6 and vs C2) in all six abrupt-type scenarios; G vs D-UCB in c_reverse |
| B3 `C10-HybridUCB` | 19 | K1 vs C2 in all six abrupt-type scenarios; K2 (vs v0.6 and vs C2) in all six; G vs D-UCB in c_reverse |

**Nomination: none.**

* No candidate meets the predeclared rule.
* The "closest" candidate by the predeclared tie-rule is **B2 `C10-VarUCB`**. It ties B1 at 17
  failures and has the larger min S2 lower bound (+0.09 vs −0.25). This is information only,
  **not a nomination**.

**Failed candidates, stated plainly.**

* **B2 and B3 remove C2's stationary and flat-shift loss.**
  * S1 and S2 pass: stationary +0.29 and +0.41 vs C2; `c_uniform` +0.70 and +0.83 vs C2, with CIs
    above 0.
  * But they **lose C2's adaptation**: recovery is as slow as v0.6 or slower in every abrupt-type
    scenario.
  * They also lose to C2 in abrupt FALSE_PASS (−0.35 and −0.33).
* **B1 keeps or improves C2's adaptation where the shift coincides with the cohort switch.**
  * abrupt: +0.12 vs C2, recovery −0.8.
  * `c_reverse`: recovery −4.4 vs C2, which is significant.
  * But it does **not** fix the stationary or `c_uniform` loss (−0.03 and +0.23 vs C2).
  * It is slower than C2 when the shift comes later: delayed, early, single, c_late.
* **None of the three beats D-UCB clearly in `c_reverse` while also passing S2.**
  * B1 beats D-UCB there (+0.38 [+0.11, +0.65]).
  * B2 and B3 do not: their lower bounds are −0.07 and −0.03.

## 8. Post-hoc ablations (added after the dev run; NOT eligible)

`PH-B1-NoCUSUM` (B1 with H = ∞) and `PH-B1-NoEvalStart` (B1 without the cohort-switch event).
These classes were added to `caver10/adaptive.py` after the dev run. Files are in
`reports/v010/agent_b/posthoc/`. Reproduce with `python3 -m caver10.agent_b_dev --posthoc`.

| scenario | B1: FP Δ vs C2 / recovery | NoCUSUM: FP Δ vs C2 / recovery | NoEvalStart: FP Δ vs C2 / recovery | C2 recovery |
|---|---|---|---|---|
| stationary | −0.03 / – | +0.05 [−0.17, +0.27] / – | +0.16 [−0.03, +0.36] / – | – |
| c_uniform | +0.23 / 29.3 | +0.25 / 30.0 | +0.31 / 30.0 | 25.6 |
| abrupt | +0.12 / 10.0 | −0.02 / 10.2 | −0.19 / 13.9 | 10.8 |
| delayed | −0.20 / 15.6 | −0.43 / 17.3 | +0.22 / 16.0 | 13.5 |
| c_reverse | +0.00 / 18.6 | +0.12 / 20.6 | −0.08 / 25.3 | 23.0 |

**Reading (exploratory).**

* **The cohort-switch event produces B1's abrupt and `c_reverse` recovery advantage.**
  * Without it, abrupt recovery goes from 10.0 to 13.9, and `c_reverse` from 18.6 to 25.3.
  * So that advantage comes from treating the **announced** train/eval boundary as a change
    point, not from detecting the shift.
  * In the final suite, any abrupt-type shift that comes after the boundary gets no such help.
* **The CUSUM costs almost nothing in stationary** (removing it changes FP by +0.08). It helps
  delayed recovery only a little (17.3 → 15.6).
* **No B1 variant beats C2 significantly in stationary.** B1's coefficient is low on average
  (≈ 0.4), but it is front-loaded at the start of evaluation, when probes on fresh cases cost the
  most.

## 9. Findings

1. **The trade-off persists on dev.** None of the evidence signals available to a policy here
   separated "stationary" from "about to shift" quickly enough. The predeclared analysis (§2,
   observation 3) expected this:
   * The policies that explore less (B2, B3) win in stationary and `c_uniform`, but recover like
     v0.6.
   * The policy that explores more after evidence (B1) keeps C2's adaptation only where the
     evidence is the announced boundary.
2. **Variance (Bernoulli-sd) scaling biases the bonus toward the incumbent.** v_f is largest for
   arms with mean near 0.5, which here means the currently best arms (m ≈ 0.23 → v ≈ 0.84, vs
   ≈ 0.5–0.65 for the low-mean arms that become valuable after a shift).
   * In relative terms, it lowers exploration of exactly the arms that recovery depends on.
   * That is why B2 and B3 lose recovery even though their mean coefficient (0.46–0.58) is not much lower
     than C2's.
   * This is an observed mechanism, consistent with the diagnostics, and not tested further.
3. **The yield-drop CUSUM with p0 = training yield fires in ~40% of stationary runs.**
   * The evaluation-phase novelty yield is not stationary within a run, because cases are
     exhausted by repeated visits.
   * A fixed training reference therefore drifts.
   * A phase-matched reference would be needed (not tested).
4. **What would have to change** is a hypothesis, not tested here. A candidate that passes both S2
   and K2 would need a change signal that is faster than ~10 probes and selective, or a cheaper way
   of keeping the mid-yield arms warm than raising C. Neither is available from the aggregate
   novelty stream on this table.

## 10. Caveats

* **Dev only.** Agent B did not see the final scenarios or the extended real table. The dev rule
  binds V010_DESIGN §5 to dev scenarios through Agent B's own typing (§4). The lead's binding for
  the final suite may differ.
* **REPLAY of 30 stored outcomes.** CIs cover schedule and policy randomness only.
* **The cohort-switch event relies on `begin_evaluation`.** That is part of the interface, but it
  favours shifts at the boundary (§8).
* **No novelty claim.** UCB, UCB1-Tuned/UCB-V, Bayes-UCB, CUSUM, change-point restarts and
  decaying schedules are prior art (header of `caver10/adaptive.py`).
* **Tests.** `tests/test_v010_adaptive.py` has 23 tests and runs in under 1 s. The full suite
  (192 tests) passes (`reports/v010/agent_b/test_log.txt`).
