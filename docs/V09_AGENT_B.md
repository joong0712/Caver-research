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
