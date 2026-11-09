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
