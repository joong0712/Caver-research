# CAVER v0.9 — Agent A: temporal adaptation (recency weighting)

Branch `v09/agent-a`, from `research/caver-v09` @ 2b673e4. Design: `docs/V09_EXPERIMENT_DESIGN.md`.

**Hypothesis (given):** CAVER's slow adaptation is caused by old observations having too much
influence on the selection score.

Sections 1–3 were written and committed **before the first dev run**. Results are appended
below them in later commits. Nothing in sections 2–3 is changed after dev results are seen.

## 1. Static analysis of v0.6's posterior and reset logic (pre-run, code reading only)

Code path: `caver6.policies.CAVERv06` → `ControlledChangeGuard` → `caver5.advanced_policies.ChangeGuard`
→ `caver5.policies.BayesianPolicy(novelty=True, robust=False)`.

**Score.** For each available arm f: `mean + 0.85·sd + 0.16/√(n_f+1)`, with
Beta(s_f+1, f_f+1) mean and sd, where s_f = number of rewarded probes (reward = new unique
FALSE_PASS) and f_f = unrewarded probes, n_f = probe count. `robust=False`, so **γ = 1**: no
discounting anywhere. Every observation since the first training probe has equal weight.

**Train → eval boundary.** `begin_evaluation` only resets the detector and the eval counters.
The 90 training observations stay in the posterior at full weight. In training there is no
ε and no sentinel, so the training posterior is purely greedy-driven. The arms that looked best
under W_BASE accumulate many observations, while low-weight arms are left with few.

**Consequences for the score (qualitative).**

1. *Inertia of the dominant arm.* For an arm with n observations, one new failure moves the
   Beta mean by about mean/(n+2). An arm with dozens of training observations needs many eval
   failures before its mean falls below a neglected arm's. Under a shift, the dominant train arm
   is exactly the one that becomes poor, so this inertia sits on the critical path.
2. *Bonus shrinks with n only, never with time.* Both the Beta-sd term and the coverage term
   decrease in n_f. Neither grows with elapsed time, unlike UCB1's √(2 ln t / n). A neglected
   arm's score is frozen at whatever its few training samples said until it is sampled again.
   Sampling comes only from the sentinel (every 7th eval step, least-eval-counted family) or ε
   (0.03, i.e. about 3 eval probes in 90).
3. *Reset is local, alarm-gated and fires at most once per family.* `ConfirmedFamilyDetector`
   needs ≥ 6 training samples of that family (low-weight arms may never reach this), then two
   disjoint batches of 4 eval samples, both with |gap| ≥ 0.35 and z ≥ 1.6 in the same direction.
   An alarmed family is never tested again. Only the alarmed family's posterior is zeroed. All
   other families keep their full training history.
4. *Direction-blind reset.* The local reset is applied whether the alarmed family went **up** or
   **down**. Zeroing a family whose rate *fell* moves it back to the Beta(1,1) prior (mean 0.5,
   maximal sd), which makes it **more** attractive. That is the opposite of the intended
   adaptation. Down-shifts are also the alarms the policy can most easily raise, because it
   samples the formerly dominant arm a lot.
5. *Novelty reward is itself nonstationary.* Within one eval period each (case, family) pair can
   be rewarded only once, and `seen` is cleared at the boundary. So even in `stationary` the
   per-arm reward rate decays over the 90 eval probes. Equal weighting of old observations is
   therefore never exactly right, even without a shift.
6. The `available()` exhaustion rule forces some diversity on repeated case draws, independent of
   the score. That partly masks (1)–(2).

These are hypotheses about mechanism. Section 5 measures some of them on dev for v0.6. That
measurement is made after the candidates below are frozen and does not change them.

## 2. Predeclared candidates (frozen; ≤ 3)

All three are **CAVER-v0.6 + exactly one change**. They are implemented in `caver9/temporal.py`
as `TemporalV06Base` subclasses. `TemporalV06Base` with defaults is checked by a unit test to
reproduce CAVER-v0.6 run-for-run.

| id | class / name | change vs v0.6 | constants |
|---|---|---|---|
| **A1** | `DecayGM` / `A1-Decay.981` | **continuous decay**: before adding each learning observation (train and eval alike), multiply s_f, f_f and n_f of **all** families by γ | γ = 1 − ¼·√(Υ/T) with Υ = 1 breakpoint, T = 180 probes → **γ = 0.981366** (Garivier & Moulines' suggested D-UCB discount; effective memory ≈ 54 probes) |
| **A2** | `DecayFast` / `A2-Decay.95` | same as A1, faster | **γ = 0.95** (effective memory 20 probes, about the v0.6 post-alarm window scale) |
| **A3** | `AlarmShrink` / `A3-AlarmShrink.2` | **decay triggered by change detection**: on every v0.6 detector alarm, in addition to v0.6's local zero-reset and ε window, multiply s_f, f_f and n_f of **all** families once by τ | **τ = 0.2** (same factor as v0.8's Temper; ≈ 40 training observations → 8, the size of the detector's two confirmation batches) |

Unchanged in all three: prior Beta(1,1), uncertainty weight 0.85, coverage weight 0.16, sentinel
period 7, ε 0.03 / 0.18 for 36 steps after an alarm, `ConfirmedFamilyDetector(min_train=6,
batch_size=4, absolute_gap=0.35, z_threshold=1.6)`, local reset, novelty reward.

Rationale: A1 vs A2 is a dose–response check on the decay rate (if the hypothesis holds, more
forgetting should give faster recovery, at some stationary cost). A1/A2 vs A3 compares continuous
with detection-triggered decay. Prior art: discounted and sliding-window bandits (Garivier &
Moulines 2011), discounted Thompson sampling, and restart-on-detection schemes. **No novelty is
claimed.**

### Comparison classes (not candidates)

| name | source | constants |
|---|---|---|
| Random | `caver5.policies.RandomPolicy` | – |
| UCB1 | `caver5.policies.UCB1Policy` | reward = violated |
| SW-UCB | `caver5.policies.SlidingWindowUCB` | window 35 (existing), reward = violated |
| D-UCB | `caver9.temporal.DiscountedUCB` (Garivier & Moulines 2011) | γ = 0.981366, ξ = 0.6, B = 1, reward = violated, index S/N + 2B√(ξ ln max(2, n_γ) / N) |
| CAVER-v0.3 | `caver5.policies.CAVERv03` | – |
| CAVER-v0.6 | `caver6.policies.CAVERv06` | – |

## 3. Protocol and predeclared nomination rule

* Dev only: salt `v09dev`, seeds 0–199, scenarios stationary / abrupt / delayed / recovery, real
  table `reports/v08/outcome_table_real.json`, train 90 + eval 90 via
  `caver8.benchmark.schedules` / `run_policy`. At most 2 worker processes. The script
  (`caver9/agent_a_dev.py`) refuses every other salt.
* Unit tests use a mechanics-only salt (`v09a-unittest`) for equivalence and hygiene checks. No
  performance numbers are read from it.
* A transparent wrapper records eval arm choices (entropy) and CPU time of select + update. It
  does not touch the policy's RNG or inputs.
* Metrics (§5 of the design): unique FALSE_PASS, unique defects, FP recall, first find, recovery
  steps (censored at the cap used by `caver8.benchmark.summarize`), false-alarm rate, exploration
  diversity (normalised entropy of the 90 eval arm choices), stationary loss vs v0.6, and CPU µs
  per select + update. Paired 95% CIs on matched seeds (normal approximation, n = 200).
* **Nomination rule (fixed now).** A candidate *passes dev* if, on dev, it meets all of §7:
  (1) stationary Δ vs v0.6 CI lower bound > −0.5;
  (2) abrupt and delayed Δ vs v0.6 CI lower bound > 0 **and** Δ vs UCB1 CI lower bound > −0.5;
  (3) abrupt and delayed Δ recovery steps vs v0.6 CI upper bound < 0;
  (4) recovery-scenario Δ vs v0.6 CI lower bound > −0.5.
  If several pass, the primary is the one with the largest mean of (abrupt Δ + delayed Δ) vs
  v0.6. If none pass, **no primary is nominated**, and the closest candidate is reported as a
  failure with the criteria it missed.
* **Predictions (written before running):** A2 recovers fastest of the three but has the largest
  stationary loss. A1 is in between. A3 is close to v0.6, because the v0.6 detector rarely fires
  and fires at most once per family. If neither A1 nor A2 improves abrupt and delayed vs v0.6,
  the hypothesis is not supported.

## Amendment 1 (implementation bug found after dev run 1; constants unchanged)

Dev run 1 (`reports/v09/agent_a/run1_invalid_gamma_shadowed/`) is **invalid for A1 and A2**.
The class constant was named `gamma`, but `caver5.policies.BayesianPolicy.__init__` sets an
instance attribute `self.gamma = 1.0`, which shadowed it. So A1 and A2 ran with γ = 1 and were
run-for-run identical to CAVER-v0.6: 800/800 matched (scenario, seed) runs had identical
outcomes, alarms, posterior snapshot and entropy, checked mechanically.
`tests/test_v09_temporal.py::test_continuous_decay_scales_all_families` exposed the bug.

Fix: rename the attribute to `decay_gamma`. The **values are unchanged** (A1 γ = 0.981366,
A2 γ = 0.95, A3 τ = 0.2). New regression tests check that the instance keeps the constant and
that A1/A2 diverge from v0.6. A3 and all baselines were unaffected; their run-2 results must
match run 1 exactly, and this is verified below. Run 1's candidate results were not used for
any decision. Run 2 is the dev result of record.

## 4. Dev results (run 2, the result of record)

Salt `v09dev`, seeds 0–199, real table, train 90 + eval 90, 2 workers.
Command: `python3 -m caver9.agent_a_dev --jobs 2`. Files are in `reports/v09/agent_a/`:
`dev_summary.json` (all metrics, CIs and the automatic nomination check), `dev_summary.csv`,
`dev_runs.csv` (per run), `dev_tables.md` (full tables with recall, first find, entropy,
false-alarm rate and CPU for every policy), `dev_mechanism.json` and `stdout.log`. Paired 95%
CIs on matched seeds, n = 200.

Run 1 versus run 2: A3 and all six baselines match run 1 exactly (800/800 runs each), so only A1
and A2 changed with the bug fix.

### Unique FALSE_PASS (mean)

| policy | stationary | abrupt | delayed | recovery |
|---|---|---|---|---|
| Random | 9.16 | 10.47 | 9.98 | 9.48 |
| UCB1 | 10.96 | 12.76 | 12.99 | 12.29 |
| SW-UCB | 9.85 | 11.96 | 11.43 | 11.01 |
| D-UCB | 9.96 | 12.07 | 11.79 | 11.31 |
| CAVER-v0.3 | 12.05 | 11.94 | 11.88 | 12.41 |
| CAVER-v0.6 | 11.68 | 12.19 | 12.34 | 12.10 |
| **A1-Decay.981** | 11.28 | **13.18** | **13.53** | 12.35 |
| A2-Decay.95 | 10.34 | 12.70 | 12.46 | 11.63 |
| A3-AlarmShrink.2 | 11.70 | 12.37 | 12.57 | 12.20 |

### Paired Δ unique FALSE_PASS [95% CI]

| policy | stat. vs v0.6 | abrupt vs v0.6 | delayed vs v0.6 | recovery vs v0.6 | stat. vs UCB1 | abrupt vs UCB1 | delayed vs UCB1 |
|---|---|---|---|---|---|---|---|
| Random | −2.51 [−2.88, −2.15] | −1.72 [−2.12, −1.32] | −2.35 [−2.88, −1.83] | −2.62 [−3.10, −2.13] | −1.80 [−2.17, −1.43] | −2.29 [−2.72, −1.86] | −3.01 [−3.59, −2.43] |
| UCB1 | −0.71 [−1.00, −0.42] | +0.57 [+0.21, +0.93] | +0.66 [+0.10, +1.21] | +0.19 [−0.37, +0.75] | – | – | – |
| SW-UCB | −1.83 [−2.14, −1.52] | −0.23 [−0.63, +0.18] | −0.91 [−1.41, −0.40] | −1.09 [−1.58, −0.61] | −1.12 [−1.46, −0.78] | −0.80 [−1.16, −0.43] | −1.56 [−2.14, −0.98] |
| D-UCB | −1.72 [−2.04, −1.39] | −0.12 [−0.50, +0.26] | −0.55 [−1.07, −0.02] | −0.79 [−1.29, −0.29] | −1.00 [−1.34, −0.67] | −0.69 [−1.05, −0.33] | −1.20 [−1.73, −0.67] |
| CAVER-v0.3 | +0.38 [+0.11, +0.64] | −0.26 [−0.62, +0.11] | −0.45 [−0.90, −0.00] | +0.31 [−0.12, +0.74] | +1.08 [+0.81, +1.36] | −0.82 [−1.20, −0.45] | −1.10 [−1.64, −0.57] |
| CAVER-v0.6 | – | – | – | – | +0.71 [+0.42, +1.00] | −0.57 [−0.93, −0.21] | −0.66 [−1.21, −0.10] |
| **A1-Decay.981** | **−0.40 [−0.66, −0.14]** | +0.98 [+0.65, +1.32] | +1.19 [+0.76, +1.62] | +0.24 [−0.18, +0.67] | +0.31 [+0.02, +0.60] | +0.41 [+0.06, +0.77] | +0.54 [+0.04, +1.03] |
| A2-Decay.95 | −1.34 [−1.61, −1.07] | +0.51 [+0.16, +0.86] | +0.13 [−0.34, +0.60] | −0.47 [−0.98, +0.04] | −0.63 [−0.93, −0.33] | −0.06 [−0.39, +0.27] | −0.53 [−1.07, +0.02] |
| A3-AlarmShrink.2 | +0.03 [−0.03, +0.08] | +0.17 [−0.01, +0.36] | +0.24 [+0.06, +0.42] | +0.10 [−0.04, +0.23] | +0.73 [+0.45, +1.02] | −0.40 [−0.74, −0.05] | −0.41 [−0.98, +0.15] |

### Recovery steps (mean, censored at the caver8 cap) and paired Δ vs v0.6

| policy | abrupt | Δ abrupt vs v0.6 | delayed | Δ delayed vs v0.6 | recovery scen. |
|---|---|---|---|---|---|
| Random | 8.1 | −8.74 [−10.60, −6.89] | 7.9 | −9.66 [−11.49, −7.83] | 8.7 |
| UCB1 | 10.6 | −6.30 [−8.37, −4.24] | 10.0 | −7.58 [−9.50, −5.65] | 8.9 |
| SW-UCB | 7.9 | −8.95 [−10.84, −7.06] | 8.7 | −8.80 [−10.78, −6.82] | 7.9 |
| D-UCB | 8.5 | −8.35 [−10.28, −6.42] | 7.8 | −9.70 [−11.63, −7.77] | 8.2 |
| CAVER-v0.3 | 23.0 | +6.16 [+4.01, +8.31] | 25.4 | +7.84 [+5.73, +9.95] | 27.8 |
| CAVER-v0.6 | 16.9 | – | 17.5 | – | 19.5 |
| A1-Decay.981 | 12.2 | −4.68 [−6.34, −3.03] | 10.7 | −6.84 [−8.71, −4.97] | 11.2 |
| A2-Decay.95 | 8.4 | −8.45 [−10.24, −6.65] | 8.9 | −8.58 [−10.38, −6.78] | 8.4 |
| A3-AlarmShrink.2 | 15.9 | −0.96 [−1.58, −0.35] | 16.6 | −0.94 [−1.92, +0.03] | 18.5 |

### Other §5 metrics (stationary / abrupt / delayed / recovery)

| policy | FP recall | first find | eval entropy | false-alarm rate (stat. / delayed / recovery) |
|---|---|---|---|---|
| UCB1 | 0.645 / 0.659 / 0.429 / 0.341 | 6.2 / 8.5 / 6.2 / 5.7 | 0.966 / 0.966 / 0.963 / 0.958 | – |
| D-UCB | 0.593 / 0.625 / 0.388 / 0.314 | 7.0 / 6.7 / 7.4 / 7.2 | 0.990 / 0.986 / 0.991 / 0.991 | – |
| CAVER-v0.6 | 0.693 / 0.632 / 0.408 / 0.338 | 5.1 / 11.9 / 4.9 / 5.2 | 0.940 / 0.951 / 0.859 / 0.807 | 0.190 / 0.140 / 0.040 |
| A1-Decay.981 | 0.667 / 0.684 / 0.448 / 0.345 | 5.4 / 8.9 / 5.3 / 6.7 | 0.962 / 0.965 / 0.941 / 0.933 | 0.130 / 0.105 / 0.050 |
| A2-Decay.95 | 0.613 / 0.659 / 0.411 / 0.326 | 6.3 / 7.2 / 6.8 / 6.5 | 0.984 / 0.980 / 0.980 / 0.978 | 0.155 / 0.055 / 0.015 |
| A3-AlarmShrink.2 | 0.695 / 0.641 / 0.416 / 0.341 | 5.1 / 11.8 / 4.9 / 5.1 | 0.942 / 0.956 / 0.873 / 0.823 | 0.190 / 0.140 / 0.040 |

Random, SW-UCB and v0.3 rows are in `dev_tables.md`.

**CPU µs per select + update** (stationary, run 2): Random 3.0, UCB1 7.7, D-UCB 9.6, SW-UCB 11.9,
v0.3 8.3, v0.6 11.0, A1 12.7, A2 12.4, A3 10.9. These numbers include two timer pairs per probe
(overhead about 0.83 µs per pair). They are **load-sensitive**: in the post-hoc run (§7), the
same A1 runs with identical outcomes measured 15.6–17.1 µs. The only robust conclusion is that
decay adds O(6) multiplications per update, a cost of a few µs at most, and that all policies
run at the 10 µs scale.

## 5. Mechanism measurements on dev (measured after freezing)

From `dev_mechanism.json` and `dev_summary.json`:

* **Up-weighted families are under-sampled right after the shift.** This is the share of the
  first 20 post-change probes that go to the 3 up-weighted families (uniform choice would give
  0.5):

  | scenario | v0.6 | A1 | A2 | A3 | UCB1 | D-UCB |
  |---|---|---|---|---|---|---|
  | abrupt | 0.31 | 0.52 | 0.59 | 0.32 | 0.55 | 0.56 |
  | delayed | 0.27 | 0.51 | 0.57 | 0.31 | 0.57 | 0.58 |

  This is the proximate cause of v0.6's slow recovery.
* **Evidence mass at the change point.** Per-run maximum family pseudo-count: abrupt 27.4 for
  v0.6 vs 12.4 for A1 and 5.2 for A2. Delayed: 43.8 vs 15.2 vs 5.4. The "neglected" families
  are not starved, because the `available()` exhaustion rule spreads probes. At the abrupt
  boundary v0.6 holds about 12 observations each for timeout, matcher and exec_mismatch, with
  posterior means 0.11–0.12, against `schema` with 24 observations and 0.235. The ranking is held
  in place by stale, low **means** on the up-families. These means were learned under W_BASE,
  and the arms are not re-sampled often enough to correct them. Decay pulls them back toward the
  prior, which forces re-sampling.
* **Detector and reset.** Runs with any alarm: abrupt 57%, delayed 39%. Runs with a post-change
  up-direction alarm on an up-weighted family: abrupt 45%, delayed 20%, recovery 14%. Of the
  post-change alarms, 37/139 in abrupt and 18/59 in delayed are **down**-direction alarms on
  down-weighted families. v0.6's local reset then returns that decayed family to the Beta(1,1)
  prior, making it more attractive (§1 point 4, now observed). The pre-change false-alarm rate
  is 19% in stationary.
* **Change-triggered decay (A3) cannot fix this.** It acts only when the detector fires, and the
  detector does not fire in 43% (abrupt) and 61% (delayed) of runs. Recovery improves by only
  about 1 probe.

**Verdict on the hypothesis.** It is **supported for the shift scenarios**. Continuous
discounting of old evidence (A1) cuts recovery by 4.7 (abrupt) and 6.8 (delayed) probes and
raises unique FALSE_PASS by +0.98 and +1.19 vs v0.6. It also beats UCB1 under shift (+0.41,
+0.54, CIs above 0). The dose–response is as predicted: more forgetting (A2) recovers as fast as
UCB1/Random (8–9 probes), but it explores almost uniformly (entropy ≈ 0.98) and loses discovery.
The hypothesis does **not** come free: the same forgetting costs −0.40 in stationary, where the
old evidence was correct.

All four predictions in §3 held: A2 recovers fastest with the largest stationary loss, A1 is in
between, and A3 is close to v0.6.

## 6. Nomination (predeclared rule, §3)

| criterion (dev) | A1 | A2 | A3 |
|---|---|---|---|
| stationary Δ vs v0.6 lb > −0.5 | **✗ (−0.66)** | ✗ (−1.61) | ✓ (−0.03) |
| abrupt Δ vs v0.6 lb > 0 | ✓ (+0.65) | ✓ (+0.16) | ✗ (−0.01) |
| abrupt Δ vs UCB1 lb > −0.5 | ✓ (+0.06) | ✓ (−0.39) | ✗ (−0.74) |
| abrupt Δ recovery vs v0.6 ub < 0 | ✓ (−3.03) | ✓ (−6.65) | ✓ (−0.35) |
| delayed Δ vs v0.6 lb > 0 | ✓ (+0.76) | ✗ (−0.34) | ✓ (+0.06) |
| delayed Δ vs UCB1 lb > −0.5 | ✓ (+0.04) | ✗ (−1.07) | ✗ (−0.98) |
| delayed Δ recovery vs v0.6 ub < 0 | ✓ (−4.97) | ✓ (−6.78) | ✗ (+0.03) |
| recovery Δ vs v0.6 lb > −0.5 | ✓ (−0.18) | ✗ (−0.98) | ✓ (−0.04) |

**No primary candidate is nominated.** None of A1–A3 passes all criteria on dev.

* **A1 (closest)** fails only criterion 1. Its stationary Δ vs v0.6 is −0.40 [−0.66, −0.14],
  so the lower bound misses −0.5 by 0.16. It meets every shift, recovery and UCB1 criterion, and
  it is the only policy here whose mean is at least UCB1's in all four scenarios (stationary
  +0.31 [+0.02, +0.60]; recovery +0.06 [−0.54, +0.65]). The lead may treat it as an informative
  partial result. Under the predeclared rule it is a failure.
* **A2** fails 4 of 8 criteria: it forgets too fast.
* **A3** fails 4 of 8: it is limited by the detector's power.

## 7. Post-hoc exploratory (added after seeing dev results; not a candidate, not nominated)

`PH-EvalOnlyDecay.981` (`caver9.temporal.PostHocEvalOnlyDecay`) applies A1's γ only after
`begin_evaluation()`. Question: does A1's stationary cost come from decay during training (an
implicit temper at the boundary)? Run with
`python3 -m caver9.agent_a_dev --jobs 2 --policies UCB1 CAVER-v0.6 A1-Decay.981 PH-EvalOnlyDecay.981 --out reports/v09/agent_a/posthoc`.
The UCB1, v0.6 and A1 runs reproduce run 2 exactly (2400/2400).

| Δ vs v0.6 [95% CI] | stationary | abrupt | delayed | recovery | Δ recovery steps abrupt / delayed |
|---|---|---|---|---|---|
| A1 | −0.40 [−0.66, −0.14] | +0.98 [+0.65, +1.32] | +1.19 [+0.76, +1.62] | +0.24 [−0.18, +0.67] | −4.68 / −6.84 |
| PH eval-only | −0.29 [−0.52, −0.07] | +0.50 [+0.22, +0.78] | +1.49 [+1.11, +1.87] | +0.21 [−0.19, +0.61] | −0.41 [−1.57, +0.74] / −4.03 |

Reading: train-phase decay explains only part of the stationary cost (−0.40 → −0.29). Most of
A1's **abrupt** recovery gain comes from train-phase decay, because a boundary shift needs a
lighter posterior at the boundary. Eval-only decay helps delayed more but leaves abrupt recovery
unchanged. Neither variant passes all criteria. This is exploratory evidence of the trade-off,
not a candidate. It was chosen after looking at dev, so its CIs are not confirmatory.

## 8. Failures and caveats

* **Implementation bug in run 1** (Amendment 1): the shadowed `gamma` made A1/A2 copies of v0.6.
  It was found by a unit test and fixed without changing constants. Run 1 is archived as invalid.
* **No primary nominated.** The hypothesis is supported only for shift scenarios. The stationary
  cost of continuous decay is real on dev and exceeds the −0.5 lower-bound margin.
* D-UCB and SW-UCB (prior art, constants not tuned here) are **worse than UCB1** in every
  scenario on this benchmark. Their violated-reward indices explore almost uniformly
  (entropy ≈ 0.99). So recency weighting of a UCB index on `violated` is not what helps. What
  helps is recency weighting of CAVER's **novelty** posterior.
* Replay caveat (design §8): seed CIs do not include the uncertainty of the 30 recorded real
  outcomes (n = 1 per config).
* All results are on dev. Seed, scenario and case-generator overfitting are possible. Agent D's
  new scenarios and the sealed final salt were not seen.
* CPU timings are load-sensitive (§4).
