# CAVER v0.9 — Agent C: adaptive exploration

Branch `v09/agent-c`, from `research/caver-v09` @ 2b673e4. Design: `docs/V09_EXPERIMENT_DESIGN.md`.

**Status of this document.** Sections 1–4 were written and committed **before the first dev run**.
They hold the analysis, the predeclared candidates and all constants. Results (section 5 onward)
were added after the dev run. Anything not predeclared here is labelled **post-hoc exploratory**.

Prior art: UCB bonuses (Auer et al. 2002), ε-greedy and adaptive-ε variants, recency and
staleness exploration bonuses, and periodic forced exploration are all known methods. **Agent C
makes no novelty claim.**

## 1. Hypothesis

"CAVER keeps choosing families with a high past success rate and does not explore enough the
other families that have newly become risky." Target: close the post-shift gap to UCB1
(abrupt and delayed) without losing v0.6's stationary advantage.

## 2. Analysis of CAVER v0.6 exploration (analytic, pre-dev)

### 2.1 What v0.6 does

* **Reward:** `newly_found` (a new unique FALSE_PASS on a fresh (case, arm)). The posterior is
  Beta(s+1, f+1) per arm, accumulated over the 90 training probes and carried into
  evaluation without discounting.
* **Score:** `mean + 0.85·sd(Beta) + 0.16/√(n+1)`. Both bonus terms shrink like 1/√n, and
  there is **no time term**. An arm that is not chosen keeps exactly the same score forever.
* **ε:** in evaluation only. 0.03 normally, or 0.18 for 36 learned steps after an alarm. That is
  about 2.6 expected random probes in 90 evaluation steps when no alarm fires.
* **Sentinel:** every 7th evaluation step goes to the available arm least sampled *in
  evaluation*. That is 12 of 90 probes, about 2 per arm. The sentinel does not look at risk, so
  about 1/6 of sentinels go to `abnormal_exit` (leading_space arm), which has 0 FALSE_PASS
  variants in the real table.
* **Detector (confirmed, local reset):** it watches `violated` per family and needs ≥ 4 + 4
  disjoint evaluation observations of a family before an alarm. Families that v0.6 rarely
  samples therefore cannot raise alarms (a blind spot). The families most likely to alarm
  are the heavily sampled incumbents whose rate *dropped*. A local reset sets that arm to n = 0,
  which makes its posterior optimistic (mean 0.5) and pulls probes **back** to the arm that just
  went cold. This is a structural side effect, recorded as an observation and not tested
  separately here.

### 2.2 Magnitudes on the real table

Expected FALSE_PASS yield of one fresh probe (P(defect in family) × FP-variant fraction, from
the generator weights and `reports/v08/outcome_table_real.json`; no dev data used):

| arm (family) | base | shifted |
|---|---|---|
| canonical (schema) | 0.231 | 0.032 |
| case_shift (field_value) | 0.179 | 0.047 |
| leading_space (abnormal_exit) | 0.000 | 0.000 |
| tool_alias (timeout) | 0.062 | 0.092 |
| nested_wrapper (matcher) | 0.078 | 0.208 |
| extra_metadata (exec_mismatch) | 0.063 | 0.328 |

v0.6 score terms (mean, 0.85·sd, coverage) for typical boundary states:

| state (s/n) | mean | 0.85·sd | coverage | total | UCB c=0.5 bonus at t=90 / 180 |
|---|---|---|---|---|---|
| incumbent 10/40 | 0.262 | 0.057 | 0.025 | 0.344 | 0.237 / 0.255 |
| neglected 0/5 | 0.143 | 0.105 | 0.065 | 0.313 | 0.671 / 0.721 |
| neglected 0/15 | 0.059 | 0.047 | 0.040 | 0.146 | 0.387 / 0.416 |
| 2/10 | 0.250 | 0.102 | 0.048 | 0.400 | 0.474 / 0.510 |

Consequences:

1. **The neglected arm never catches up on its own.** An arm abandoned at 0/15 scores 0.146,
   and nothing in the score grows while it is not chosen. Only the sentinel (about 2 probes) and
   ε (about 0.4 probes per arm) revisit it. After a shift toward `exec_mismatch` and `matcher`
   (yield 0.33 and 0.21), v0.6 needs a sentinel or ε probe to land there **and** hit, before
   the posterior moves.
2. **The incumbent is slow to fall.** An incumbent at 10/40 (score 0.344) that now yields
   about 0.03 needs about 14 more failures before its mean (11/(42+k)) drops below 0.2. Per-case
   exhaustion (`available()`) softens this, because each case gets about 3 probes and the
   incumbent can only take one of them.
3. **UCB1 contrast.** UCB1 learns `violated` (a denser signal that includes contract
   violations) with bonus √(2 ln t / n) ≈ 0.4–1.4, larger than any mean gap. Allocation is
   close to balanced with a tilt, so after a shift the up-weighted families are already being
   sampled. This explains its faster recovery (about 9 probes) and its stationary loss.

**Design implication.** The gap is a missing *time/recency* term on rarely chosen arms. Remedies
that rescale the bonus by recency or by time, or that raise ε when the yield drops, address
the hypothesis directly. Discounting the *reward* posterior is Agent A's topic and is
deliberately not used here.

## 3. Predeclared candidates (eligible for nomination; ≤ 3)

All candidates are new classes in `caver9/exploration.py`, built on `ExploreCAVER`. This class
reproduces CAVER-v0.6 **exactly** in its default configuration (same RNG call order). A unit
test checks identical `Run` records vs `caver6.CAVERv06`. Every candidate keeps v0.6's novelty
posterior, confirmed detector and local reset. Bonus terms apply in train and evaluation.
ε and the sentinel apply in evaluation only, as in v0.6. Trackers use only the policy's own
probes: `t` = learned probes so far, `last_t[f]`, and an EWMA of selection indicators.

| id | class / name | change vs v0.6 | constants |
|---|---|---|---|
| **C1** | `RecencyCAVER` / `C9-Recency` | score += 0.12·max(0, 1 − 6·r_f) + 0.08·min(1, g_f/30). Here r_f is the EWMA share of recent probes (decay 0.9, init 1/6), and g_f = t − last_t[f] is the number of probes since f was last chosen. Sentinel and ε unchanged. | FREQ_WEIGHT 0.12, FREQ_DECAY 0.9, STALE_WEIGHT 0.08, STALE_HORIZON 30 |
| **C2** | `UCBMeanCAVER` / `C9-UCBMean` | score = posterior mean + c·√(2 ln max(2,t) / n_f), with n_f = 0 → +∞. This **replaces** the Beta-sd + coverage bonus, the sentinel and ε. Detector and local reset kept. | C = 0.5 |
| **C3** | `AdaptiveEpsCAVER` / `C9-AdaptEps` | evaluation ε = max(0.18 if post-alarm, 0.03 + 0.22·drop), where drop = clip(1 − ȳ_recent/ȳ_train, 0, 1). ȳ_train is the mean `newly_found` over training probes, and ȳ_recent is an EWMA (decay 0.95) of `newly_found` over evaluation probes, initialised at ȳ_train. Random arm is uniform over available arms. Score and sentinel unchanged. | EPS_MIN 0.03, EPS_MAX 0.25, YIELD_DECAY 0.95 |

Why c = 0.5 for C2: it is a midpoint, chosen a priori. c = 1 is the literal UCB1 constant, and
with means ≤ 0.35 it would allocate almost uniformly. The c = 0.25 and c = 1.0 runs (M4/M5
below) are run to show the sensitivity, and **neither may be nominated**.

## 4. Mechanism-comparison arms (predeclared, NOT eligible for nomination)

These arms implement the requested comparison of exploration mechanisms (frequency vs
staleness, fixed vs adaptive ε, UCB constant). Their constants are fixed here, before dev.

| id | name | definition |
|---|---|---|
| M1 | `M-FreqOnly` | v0.6 + 0.12·max(0, 1 − 6·r_f) (C1 without staleness) |
| M2 | `M-StaleOnly` | v0.6 + 0.08·min(1, g_f/30) (C1 without frequency) |
| M3 | `M-FixEps0.10` | v0.6 with fixed evaluation ε = 0.10 (no post-alarm boost) |
| M4 | `M-UCBMean-c0.25` | C2 with c = 0.25 |
| M5 | `M-UCBMean-c1.0` | C2 with c = 1.0 (RESEARCH_NOTES §7 H2, literal) |

Baselines: Random, Uniform (`caver8.benchmark.Uniform`), UCB1, CAVER-v0.3, CAVER-v0.6.

### 4.1 Dev protocol and nomination rule (predeclared)

* Salt `v09dev`, seeds 0–199, scenarios stationary/abrupt/delayed/recovery, real table,
  train 90 + eval 90 via `caver8.benchmark.schedules` / `run_policy`, at most 2 processes.
  Script: `caver9/agent_c_dev.py`. Output: `reports/v09/agent_c/`.
* Metrics (§5): unique FALSE_PASS, unique defects, FP recall, first find, recovery steps
  (censored at the cap: abrupt 91, delayed 46, recovery 61), exploration diversity
  (normalised entropy of the 90 eval arm choices), stationary loss (paired Δ vs v0.6), CPU
  µs per select+update. Also post-change unique FALSE_PASS, and ε/sentinel shares.
  Paired 95% CIs (normal approximation) vs CAVER-v0.6 and vs UCB1.
* **Nomination:** a candidate (C1–C3) is nominated only if it meets **all** §7 criteria on dev
  (stationary Δ vs v0.6 CI lower bound > −0.5; abrupt and delayed Δ vs v0.6 CI > 0 and Δ vs
  UCB1 CI lower bound > −0.5; abrupt and delayed recovery Δ vs v0.6 CI < 0; recovery-scenario
  Δ vs v0.6 CI lower bound > −0.5). If several qualify, the one with the larger mean of
  (abrupt Δ + delayed Δ vs v0.6) is chosen. If none qualifies, **no primary is nominated**.
  The closest candidate is then reported as a partial result only.
* "Does more exploration hurt stationary?" is answered with (a) each candidate's paired
  stationary Δ vs v0.6 and (b) a descriptive across-policy relation between eval diversity
  and stationary FALSE_PASS.
* Constants above are not changed after seeing dev.

Predeclared expectation (not a criterion): C2 should recover fastest and gain most under
shift, but risks stationary loss. C1 and C3 should keep stationary performance and gain less.
