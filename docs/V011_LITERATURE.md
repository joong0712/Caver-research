# CAVER v0.11: literature review (Phase 1)

## Sources and how they were read

The full texts were downloaded from arXiv into the session scratchpad. `pdftotext` was used, and
the algorithm-defining passages were read: algorithm boxes, definitions, theorems/corollaries and
experiment summaries. Quotes below are from those texts. The PDFs are not committed (licence).

| paper | source read | status |
|---|---|---|
| Besson, Kaufmann, Maillard, Seznec. *Efficient Change-Point Detection for Tackling Piecewise-Stationary Bandits.* JMLR 23 (2022) | arXiv:1902.01575 full text | read |
| Komiyama, Fouché, Honda. *Finite-time Analysis of Globally Nonstationary Multi-Armed Bandits.* JMLR 25 (2024) | arXiv:2107.11419 full text | read |
| Cheung, Simchi-Levi, Zhu. *Learning to Optimize under Non-Stationarity.* AISTATS 2019 | arXiv:1810.03024 full text (two-column extraction, partly garbled) | read; formulas checked where legible |
| Liu, Van Roy, Xu. *Nonstationary Bandit Learning via Predictive Sampling.* AISTATS 2023 | arXiv:2205.01970 full text | read |
| Biagiola, Feldt, Tonella. *Adaptive Random Testing with Q-grams: The Illusion Comes True.* FSE 2025 (PACMSE 2) | arXiv:2410.17907 full text | read |
| Spieker, Gotlieb, Marijan, Mossige. *Reinforcement Learning for Automatic Test Case Prioritization and Selection in CI* (RETECS). ISSTA 2017 | arXiv:1811.04122 full text | read |
| Prado Lima, Vergilio. *A Multi-Armed Bandit Approach for Test Case Prioritization in CI Environments* (COLEMAN). IEEE TSE 48(2), 2022 | **full text NOT available**: no arXiv preprint found via the arXiv API; IEEE not reachable from this environment | only the repository docs (`github.com/jacksonpradolima/coleman`) and bibliographic metadata were read. Statements about COLEMAN are marked **[repo-only]**. |

## Per-paper summary (as stated in the papers)

### GLR-klUCB (Besson et al. 2022)

* **Detector.** Bernoulli GLR change-point detector (Def. 1, eq. 2):
  τ̂ = inf{ n : sup_{s∈[1,n]} [ s·kl(μ̂_{1:s}, μ̂_{1:n}) + (n−s)·kl(μ̂_{s+1:n}, μ̂_{1:n}) ] ≥ β(n, δ) },
  with β defined through the function T(x) of Kaufmann & Koolen (Lemma 2), which bounds false
  alarms under i.i.d. data.
* **Algorithm 1.** klUCB index. **Forced exploration** with probability α_k: round-robin arm when
  `t mod ⌊A/α_k⌋ ∈ {1..A}`. After an alarm on the played arm, a **local restart** (that arm's
  history) or a **global restart** (all arms).
* **Tuning (Cor. 6).** α_k = α0·√(kA ln T / T) and δ = 1/T^γ, with γ ∈ (1/2, 1]. Regret
  O(√(Υ_T A T ln T)/(Δ_change)²) on instances satisfying Assumption 4 (changes large and far enough
  apart).
* **Practice.** Test only every Δs split points / Δn steps to cut cost. The detector needs no prior
  on the minimum change size, unlike CUSUM-UCB and M-UCB.

### ADR-bandit (Komiyama, Fouché, Honda 2024)

* **ADWIN** (Alg. 1). Keep a window W and drop the older part whenever some split W = W1 ∪ W2 has
  |μ̂_W1 − μ̂_W2| ≥ ε_cut, with ε_cut = √(log(1/δ)/(2|W1|)) + √(log(1/δ)/(2|W2|)) (eq. 1,
  Hoeffding-based). Every split is checked.
* **Base bandits.** TS and KL-UCB on windowed counts (Alg. 2, 3). TS is shown to be
  "drift-tolerant" (Lemma 14) but needs forgetting once drift is large.
* **ADS-bandit** (Alg. 4) shrinks each arm's window. **ADR-bandit** (Alg. 5) **resets** when a
  detector fires, and uses **monitoring arms** drawn at least N times per sub-block over doubling
  blocks.
* **Global change.** Defined as abrupt changes whose cross-arm magnitudes are comparable (Def. 19,
  constant C^ab), and gradual drift where all arms move proportionally (Assumption 22, C^gr).
* **Claim (abstract).** Under global changes, "forced exploration is unnecessary". ADR-bandit "has
  optimal performance in stationary environments as well as nonstationary environments with global
  changes".

### Bandit-over-Bandit (Cheung, Simchi-Levi, Zhu 2019)

* **Setting.** Non-stationary *linear* stochastic bandit with variation budget B_T.
* **SW-UCB.** With known B_T the window is tuned. **BOB** removes that need:
  * split the horizon into ⌈T/H⌉ blocks;
  * in each block, a meta **EXP3** picks the SW-UCB window length w from a candidate set J ⊆ [H];
  * the **block's total reward** is EXP3's feedback.
  * Choices (eq. 22): H = ⌊d^{2/3} T^{1/2}⌋, J = {H^0, ⌊H^{1/Δ}⌋, …, H} with Δ = ⌈ln H⌉.
* **Regret.** Õ(d^{2/3}(B_T+1)^{1/4} T^{3/4}).

### Predictive Sampling (Liu, Van Roy, Xu 2023)

* **Diagnosis.** Thompson sampling "does not differentiate actions based on how quickly the
  information acquired loses its usefulness".
* **Algorithm 1 (PS).** Sample the **future reward sequence** R̂_{t+1:∞} from the posterior; estimate
  θ̂_t = E[R_t | H_{t−1}, R_{t+1:∞} ← R̂]; act greedily on θ̂_t.
* **Requirement.** A probabilistic model of the environment's dynamics (for example a modulated
  Bernoulli bandit with a Markov switching kernel, or AR(1) bandits).
* **Properties.** In a stationary bandit PS equals TS (Prop. 1). The Bayesian regret bound depends on
  the cumulative predictive information. Tractable approximations exist for AR(1) and logistic
  bandits.

### Q-gram ART (Biagiola, Feldt, Tonella 2025)

* **Idea.** Instead of pairwise distances to all executed tests (quadratic), keep an **aggregate of
  q-gram counts** over executed test sequences. Pick the candidate that maximises a diversity
  measure such as **q-gram entropy**. Cost becomes **linear** in executions.
* **Results.** On 6 web apps it covered about **4× more unique targets than random testing** and
  about **3.5× more than distance-based ART**. In simulation it exposed low-probability faults with
  2.6–3.4× higher probability and about 10× fewer executions.
* **Requirement.** Tests are sequences (for example method calls along navigation paths), so they
  have q-gram structure.

### RETECS (Spieker et al. 2017)

* **Setting.** CI test prioritisation and selection as RL, with a tableau agent and a neural-network
  agent.
* **State.** Duration, last execution, failure history.
* **Reward functions:** failure count, test-case failure, and time-ranked (order-aware).
* **Evaluation.** NAPFD on three industrial data sets (Paint Control, IOF/ROL, GSDTSR). The agents
  learn "without any prior knowledge … and without any model of the environment", but need a number
  of CI cycles before they beat the baselines.

### COLEMAN (Prado Lima & Vergilio 2022) [repo-only]

* **Name.** "Combinatorial VOlatiLE Multi-Armed BANdit" for test prioritisation in CI, where test
  cases appear and disappear between cycles.
* **Policies named in the repository:** ε-greedy, UCB and FRRMAB. FRRMAB adapts the use of older
  feedback through windows, discounting or rank-based credit.
* **Rewards named:** RNFail and TimeRank.
* Exact formulas, parameters and results of the TSE paper were **not verified**.

## Comparison with CAVER v0.6 / C2 / L1 (and the v0.10 findings)

| | key assumption | mathematical idea | implementation complexity | difference from CAVER v0.6 / C2 / L1 | applicable to CAVER | hard to apply |
|---|---|---|---|---|---|---|
| **GLR-klUCB** | piecewise-stationary; changes large and spaced (Assumption 4); long horizon | Bernoulli GLR scan with threshold β(n,δ); forced exploration α_k; local or global restart | low–moderate; O(n) per test (Δs/Δn subsampling) | v0.6 uses a two-batch z heuristic plus local reset. v0.8's GLR gate (hypothesis A) **almost never fired** (0–5% detection) at our scale. C2/L1 have no forced-exploration schedule. | forced-exploration schedule; global vs local restart; a GLR test on **pooled** evidence instead of per arm | our evaluation horizon is 90 probes with about 15 per arm; detection power was measured low in v0.8 |
| **ADR-bandit** | **global** changes (arms move together); stationary optimality | ADWIN window shrink/reset (Hoeffding ε_cut); TS/KL-UCB on windowed counts; monitoring arms instead of forced exploration | moderate (all splits; O(W) per step) | CAVER detects per arm and resets locally. ADR's reset is triggered by any arm, and the paper argues no forced exploration is needed under global change | our shifts *are* coordinated (a cohort switch moves many arms), so **a global detector on pooled evidence** and **no exploration cost in stable regimes** address exactly v0.10's failure | ε_cut with tiny per-arm windows; the stationary-optimality claim is asymptotic; our reward is novelty, which **depletes** (not stationary even without change) |
| **BOB** | linear bandit; variation budget B_T unknown; long T | meta-EXP3 over SW-UCB window lengths per block; block reward as feedback | moderate | CAVER has a fixed memory and C. L1 used a hand-set gate | a meta-learner choosing among memory lengths or C values (Agent B) | with T_eval = 90 there are very few blocks, so EXP3 cannot learn within one run. Any use is BOB-*inspired*, **not BOB**. |
| **Predictive Sampling** | a known dynamics prior (switching kernel / AR(1)) | sample future rewards; value information by how long it stays useful | high in general; tractable special cases | CAVER weighs all information equally until a reset | the principle: down-weight information that goes stale fast. In our setting novelty depletes predictably once a (case, family) is found. | the dynamics model is unknown; a Bayesian approximation would need an assumed switching rate |
| **Q-gram ART** | tests are sequences with q-gram structure; expensive executions | aggregate q-gram counts; entropy-maximising candidate selection; linear cost | low | CAVER picks one of 6 families per case. It has no explicit diversity objective beyond the per-case `available()` rule | the diversity objective: choose the arm that most increases entropy or coverage of observed outcome **fingerprints** (Agent C) | our action space is tiny (6 arms) and the policy sees only booleans. The q-gram analogue has to be built on (family, outcome) sequences. |
| **RETECS** | CI cycles with test history | RL with history features; failure-count / time-rank rewards | moderate–high (NN) | CAVER's reward is binary novelty or violation | reward design: rank- or time-aware rewards; using failure history | many cycles needed to learn; a 90-probe episode is short |
| **COLEMAN** [repo-only] | volatile arm set (tests added or removed) | MAB policies (ε-greedy, UCB, FRRMAB) with failure-based rewards | low–moderate | CAVER's arm set is fixed (6 families); cases appear and disappear like volatile tests | volatility framing for new cases; FRRMAB-style sliding credit | paper details unverified |

**Synthesis for v0.11 (hypotheses, not results).**
1. v0.10 showed the stable/shift trade-off is driven by **exploration spent in stable regimes**.
   ADR-bandit's argument (global changes → no forced exploration, stationary-optimal) matches our
   setting best. This is Agent A's lead.
2. One global switch failed in v0.10 (L1). A **two-memory** model choosing between long and short
   memory per arm by predictive fit avoids a global regime switch. It draws on BOB's meta-selection
   and PS's information-staleness principle (Agent B).
3. The **unique-FALSE_PASS objective is a coverage objective**. Diversity over outcome fingerprints
   (q-gram ART) and novelty depletion may beat reward-mean estimation (Agent C). The definition of
   "unique" has to be audited first: today it counts (case, family) pairs, so the same defect variant
   found in several cases counts several times.
