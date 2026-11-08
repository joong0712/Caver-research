# CAVER v0.9 — Failure analysis

Everything below is from the final holdout (`v09final`, real-table replay) unless marked
"dev". Mechanism statements marked **[HYPOTHESIS]** were not tested directly.

## 1. The frozen candidate B2 missed criterion 3 in `abrupt`

* **Observation.** Recovery steps were 14.6 for B2 vs 16.1 for v0.6: Δ −1.46, CI
  [−2.93, +0.01]. The criterion needed the upper bound below 0.
* **Comparison.** In delayed, the same policy recovers significantly faster (−4.0
  [−5.6, −2.4]). UCB1 recovers in 9.8.
* **[HYPOTHESIS] mechanism.** B2's discovery model is **undiscounted**, so after 90 training
  probes the families that produced FALSE_PASS in training keep high posterior means. Only the
  0.4-weighted, discounted violation model can move. In `abrupt` the shift coincides with the
  train/eval boundary, when that undiscounted mass is largest. Agent B's dev ablation agrees:
  discounting the discovery model too cost 1.27 FALSE_PASS in stationary.
* **The margin was decided by 0.01 probes.** The criterion was not relaxed after the fact. The
  correct reading is "B2 improved abrupt recovery by about 1.5 probes, not significantly", not
  "B2 failed badly".

## 2. The dev selection rule picked the wrong one of two good candidates

* **What happened.** Amendment 2 chose between B2 and C2 by the mean abrupt/delayed FALSE_PASS
  gain only (1.235 vs 1.123). The rule ignored recovery speed, where C2 was clearly better on
  dev (12.3/12.5 vs 14.5/15.1 steps).
* **Result.** C2 then passed all final criteria and B2 did not.
* **Lesson for the next study.** The candidate-selection rule should cover **every** adoption
  criterion, for example by excluding candidates whose dev recovery CI is close to 0, not only
  the headline metric. This is a design flaw in the pre-registration, recorded rather than
  repaired retroactively.

## 3. Combining B and C made things worse (V09-BC)

* **Observation.** V09-BC loses 0.63 [−0.86, −0.39] FALSE_PASS in stationary vs v0.6, while
  B2 (+0.10) and C2 (−0.13) are each non-inferior. It recovers fastest of the CAVER family
  (10.0/10.0), but trades stationary yield for it.
* **Ablation.** Removing the violation model (V09-BC[-viol]) restores stationary (−0.17) and
  passes all criteria.
* **[HYPOTHESIS] mechanism.** The violation model also rewards defects the weak test catches
  (CONTRACT_VIOLATION without FALSE_PASS). Under C's stronger UCB exploration, that pull is no
  longer counterweighted by B2's Beta-sd and coverage structure. So probes go to families with
  high raw violation rates but few FALSE_PASS.
* **Rule outcome.** As pre-registered, the combination was not adopted ("do not force an
  integration that is worse than its parts").

## 4. Temporal decay (Agent A) trades stationary yield for speed

* **A1** (continuous discount γ = 0.981, Garivier–Moulines formula): under shift it reaches
  UCB1's level (abrupt +0.01, delayed +0.57 vs UCB1), but stationary is −0.63 vs v0.6.
  Forgetting is applied whether or not anything changed.
* **A2** (γ = 0.95), dev only: forgets too fast; recovers like UCB1 but loses 1.34 in stationary.
* **A3** (shrink after an alarm), dev only: barely differs from v0.6, because the v0.6 detector
  never fired in 43% of abrupt and 61% of delayed runs. This is the same detection-power problem
  v0.8 found for the GLR gate.
* **Agent A run 1 was invalid.** An instance attribute (`gamma = 1.0` in `BayesianPolicy`)
  shadowed the class constant, so A1/A2 ran as v0.6. A unit test caught it. The constants were
  renamed, not changed, and run 1 is archived. The lead verified that the diff renames only.

## 5. Exploration variants that failed (Agent C, dev)

* **C1** (recency and staleness bonus): recovers faster but loses FALSE_PASS in every scenario.
* **C3** (adaptive ε): no effect under shift.
* Fixed ε 0.10, frequency-only and staleness-only fail the shift criteria. UCB c = 1.0 fails
  stationary.
* **Agent C's dev finding:** across 11 learning policies, exploration diversity and stationary
  FALSE_PASS correlate at r = −0.92. More exploration is not the fix. C2 works by **redirecting**
  exploration (time-growing bonus, no sentinel), not by adding it. Part of C2's gain comes from
  dropping v0.6's sentinel (post-hoc ablation, labelled exploratory).

## 6. Limits of the algorithms found in this study

1. **No CAVER-family policy matched UCB1's recovery speed** in abrupt or delayed. On the final
   holdout, every policy that recovers in ≤ 10.5 probes in both abrupt and delayed loses at least
   0.6 stationary FALSE_PASS vs v0.6: V09-BC −0.63, UCB1 −0.99, UCB1-RM −0.84, D-UCB −1.59,
   SW-UCB −1.70, Random/Uniform about −2.4. A2 showed the same pattern on dev (−1.34). This is
   an empirical trade-off frontier in this benchmark, not a proven bound.
2. **Change detectors do not drive adaptation here.** v0.6's confirmed detector is silent in
   many shifted runs (A3), and v0.8's GLR gate was nearly always silent. The gains in v0.9 come
   from score design (reward signal, bonus shape), not from detection.
3. **The weak point is the train/eval boundary shift** (`abrupt`). It is the one scenario where
   B2's recovery gain was not significant, and the one v0.8 tempering could only partly fix.

## 7. Evaluation and process issues

* **Case-ID leakage (found by Agent D).** caver8 case IDs encode the cohort (`-eval-shift-`).
  A deliberately cheating v0.6 gains +1.2 to +2.1 FALSE_PASS by reading it. None of the v0.9
  policies parse case IDs (source audit), and opaque-ID re-runs reproduced every dev number
  exactly. v0.8 results are also unaffected, because no v0.8 policy reads IDs. The final holdout
  used opaque IDs.
* **The seal is harness-level only.** Calling `caver8.benchmark.schedules('v09final', …)`
  directly would bypass it. The unseal log shows exactly two final runs, both at frozen commit
  `2584d6a`, one per pre-registered table.
* **Replay is not independent evidence.** One table of 30 configs (now two identical
  repetitions) underlies every number. Seed CIs do not cover the per-configuration outcome
  uncertainty. A run-to-run outcome change in a single FALSE_PASS config could shift all
  results.
* **Synthetic case distribution.** Family weights and shift shapes are design choices. Holdout
  salts protect against seed overfitting, not against overfitting to the generator family.
