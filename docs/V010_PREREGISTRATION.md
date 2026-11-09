# CAVER v0.10: pre-registration of the final evaluation

Committed **before** the final run. Freeze manifest: `reports/v010/freeze_manifest.json`
(sha256 `71a6e1b855bc6943c232092c3a61c30e664aeb14ad134a0a53d37c9d259fda5d`). The final runner (`caver10.final_env final`) recomputes every hash and the
protocol, and refuses to start on any mismatch.

## Candidate (frozen; not changed after the final run)

| item | value |
|---|---|
| class | `caver10.lead_l1:ProfileGatedUCB` (`C10-L1-ProfileGated`), file `caver10/lead_l1.py` |
| hyperparameters | C_TRAIN 0.5, C_LOW 0.25, C_HIGH 0.5, WINDOW 30, MIN_OBS 15, RHO −0.4, HOLD 30. The detector and local reset are inherited from C2. |
| why this candidate | Under V010_DESIGN Amendment 2, none of B1/B2/B3/L1 passed the dev rule, so the candidate with the fewest failed dev checks is frozen: L1 16, B1 17, B2 17, B3 19 (of 86) |
| **status** | **failed dev. Under Amendment 2 it cannot be adopted**, whatever the final run shows. The final run provides confirmatory evidence on new scenarios and new real defect configurations. |

## Final evaluation protocol

| item | value |
|---|---|
| salt | `v010final`, sealed. Needs `CAVER_UNSEAL_V010=1` plus `--unseal`; logged in `reports/v010/final_unseal_log.jsonl`; a second unsealing is refused. |
| seeds | 0–499 (n = 500) |
| scenarios (type) | `f_stat_skew` (stationary), `f_stat_flat` (stationary, near-uniform), `f_flat_shift` (flat shift), `f_abrupt_boundary` (abrupt), `f_abrupt_after` (abrupt), `f_spike` (transient), `f_gradual` (gradual). Definitions are in the manifest's protocol and in `docs/V010_FINAL_ENV.md`. |
| case generator | samples the old 24 and the 12 new defect variants (new-variant share about 45% on the smoke salt) |
| outcome table | `reports/v010/outcome_table_extended_real.json` (sha256 `f4e329642bd429ae6f06de5e4819e4feca2fb06c77341c071f56cd3e9df261b9`): 42 configurations, 96 **real** rows (CLI 2.1.319, subscription OAuth), every configuration measured at least twice, all repetitions agree |
| budget | 90 training + 90 evaluation probes per run (asserted) |
| policies | the candidate plus C2, CAVER-v0.6, UCB1, Random, SW-UCB and Discounted-UCB |
| statistics | paired normal 95% CI (primary for criteria); paired percentile bootstrap (2000 resamples, fixed seed) reported; two-sided p-values with **Holm** adjustment for every reported comparison beyond the criteria |
| recovery (censored) | paired restricted mean (cap = horizon − change + 1), censoring rate, Kaplan–Meier median |

## Bound adoption criteria (V010_DESIGN §5)

| id | scenarios | criterion |
|---|---|---|
| S1 | f_stat_skew, f_stat_flat, f_flat_shift | Δ vs v0.6, CI lower bound > −0.25 |
| S2 | the same | Δ vs C2, CI lower bound > 0 |
| K1 | f_abrupt_boundary, f_abrupt_after | Δ vs C2 lower bound > −0.3, and Δ vs v0.6 lower bound > 0 |
| K2 | the same | recovery Δ vs v0.6 upper bound < 0, and recovery Δ vs C2 upper bound < +1.5 |
| G | all 7 | Δ vs Random, SW-UCB and D-UCB lower bound > 0; Δ vs v0.6 lower bound > −0.5 |
| FA | f_stat_skew, f_stat_flat, f_abrupt_after, f_flat_shift, f_spike, f_gradual | false-alarm rate ≤ v0.6's + 0.05 |
| RV | extended table | every multi-measured configuration agrees across real runs (already passes: 42/42) |

* **Multiplicity:** adoption needs every criterion (intersection–union). Supplementary claims use
  Holm.
* **Verdict rule:** a candidate that failed dev cannot be adopted (Amendment 2). So the verdict is
  **채택 보류 (adoption on hold)**, whether the final criteria pass ("final passed but dev failed;
  replication needed") or fail. v0.6 stays recommended, and neither the result nor the candidate
  is changed.

## Command (run once)

```
CAVER_UNSEAL_V010=1 python3 -m caver10.final_env final --unseal --candidate caver10.lead_l1:ProfileGatedUCB \
  --table reports/v010/outcome_table_extended_real.json --manifest reports/v010/freeze_manifest.json \
  --output reports/v010/final --jobs 2
```

## Replay vs real

The final run is **replay** of real outcomes. 30 of the 42 configurations are the old ones C2 and
the candidates were developed on. The 12 new configurations come from new real runs (R1) that no
candidate was developed on. Seed CIs do not cover uncertainty in the recorded outcomes, which are 2
or more agreeing real runs per configuration.
