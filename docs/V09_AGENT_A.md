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
