# CAVER v0.9 — Agent B: dual reward (pre-registration, then results)

Branch `v09/agent-b`. This section was written and committed **before the first dev run**.
Constants are not changed after dev. Anything added later is labelled *post-hoc exploratory*.

## 1. Hypothesis

> Learning the change in the recent contract-violation rate together with new-FALSE_PASS
> discovery adapts faster to shifts than learning new-FALSE_PASS discovery alone.

Background: CAVER (v0.3–v0.6) learns only from `newly_found` (new unique FALSE_PASS). UCB1
learns from `violated`. The v0.8 comparison was therefore not reward-matched. v0.8 hypothesis B
(severity-weighted reward + decayed risk *mean*, added on top of v0.6) was rejected. This study
differs from it in three ways. The two signals are kept as **separate models**. The violation
model is **time-discounted for all arms on every step**, so the uncertainty of a neglected arm
grows back and drives re-exploration. Reward-matched UCB1 baselines are added.

## 2. Models (`caver9/dual_reward.py`)

* **(i) `DiscoveryModel`:** per-arm Beta(1 + s, 1 + f) of P(probe yields a new unique
  FALSE_PASS), updated from `newly_found`. Not discounted (γ_d = 1.0).
* **(ii) `RecentViolationModel`:** per-arm Beta(1 + s, 1 + f) of the per-probe violation rate,
  updated from `violated`. Before each observation, **all** arms' (s, f) are multiplied by
  γ_v = 0.97, which gives an effective memory of about 33 probes.
* **(iii) Combination:** score(arm) = W_DISC · g(discovery) + W_VIOL · g(violation).

## 3. Constants (all fixed now)

| constant | value | note |
|---|---|---|
| W_DISC / W_VIOL | **0.6 / 0.4** | **starting values, not validated optima** |
| γ_d (discovery discount) | 1.0 | none |
| γ_v (violation discount) | 0.97 | per learning step, all arms; memory ≈ 1/(1−γ) ≈ 33 ≈ EVAL_BUDGET/3 |
| Beta priors | (1, 1) | both models |
| optimistic score g | mean + 0.85·sd + 0.16/√(n_eff+1) | bonus constants copied from `caver5.BayesianPolicy` |
| B3 v0.6 components | unchanged | ConfirmedFamilyDetector defaults, local reset, sentinel period 7, ε 0.18/0.03, 36 post-change steps |
| UCB1-Combined reward | 0.6·newly_found + 0.4·violated | |

## 4. Predeclared main candidates (3)

| id | class | name | selection |
|---|---|---|---|
| B1 | `DualRewardTS` | `B-DR-TS` | Thompson: draw θ_d, θ_v per available arm; argmax 0.6·θ_d + 0.4·θ_v |
| B2 | `DualRewardBayes` | `B-DR-Bayes` | deterministic: argmax 0.6·g_d + 0.4·g_v (random tie order) |
| B3 | `DualRewardV06` | `B-DR-v06` | CAVER-v0.6 unchanged, except greedy score = 0.6·(v0.6 novelty score) + 0.4·g_v |

**Extra classes (not candidates):**

* Ablations: `B-DR-TS[disc]` (1/0), `B-DR-TS[viol]` (0/1), and `B-DR-TS[recent-disc]` (1/0 with
  the discovery model discounted at γ = 0.97, which separates recency from reward type);
  `B-DR-Bayes[disc]` and `B-DR-Bayes[viol]`; `B-DR-v06[disc]` (must equal CAVER-v0.6 run for
  run, a sanity check) and `B-DR-v06[viol]`.
* Fair UCB1: `B-UCB1-NewFP` (UCB1 on `newly_found`, the same reward as CAVER) and
  `B-UCB1-Combined` (UCB1 on 0.6·newly_found + 0.4·violated). The standard `UCB1` (violation
  reward) stays the baseline.
* Baselines: Random, UCB1, CAVER-v0.3, CAVER-v0.6.

All policies use the `caver5.BasePolicy` exhaustion rule and receive only
`update(str, str, bool, bool)` and `observe_outcome(bool, bool, bool)`. `observe_outcome` is
recorded for diagnostics and is not used for selection.

## 5. Dev protocol

Salt `v09dev`, seeds 0–199, scenarios stationary/abrupt/delayed/recovery, real table
`reports/v08/outcome_table_real.json`, train 90 + eval 90 via `caver8.benchmark.run_policy`,
2 worker processes. Metrics follow design §5. Statistics are paired 95% CIs (normal
approximation) on matched seeds vs CAVER-v0.6 and vs UCB1. Recovery steps are censored at the
cap, as in `caver8.benchmark.summarize` (abrupt 91, delayed 46, recovery 61).

## 6. Nomination rule (fixed now)

A candidate **passes dev** when all of design §7 hold on dev:
(1) stationary Δ vs v0.6, CI lower bound > −0.5;
(2) abrupt and delayed: Δ vs v0.6 CI above 0 **and** Δ vs UCB1 CI lower bound > −0.5;
(3) abrupt and delayed: Δ recovery steps vs v0.6 CI below 0;
(4) recovery scenario: Δ vs v0.6 CI lower bound > −0.5.

Among passing candidates (B1–B3 only), the primary is the one with the largest mean of
(abrupt Δ vs v0.6, delayed Δ vs v0.6). If none passes, **no primary is nominated** and the best
partial result is reported as a negative result.

**Hypothesis support.** The hypothesis counts as supported on dev for a candidate family only if
the combined variant beats its own discovery-only ablation in abrupt and delayed (paired CI
above 0) and recovers faster (paired recovery-step CI below 0).

## 7. Known confounds, stated in advance

* In this table, a violation without FALSE_PASS occurs only for 4 of the 24 defect variants.
  Within evaluation a (case, arm) pair is rarely repeated, so `violated` and `newly_found` are
  strongly correlated. The reward-matching effect is therefore expected to be small, and most
  differences should come from recency and exploration.
* The recovery metric counts any new defect (FALSE_PASS or not) in an up-weighted family. A
  violation-learning policy is aligned with that metric.

---

# Dev results (written after the dev run; constants unchanged)

Run: `python3 -m caver9.agent_b_dev --jobs 2` → `reports/v09/agent_b/` (`summary.json`,
`summary.csv`, `runs.csv`, `table.md`). Salt `v09dev`, seeds 0–199, 4 scenarios, real table,
16 policies, 25 s wall time. Re-running gives identical runs (only CPU timings differ).
Instrumentation was checked to be behaviour-neutral, and `B-DR-v06[disc]` reproduces CAVER-v0.6
run for run, as predicted.

## Main table (unique FALSE_PASS, Δ = paired mean [95% CI])

| policy | stat | abrupt | delayed | recovery | Δv0.6 stat | Δv0.6 abrupt | Δv0.6 delayed | ΔUCB1 stat | ΔUCB1 abrupt | ΔUCB1 delayed | rec. steps abr / del |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Random | 9.16 | 10.47 | 9.98 | 9.48 | −2.51 [−2.88, −2.15] | −1.72 [−2.12, −1.32] | −2.35 [−2.88, −1.83] | −1.80 [−2.17, −1.43] | −2.29 [−2.72, −1.86] | −3.01 [−3.59, −2.43] | 8.1 / 7.9 |
| UCB1 (violation) | 10.96 | 12.76 | 12.99 | 12.29 | −0.71 [−1.00, −0.42] | +0.57 [+0.21, +0.93] | +0.66 [+0.10, +1.21] | – | – | – | 10.6 / 10.0 |
| CAVER-v0.3 | 12.05 | 11.94 | 11.88 | 12.41 | +0.38 [+0.11, +0.64] | −0.26 [−0.62, +0.11] | −0.45 [−0.90, −0.00] | +1.08 [+0.81, +1.36] | −0.82 [−1.20, −0.45] | −1.10 [−1.64, −0.57] | 23.0 / 25.4 |
| CAVER-v0.6 | 11.68 | 12.19 | 12.34 | 12.10 | – | – | – | +0.71 [+0.42, +1.00] | −0.57 [−0.93, −0.21] | −0.66 [−1.21, −0.10] | 16.9 / 17.5 |
| B-UCB1-NewFP | 11.11 | 12.99 | 13.27 | 12.31 | −0.56 [−0.86, −0.27] | +0.81 [+0.45, +1.16] | +0.94 [+0.39, +1.48] | +0.14 [−0.13, +0.42] | +0.23 [−0.08, +0.55] | +0.28 [−0.19, +0.75] | 9.2 / 9.3 |
| B-UCB1-Combined | 11.19 | 12.92 | 13.37 | 12.11 | −0.49 [−0.75, −0.23] | +0.73 [+0.38, +1.08] | +1.03 [+0.50, +1.57] | +0.22 [−0.06, +0.50] | +0.16 [−0.17, +0.49] | +0.38 [−0.10, +0.86] | 9.0 / 10.1 |
| **B1 B-DR-TS** | 11.28 | 12.52 | 12.75 | 11.64 | −0.40 [−0.67, −0.13] | +0.33 [+0.00, +0.66] | +0.41 [−0.07, +0.90] | +0.31 [+0.04, +0.58] | −0.24 [−0.62, +0.14] | −0.24 [−0.75, +0.27] | 12.6 / 12.7 |
| **B2 B-DR-Bayes** | 11.81 | 13.22 | 13.77 | 13.06 | +0.14 [−0.14, +0.41] | +1.03 [+0.67, +1.40] | +1.44 [+0.98, +1.89] | +0.84 [+0.55, +1.14] | +0.47 [+0.12, +0.81] | +0.78 [+0.29, +1.27] | 14.4 / 15.1 |
| **B3 B-DR-v06** | 11.41 | 12.71 | 13.37 | 12.40 | −0.26 [−0.50, −0.02] | +0.53 [+0.20, +0.85] | +1.03 [+0.59, +1.47] | +0.45 [+0.17, +0.73] | −0.04 [−0.40, +0.31] | +0.38 [−0.13, +0.88] | 13.7 / 14.4 |
| B-DR-TS[disc] | 11.48 | 11.77 | 12.11 | 11.94 | −0.20 [−0.47, +0.08] | −0.42 [−0.82, −0.02] | −0.23 [−0.69, +0.23] | +0.52 [+0.21, +0.82] | −0.99 [−1.40, −0.58] | −0.89 [−1.42, −0.35] | 13.3 / 15.2 |
| B-DR-TS[viol] | 10.49 | 11.66 | 11.92 | 11.09 | −1.18 [−1.49, −0.87] | −0.53 [−0.89, −0.16] | −0.41 [−0.94, +0.11] | −0.47 [−0.78, −0.16] | −1.09 [−1.48, −0.71] | −1.07 [−1.59, −0.55] | 10.3 / 10.7 |
| B-DR-TS[recent-disc] | 10.40 | 12.37 | 11.77 | 11.26 | −1.27 [−1.58, −0.97] | +0.18 [−0.23, +0.59] | −0.56 [−1.09, −0.04] | −0.56 [−0.88, −0.25] | −0.39 [−0.78, −0.00] | −1.22 [−1.73, −0.71] | 9.5 / 9.5 |
| B-DR-Bayes[disc] | 12.22 | 12.25 | 12.62 | 12.80 | +0.55 [+0.32, +0.78] | +0.06 [−0.31, +0.43] | +0.28 [−0.18, +0.75] | +1.26 [+0.98, +1.54] | −0.51 [−0.91, −0.11] | −0.37 [−0.95, +0.21] | 21.9 / 22.7 |
| B-DR-Bayes[viol] | 11.11 | 13.19 | 13.56 | 12.38 | −0.56 [−0.85, −0.28] | +1.00 [+0.64, +1.36] | +1.23 [+0.72, +1.73] | +0.14 [−0.14, +0.43] | +0.43 [+0.09, +0.77] | +0.57 [+0.04, +1.10] | 11.6 / 9.9 |
| B-DR-v06[disc] (= v0.6) | 11.68 | 12.19 | 12.34 | 12.10 | 0 | 0 | 0 | +0.71 | −0.57 | −0.66 | 16.9 / 17.5 |
| B-DR-v06[viol] | 10.71 | 12.95 | 12.93 | 11.89 | −0.96 [−1.24, −0.68] | +0.76 [+0.39, +1.12] | +0.59 [+0.16, +1.02] | −0.25 [−0.56, +0.06] | +0.18 [−0.18, +0.55] | −0.07 [−0.56, +0.43] | 10.4 / 10.0 |

Recovery steps are censored at the cap (abrupt 91, delayed 46). Censoring rate is ≤ 2% for all
candidates (v0.6: 0% abrupt, 4% delayed).

**Recovery-step Δ (paired).**

| candidate | vs v0.6, abrupt | vs v0.6, delayed | vs UCB1, abrupt | vs UCB1, delayed |
|---|---|---|---|---|
| B1 | −4.29 [−6.30, −2.27] | −4.83 [−6.84, −2.83] | +2.02 [+0.43, +3.61] | +2.74 [+1.02, +4.46] |
| B2 | −2.42 [−4.17, −0.68] | −2.39 [−4.33, −0.45] | +3.88 [+2.23, +5.53] | +5.19 [+3.45, +6.92] |
| B3 | −3.21 [−4.84, −1.58] | −3.09 [−5.09, −1.09] | +3.10 [+1.49, +4.70] | +4.49 [+2.80, +6.17] |

**`recovery` scenario Δ vs v0.6 (unique FALSE_PASS).** B1 −0.46 [−0.95, +0.03]; B2 +0.97
[+0.49, +1.44]; B3 +0.30 [−0.12, +0.72].

**Other §5 metrics** (full values in `summary.json`):

| metric | B2 | B3 | B1 | v0.6 | UCB1 |
|---|---|---|---|---|---|
| FP recall, stationary | 0.698 | 0.677 | 0.666 | 0.693 | 0.645 |
| FP recall, abrupt | 0.684 | 0.661 | 0.647 | 0.632 | 0.659 |
| first find, stationary | 5.0 | 5.0 | 5.7 | 5.1 | 6.2 |
| first find, abrupt | 10.6 | 10.4 | 9.4 | 11.9 | 8.5 |
| eval entropy, stationary | 0.937 | 0.954 | 0.958 | 0.940 | 0.966 |
| eval entropy, abrupt | 0.942 | 0.962 | 0.964 | 0.951 | 0.966 |
| CPU µs per probe (select + observe + update) | 18.6 | 18.8 | 28.3 | 12.4 | 8.4 |

There is no change detector in B1/B2, so no false-alarm rate. B3 keeps v0.6's detector.

## §7 criteria on dev

| criterion | B1 DR-TS | B2 DR-Bayes | B3 DR-v06 |
|---|---|---|---|
| (1) stationary Δv0.6 lower bound > −0.5 | **✗** (−0.67) | ✓ (−0.14) | **✗** (−0.503) |
| (2) abrupt Δv0.6 > 0 | ✓ (+0.00) | ✓ | ✓ |
| (2) delayed Δv0.6 > 0 | ✗ | ✓ | ✓ |
| (2) abrupt ΔUCB1 lower bound > −0.5 | ✗ (−0.62) | ✓ | ✓ |
| (2) delayed ΔUCB1 lower bound > −0.5 | ✗ (−0.75) | ✓ | ✓ |
| (3) recovery steps vs v0.6 below 0, abrupt and delayed | ✓ | ✓ | ✓ |
| (4) `recovery` scenario Δv0.6 lower bound > −0.5 | ✗ (−0.95) | ✓ | ✓ |
| **all** | ✗ | **✓** | ✗ (misses (1) by 0.003) |
| hypothesis vs own discovery-only ablation | partial (FP ✓; abrupt recovery CI includes 0) | ✓ | ✓ |

## Nomination

**Primary: B2 `B-DR-Bayes`** (`caver9.dual_reward.DualRewardBayes`). It is the only candidate
that meets every §7 criterion on dev, following the pre-registered rule. Dev does not decide
adoption; the lead's final holdout does.

## Findings and failures (honest record)

1. **Reward matching explains little.** UCB1 on the CAVER reward (`B-UCB1-NewFP`) and on the
   combined reward are within ±0.4 of standard UCB1, with every CI including 0. Their
   stationary deficit vs v0.6 remains (−0.56 and −0.49). As predicted in §7, the v0.8 reward
   asymmetry is not the main cause of the shift gap.
2. **The dual-reward hypothesis is supported on dev for B2 and B3.** Against their own
   discovery-only ablations, the combined policies find more FALSE_PASS under shift (B2: abrupt
   +0.98 [+0.61, +1.34], delayed +1.15 [+0.66, +1.64]) and recover faster (B2: −7.5 steps in both
   scenarios). The combination costs some stationary performance (B2 vs B2[disc] −0.42
   [−0.68, −0.15]). Compared with v0.6, that cost is not significant.
3. **Recency belongs on the violation signal, not on the discovery signal.**
   `B-DR-TS[recent-disc]` (discounted discovery only) loses 1.27 FALSE_PASS in stationary.
   Violation-only variants recover about as fast as UCB1 but lose 0.6–1.2 in stationary. Only
   the combination with an undiscounted discovery model keeps stationary performance.
4. **B1 (Thompson) failed.** Combining helped B1 vs its ablation on FP, but TS is weaker overall
   and fails (1), (2) and (4).
5. **B3 failed criterion (1) by a hair** (lower bound −0.503 vs −0.5). Per the rule it is not
   nominated.
6. **Recovery is still slower than UCB1.** Even B2 needs about 4–5 more probes than UCB1 after a
   shift (CI above 0). It recovers faster than v0.6, but does not reach UCB1's recovery speed. Its
   advantage over UCB1 comes from total discovery, not speed.
7. **Caveats.** These are table replays (30 outcomes, n = 1 per config). Dev seeds only, and
   one candidate selected out of three, so the dev CIs are optimistic for the selected
   candidate. The weights 0.6/0.4 and γ_v = 0.97 are untuned starting values. The recovery
   metric counts any new violation, which favours violation-learning policies. CPU cost is about
   1.5× v0.6 and about 2.2× UCB1.
