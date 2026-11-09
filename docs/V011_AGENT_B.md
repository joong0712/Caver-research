# CAVER v0.11, Agent B: dual-memory exploration (pre-declaration)

Branch `v011/agent-b` (from `research/caver-v011` @ `8bf9b8f`). Role, isolation and the shared dev
rule: `docs/V011_DESIGN.md` §2–§5. Literature: `docs/V011_LITERATURE.md`.

**This section (§1–§6) is committed before any dev run.** Every constant of every candidate and of
every ablation arm is fixed here. Anything added after the first dev run is labelled post-hoc and is
not eligible.

## 1. Problem and hypothesis

v0.9/v0.10 established (REPLAY, dev):

* C2 (`C9-UCBMean`, posterior mean + 0.5·√(2 ln t / n)) wins after concentrated shifts but pays an
  exploration tax in stable/flat regimes (`docs/V010_AGENT_A.md` F1–F5).
* The bonus level moves stable and shift results in opposite directions, monotonically. C = 0.25 in
  both phases: stationary +0.14, c_uniform +0.81* vs C2, abrupt −0.23, delayed −0.16 (n.s.), but
  recovery 15.5 vs 10.8 steps.
* Training evidence is stale after a shift (F6): C2's greedy probes yield less than its exploratory
  probes in c_reverse. But **down-weighting all training evidence costs −0.88* in stationary**, so a
  memory that is short everywhere is not the answer.
* L1's single global gate (profile correlation, hard threshold, hold) was too noisy at the needed
  speed and traded one side for the other.

**Hypothesis H-B.** Keep the low, stable-friendly exploration level (C = 0.25) and let a **second,
short memory** take over only where recent predictive evidence says the long memory is stale. The
switch is soft (a Bayesian weight from predictive log-likelihood), so a noisy signal costs little in
stable regimes. The question is whether the evidence is strong enough, per arm or pooled, to recover
C2's shift gains.

**Prior expectation (stated before the dev run).** A generic synthetic Bernoulli calculation (no
benchmark code, cases, weights or tables; script not committed) shows that one arm's own predictive
evidence is weak at our scale. With the B1 constants and a yield drop 0.24 → 0.03 after 30 own
pulls, the mean short-memory weight rises only from about 0.41 to about 0.53 after 6 own pulls and
0.65 after 15. So B1's per-arm selection is expected to be slow. B2 pools evidence across arms
(more observations per unit time; ADR's "global change" argument). B3 tests a BOB-inspired
meta-selector.

## 2. Shared base (all candidates and ablations)

`caver11.agent_b._MemoryBase` subclasses `caver9.exploration.UCBMeanCAVER` (C2), so it inherits:

* `caver5.policies.BasePolicy.available()` (per-case exhaustion rule) and `visited` bookkeeping;
* the long-memory Beta(s+1, f+1) novelty posterior per arm (`successes`, `failures`, `counts`);
* v0.6's `ConfirmedFamilyDetector` and its **local reset** of the alarmed arm (the alarmed arm's short
  memory is reset too, see below);
* no sentinel and no ε; the random tie-break by shuffling `avail` (policy RNG);
* `t` = number of learned probes (train + eval); index bonus √(2 ln max(2, t) / n); an arm with
  long count n_L = 0 scores +∞ (C2's rule).

Observation `y` = `newly_found` (the reward C2 uses). `violated` feeds only the inherited detector.
Policies see only `(case_id: str, arm: str, violated: bool, newly_found: bool, learn)`. They never
parse case IDs, read hidden defects, weights, change points or scenario names, or use
`observe_outcome`.

Notation. Long mean m_L(f) = (s_f + 1)/(n_L(f) + 2), the C2 posterior mean. A discounted short
memory keeps (s_S, n_S) per arm, and its predictive mean is shrunk toward the long mean with
pseudo-count M0:

  m_S(f) = (s_S(f) + M0·m_L(f)) / (n_S(f) + M0).

Predictive log-likelihood of y under mean m: ℓ(m, y) = ln m if y else ln(1 − m), with m clipped to
[1e-6, 1 − 1e-6]. Every predictive score is computed **before** the observation is added (one-step-
ahead). On a local reset of arm f, s_S(f) = n_S(f) = 0 (and B1's λ_f returns to λ0) before the
current observation is added.

## 3. Candidates (eligible for nomination)

### B1 `B11-B1-DualMem` (`DualMemoryUCB`): per-arm blend by predictive accuracy

* Short memory per arm, discounted **per own pull**: on a pull of f, s_S ← γ_S s_S + y,
  n_S ← γ_S n_S + 1 (other arms unchanged). Effective window ≤ 1/(1 − γ_S) = 5 own pulls.
* Per-arm log-odds λ_f that the short memory is the better predictor (dynamic model averaging with
  forgetting toward the prior): on a pull of f,
  λ_f ← λ0 + α(λ_f − λ0) + ℓ(m_S(f), y) − ℓ(m_L(f), y), clipped to [−6, 6]; λ0 = logit(W0).
* w_f = σ(λ_f). Blended mean m_B(f) = (1 − w_f) m_L(f) + w_f m_S(f). Effective count
  n_eff(f) = (1 − w_f) n_L(f) + w_f n_S(f).
* Index: m_B(f) + C·√(2 ln max(2, t) / n_eff(f)); +∞ if n_L(f) = 0.

| constant | value |
|---|---|
| γ_S (discount per own pull) | 0.8 |
| M0 (short-memory shrinkage toward the long mean) | 1.0 |
| W0 (prior short weight) | 0.5 (λ0 = 0) |
| α (forgetting of λ toward λ0, per own pull) | 0.9 |
| λ clip | ±6 |
| C (training and evaluation) | 0.25 |

### B2 `B11-B2-PooledDualMem` (`PooledDualMemoryUCB`): one pooled weight, coupled to exploration

* Short memory per arm, discounted **per learned probe (global time)**: on every learned probe, every
  arm's (s_S, n_S) ← γ_G·(s_S, n_S); then the pulled arm adds (y, 1). Arms that are not pulled lose
  short-memory count, so they get a large bonus **only when** the short memory has weight.
* One global log-odds Λ, pooled over all arms: on every learned probe of arm f,
  Λ ← λ0 + α(Λ − λ0) + ℓ(m_S(f), y) − ℓ(m_L(f), y), clipped to [−6, 6]; λ0 = logit(W0); w = σ(Λ).
* m_B(f) = (1 − w) m_L(f) + w m_S(f); n_eff(f) = (1 − w) n_L(f) + w n_S(f).
* Exploration coefficient coupled to the weight: C(w) = C_LOW + (C_HIGH − C_LOW)·w (both phases).
* Index: m_B(f) + C(w)·√(2 ln max(2, t) / n_eff(f)); +∞ if n_L(f) = 0; n_eff floored at 1e-6.

| constant | value |
|---|---|
| γ_G (discount per learned probe, all arms) | 0.95 |
| M0 | 1.0 |
| W0 | 0.2 (λ0 = ln 0.25 ≈ −1.386) |
| α (per learned probe) | 0.95 |
| Λ clip | ±6 |
| C_LOW / C_HIGH | 0.25 / 0.5 |

### B3 `B11-B3-MemHedge` (`MemoryHedgeUCB`): BOB-inspired meta-selector over memory lengths

* Three experts e = (γ_e, C_e): **(1.0, 0.25)**, **(0.98, 0.4)**, **(0.93, 0.5)**. Expert γ = 1 is
  the long memory (m_L, n_L). Each γ < 1 expert keeps its own global-time discounted (s_e, n_e) per
  arm, with m_e(f) = (s_e + M0·m_L)/(n_e + M0), M0 = 1.0. Its index is
  m_e(f) + C_e·√(2 ln max(2, t) / max(n_e(f), 1e-6)) (+∞ if n_L(f) = 0).
* **Blocks** of H = 10 learned probes (train 90 = 9 blocks, eval 90 = 9 blocks, aligned). At the
  first `select` of a block, one expert is **sampled** from π with the policy RNG and used for the
  whole block.
* During the block, every expert's predictive log-loss on the pulled arm's outcome is accumulated
  (−ℓ(m_e(f), y), all experts, full information). At the block end: Hedge
  π_e ∝ π_e·exp(−η·L_e), then fixed share π ← (1 − ρ)π + ρ/3. π starts uniform.

| constant | value |
|---|---|
| experts (γ, C) | (1.0, 0.25), (0.98, 0.4), (0.93, 0.5) |
| H (block length, learned probes) | 10 |
| η (Hedge learning rate on summed block log-loss) | 1.0 |
| ρ (fixed share per block) | 0.1 |
| M0 | 1.0 |

## 4. Ablations (pre-declared; mechanism arms, **not eligible**)

| id | class | change | isolates |
|---|---|---|---|
| AB1 `B11-AB-LongOnly` | `AblLongOnly` | B1 with w_f ≡ 0 | long memory alone. **Equals C2 with C = 0.25** (v0.9 M4); a unit test checks identical choices |
| AB2 `B11-AB-ShortOnly` | `AblShortOnly` | B1 with w_f ≡ 1 | short memory alone |
| AB3 `B11-AB-FixedBlend` | `AblFixedBlend` | B1 with w_f ≡ 0.5 | blending without predictive selection |
| AB4 `B11-AB-B1-LongBonus` | `AblB1LongBonus` | B1 with the bonus on n_L instead of n_eff | effect of the n_eff coupling |
| AB5 `B11-AB-B2-NoCoupling` | `AblB2NoCoupling` | B2 with C_HIGH = C_LOW = 0.25 | pooled blend without the C coupling |
| AB6 `B11-AB-B2-CoupleOnly` | `AblB2CoupleOnly` | B2 with mean m_L and count n_L; w only sets C(w) | the pooled weight as a signal only |
| AB7 `B11-AB-B3-UniformMeta` | `AblB3UniformMeta` | B3 with η = 0 (π stays uniform) | value of the meta-selector |

## 5. Paper mapping and differences (no novelty claim)

| component | source idea | what is the same | what differs here |
|---|---|---|---|
| long + discounted short Beta posterior | discounted / sliding-window bandits (Garivier & Moulines 2011, D-UCB/SW-UCB); discounted Thompson sampling (Raj & Kalyani 2017) | geometric forgetting of old evidence | the short memory is **shrunk toward the long mean** (M0), so it departs from the long memory only on recent disagreement; it is one of two models, not the policy's only memory |
| B1/B2 weights | dynamic model averaging with forgetting (Raftery, Kárný & Ettler 2010); Bayesian model averaging of predictive likelihoods | posterior model weight ∝ product of one-step predictive likelihoods, with forgetting | forgetting pulls the log-odds toward a fixed prior λ0, not toward uniform; two models only; B1 is per arm, B2 pooled |
| B2 pooling | ADR-bandit's global-change assumption (Komiyama, Fouché & Honda 2024) | evidence from any arm informs all arms | no ADWIN window, no reset, no monitoring arms; a soft weight, not a detector. Agent A owns ADWIN/GLR. |
| B2/B3 coupling of C to memory | Predictive Sampling's principle (Liu, Van Roy & Xu 2023): value information by how fast it goes stale | more exploration when stale evidence is detected | **this is not Predictive Sampling**: no dynamics prior, no sampling of future rewards, no Thompson sampling |
| B3 meta-selector | Bandit-over-Bandit (Cheung, Simchi-Levi & Zhu 2019) | blocks; a meta-learner picks a memory length (window) per block and holds it for the block | **not BOB**: (1) Hedge with **full-information predictive log-loss** of every expert, not EXP3 on the block's bandit reward; (2) fixed share ρ; (3) H = 10 and 18 blocks per run, not H = ⌊d^{2/3}T^{1/2}⌋; (4) experts are discounted Beta-UCB indices with coupled C, not SW-UCB on a linear bandit; (5) the candidate set J is three hand-set discounts, not BOB's geometric grid; (6) no regret guarantee is claimed |

## 6. Dev procedure (fixed in advance)

1. One run, candidates only (all 7 baselines are added by the devkit):
   `python3 -m caver11.devkit --candidates caver11.agent_b:DualMemoryUCB caver11.agent_b:PooledDualMemoryUCB caver11.agent_b:MemoryHedgeUCB --output reports/v011/agent_b/dev --jobs 2`
   (salt `v011dev`, seeds 0–299, 19 scenarios).
2. One ablation run with the 7 ablation arms (plus baselines) to `reports/v011/agent_b/ablation`.
3. `devkit.dev_rule` for each candidate. Nominate **at most one** candidate that passes every check;
   ties: larger pooled Δ vs C2, then larger minimum S lower bound. If none passes, report all failures
   and nominate none (the lead may still freeze the fewest-failures candidate as "best available;
   failed dev").
4. Report: unique FALSE_PASS, variant-level unique FALSE_PASS, first find, recovery, stable loss,
   duplicate rate, false-alarm rate, cost (USD, wall ms, CPU µs per probe). All numbers are REPLAY.

---

# Results (added after the dev runs; §1–§6 above are unchanged since `a2ac39e`)

Commit order: pre-declaration `a2ac39e` → implementation and tests `7c1d85f` → dev run `6ebbd34` →
ablation run `d827667`. **Every number below is REPLAY** of the stored real outcomes (extended real
table, 42 configs), salt `v011dev`, seeds 0–299, 19 scenarios, 90 train + 90 eval probes. CIs are
paired normal 95% over seeds. Type-level and pooled CIs use the per-seed mean difference over the
type's scenarios (the devkit's pooled construction). Source tables:
`reports/v011/agent_b/dev_tables.md`, `ablation_tables.md` (generated by `make_tables.py` from the
saved `summary.json`/`runs.csv.gz`).

```bash
python3 -m caver11.devkit --candidates caver11.agent_b:DualMemoryUCB caver11.agent_b:PooledDualMemoryUCB caver11.agent_b:MemoryHedgeUCB --output reports/v011/agent_b/dev --jobs 2        # 164 s
python3 -m caver11.devkit --candidates caver11.agent_b:AblLongOnly caver11.agent_b:AblShortOnly caver11.agent_b:AblFixedBlend caver11.agent_b:AblB1LongBonus caver11.agent_b:AblB2NoCoupling caver11.agent_b:AblB2CoupleOnly caver11.agent_b:AblB3UniformMeta --output reports/v011/agent_b/ablation --jobs 2
python3 reports/v011/agent_b/make_tables.py reports/v011/agent_b/dev > reports/v011/agent_b/dev_tables.md
```

## 7. Verdict

**No candidate passes `devkit.dev_rule`. Agent B nominates none.** Fewest failures: **B2 (13/142)**,
then B1 (18/142) and B3 (56/142). For context, the L1 baseline fails 21/142 under the same rule on the
same run (`dev/l1_rule_context.json`). If the lead needs a "best available; failed dev" entry from
Agent B, it is B2, which cannot be adopted (V011_DESIGN §4).

## 8. Dev table (candidates)

Δ unique FALSE_PASS (95% CI):

| policy | pooled vs v0.6 | pooled vs C2 | stable vs v0.6 | stable vs C2 | abrupt vs v0.6 | abrupt vs C2 | other vs v0.6 | other vs C2 |
|---|---|---|---|---|---|---|---|---|
| C2 (reference) | +0.37 [+0.30, +0.45] | – | – | – | – | – | – | – |
| L1 (reference) | +0.40 [+0.32, +0.47] | +0.03 [−0.04, +0.09] | −0.09 [−0.20, +0.03] | +0.23 [+0.12, +0.34] | +0.76 [+0.63, +0.88] | +0.01 [−0.09, +0.12] | +0.32 [+0.17, +0.48] | −0.13 [−0.28, +0.03] |
| **B1** DualMem | +0.41 [+0.34, +0.49] | +0.04 [−0.03, +0.12] | −0.31 [−0.44, −0.19] | +0.00 [−0.12, +0.12] | +0.88 [+0.76, +1.00] | +0.14 [+0.03, +0.25] | +0.39 [+0.24, +0.54] | −0.06 [−0.22, +0.11] |
| **B2** PooledDualMem | +0.47 [+0.39, +0.55] | +0.10 [+0.03, +0.17] | −0.11 [−0.22, +0.01] | +0.21 [+0.09, +0.33] | +0.83 [+0.71, +0.95] | +0.09 [−0.02, +0.19] | +0.47 [+0.31, +0.64] | +0.03 [−0.14, +0.19] |
| **B3** MemHedge | −0.30 [−0.38, −0.22] | −0.67 [−0.75, −0.59] | −0.57 [−0.69, −0.45] | −0.26 [−0.38, −0.13] | −0.00 [−0.11, +0.11] | −0.74 [−0.86, −0.63] | −0.47 [−0.63, −0.32] | −0.92 [−1.08, −0.76] |

Means over the 19 scenarios:

| policy | unique FP | variant-level unique FP | first find | duplicate rate | false-alarm rate | USD / probe | CPU µs / probe |
|---|---|---|---|---|---|---|---|
| CAVER-v0.6 | 11.24 | 6.82 | 6.15 | 0.0129 | 0.059 | 0.02372 | 9.9 |
| C2 | 11.61 | 7.01 | 6.59 | 0.0140 | 0.059 | 0.02385 | 9.9 |
| L1 | 11.63 | 6.98 | 6.15 | 0.0142 | 0.060 | 0.02391 | 12.2 |
| B1 | 11.65 | 6.93 | 6.54 | 0.0142 | 0.058 | 0.02391 | 17.1 |
| B2 | 11.71 | 6.91 | 6.48 | 0.0139 | 0.055 | 0.02385 | 18.4 |
| B3 | 10.94 | 6.95 | 6.95 | 0.0123 | 0.054 | 0.02369 | 19.0 |

* **Variant-level uniqueness.** Pooled variant-level Δ vs C2 is negative for every candidate (B1
  −0.08 [−0.12, −0.03], B2 −0.09 [−0.14, −0.05], B3 −0.06 [−0.11, −0.01]). The (case, family) gains
  over C2 are not gains in distinct (family, variant) FALSE_PASS.
* **Recovery** (restricted mean, Δ vs v0.6). B1 and B2 recover faster than v0.6 in every abrupt
  scenario except: B1 `c_late` −1.0 [−1.9, +0.0] and `c_reverse` −2.1 [−4.3, +0.2]; B2 `c_late`
  −0.1 [−1.0, +0.8]. Both are slower than C2 in most shift scenarios (e.g. abrupt 13.2 / 13.0 vs
  C2 12.3, v0.6 17.0). B3 recovers fastest (abrupt 10.9) but finds far fewer FALSE_PASS (the F4 caveat
  of v0.10: recovery rewards spreading probes).
* **Duplicate rate** is 1.2–1.5% for all learners; the candidates do not change it materially.
* **False alarms** stay within v0.6 + 0.05 in every scenario where defined (FA passes for all).
* **Cost.** Replayed USD and wall ms per probe are the same as the baselines (the outcome table
  dominates). Policy CPU rises to 17–19 µs per probe (v0.6 9.9).

## 9. `dev_rule` failures

| candidate | failed / 142 | S (stable vs v0.6) | K | G | U |
|---|---|---|---|---|---|
| B1 | 18 | 5/5 fail: stationary −0.44, f_stat_skew −0.64, f_stat_flat −0.63, c_uniform −0.70, f_flat_shift −0.45 | K_shift vs v0.6 f_abrupt_after −0.09; K_recovery c_late +0.01, c_reverse +0.20 | vs UCB1: abrupt, double, single, c_late; vs v0.6: c_uniform, f_stat_skew, f_stat_flat, f_spike, f_gradual | vs C2 [−0.03, +0.12] |
| B2 | 13 | 4/5 fail: f_stat_skew −0.53, f_stat_flat −0.45, c_uniform −0.32, f_flat_shift −0.33 (stationary passes, −0.15) | K_shift vs C2 abrupt −0.45; K_recovery c_late +0.79 | vs UCB1: abrupt, double, single, c_late, c_reverse; vs v0.6: f_stat_skew, f_gradual | **passes** both: vs v0.6 [+0.39, +0.55], vs C2 [+0.03, +0.17] |
| B3 | 56 | 5/5 fail | 16 of 24 fail | 33 fail | both fail |

(Values are the CI bound the check uses.) Note that `G_vs_UCB1` fails in the abrupt-type scenarios for
L1 too (6 checks): on this dev salt UCB1 is strong after concentrated shifts (abrupt-type +0.40 vs
v0.6).

## 10. Ablations (pre-declared mechanism arms; not eligible)

| arm | pooled vs C2 | stable vs v0.6 | abrupt vs C2 | failed / 142 | reading |
|---|---|---|---|---|---|
| AB1 LongOnly (= C2 at C = 0.25) | +0.16 [+0.08, +0.23] | +0.24 [+0.13, +0.34] | −0.04 [−0.14, +0.06] | 18 (K_recovery 7, K_shift vs C2 4, G vs UCB1 7) | the low C alone already beats every candidate pooled |
| AB2 ShortOnly | +0.17 [+0.09, +0.25] | **+0.39 [+0.28, +0.50]** | −0.06 [−0.17, +0.05] | 20 (K_recovery 8) | short memory (shrunk to the long mean) is *best* in stable regimes; recovery slow |
| AB3 FixedBlend (w = 0.5) | **+0.23 [+0.16, +0.30]** | −0.12 [−0.24, +0.01] | **+0.30 [+0.20, +0.40]** | 10 (S 5) | blending + n_eff bonus helps shifts; the n_eff coupling costs in stable |
| AB4 B1 with long-count bonus | +0.13 [+0.06, +0.20] | −0.20 [−0.32, −0.09] | +0.26 [+0.14, +0.37] | 14 | |
| AB5 B2 without C coupling | +0.20 [+0.13, +0.28] | +0.11 [−0.00, +0.23] | +0.12 [+0.01, +0.22] | **8** (G vs UCB1 5, K_shift vs C2 2, K_recovery 1) | fewest failures of all Agent B arms |
| AB6 B2 coupling only | +0.21 [+0.14, +0.28] | +0.20 [+0.09, +0.32] | +0.05 [−0.05, +0.16] | 12 | |
| AB7 B3 with uniform meta | −0.77 [−0.85, −0.69] | −0.80 [−0.93, −0.68] | −0.76 [−0.88, −0.64] | 55 | |

Findings (REPLAY, dev; mechanism attributions are **[HYPOTHESIS]** beyond the measured contrasts):

* **B-F1. Per-arm predictive selection hurt.** B1 (learned per-arm weight) is worse than the same
  model with a fixed 0.5 weight: pooled vs C2 +0.04 vs +0.23; stable vs v0.6 −0.31 vs −0.12. As the
  pre-run synthetic check predicted, one arm's evidence is weak. [HYPOTHESIS] The weight mainly
  follows noise, so arms swing between memories in stable runs.
* **B-F2. Pooling plus coupling double-counts exploration.** B2 is worse than either of its parts
  alone (vs C2: B2 +0.10, without coupling +0.20, coupling only +0.21; stable vs v0.6 −0.11 vs
  +0.11 / +0.20). When w rises, the blended n_eff already shrinks for unpulled arms; raising C on top
  over-explores.
* **B-F3. Per-arm blending of the two memories costs in stable regimes, though each memory alone does
  not.** Long only (AB1) and short only (AB2) pass all five S checks. Every per-arm blend fails all five
  (B1, AB3 with w = 0.5, AB4 with the long-count bonus), whichever count the bonus uses. The arms that
  pass S fail K_recovery more often (AB1 7, AB2 8, AB6 5 of 8), except AB5 (1). So the v0.10 trade-off
  reappears, but AB5 (pooled blend, fixed C = 0.25) comes closest to escaping it. The mechanism of the
  blend's stable loss is not identified.
* **B-F4. The BOB-inspired meta-selector cannot learn at this horizon.** B3 vs its uniform-meta
  ablation: pooled +0.10 vs C2 (−0.67 vs −0.77). 18 blocks per run are too few, and the γ < 1 experts
  with C = 0.4–0.5 and global-time discounting explore like D-UCB. This matches the literature note
  that BOB's EXP3 "cannot learn within one run" here.
* **B-F5. The short memory shrunk toward the long mean is a strong stable-regime estimator** (AB2
  stable +0.39 vs v0.6, all five S checks pass). It was not a declared candidate, so it is not
  eligible. **[HYPOTHESIS for a future pre-registered study]** AB2's estimator or AB5's pooled blend,
  with an exploration term that does not shrink with the weight, may keep the stable gain. That has to
  be tested on a new salt, not selected from this run.

## 11. Caveats

* Single dev salt; all REPLAY; seed CIs do not cover outcome-table uncertainty. The dev_rule is an
  intersection over 142 checks with no multiplicity correction, so even a policy at C2's level fails
  some checks by chance.
* AB1–AB7 were declared before the run but as non-eligible mechanism arms. Their better numbers are
  reported, not used for selection. Promoting one would be post-hoc.
* The synthetic prior check (§1) was originally a scratch script; it was re-created after the dev run as
  `reports/v011/agent_b/synthetic_prior_check.py` and reproduces the quoted numbers (0.41 → 0.53 → 0.65).
* No Claude CLI call, no other salt, no final-environment file was used.
* Full suite: `python3 -m unittest discover -s tests`: 255 tests OK (11 in `tests/test_v011_agent_b.py`); log `reports/v011/agent_b/test_log.txt`.
