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
