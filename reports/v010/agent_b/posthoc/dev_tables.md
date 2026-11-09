# Agent B dev tables (salt v010dev, REPLAY)

## Unique FALSE_PASS (mean)

| scenario | CAVER-v0.6 | C9-UCBMean | C10-EvidenceUCB | PH-B1-NoCUSUM | PH-B1-NoEvalStart |
|---|---|---|---|---|---|
| stationary | 11.66 | 11.64 | 11.61 | 11.69 | 11.80 |
| abrupt | 12.37 | 13.30 | 13.42 | 13.28 | 13.11 |
| delayed | 12.20 | 13.07 | 12.88 | 12.64 | 13.29 |
| recovery | 12.45 | 12.65 | 12.70 | 12.75 | 12.71 |
| gradual | 11.92 | 12.76 | 12.54 | 12.45 | 12.90 |
| early | 13.15 | 13.69 | 13.34 | 13.37 | 13.85 |
| double | 11.54 | 12.81 | 12.52 | 12.35 | 12.53 |
| single | 11.70 | 12.29 | 12.12 | 12.12 | 12.79 |
| c_late | 11.12 | 11.72 | 11.49 | 11.36 | 11.74 |
| c_reverse | 9.92 | 10.37 | 10.37 | 10.48 | 10.29 |
| c_oscillate | 11.53 | 12.21 | 11.77 | 11.79 | 12.20 |
| c_uniform | 12.15 | 11.73 | 11.96 | 11.98 | 12.04 |

## Paired Δ unique FALSE_PASS vs CAVER-v0.6 (95% CI)

| scenario | C9-UCBMean | C10-EvidenceUCB | PH-B1-NoCUSUM | PH-B1-NoEvalStart |
|---|---|---|---|---|
| stationary | -0.02 [-0.22, +0.18] | -0.05 [-0.26, +0.16] | +0.03 [-0.18, +0.24] | +0.14 [-0.05, +0.34] |
| abrupt | +0.93 [+0.64, +1.23] | +1.06 [+0.77, +1.35] | +0.92 [+0.62, +1.22] | +0.75 [+0.46, +1.03] |
| delayed | +0.87 [+0.50, +1.25] | +0.68 [+0.30, +1.06] | +0.44 [+0.04, +0.84] | +1.09 [+0.69, +1.50] |
| recovery | +0.19 [-0.19, +0.57] | +0.25 [-0.16, +0.66] | +0.29 [-0.11, +0.70] | +0.26 [-0.12, +0.63] |
| gradual | +0.84 [+0.45, +1.24] | +0.62 [+0.26, +0.99] | +0.53 [+0.15, +0.91] | +0.98 [+0.60, +1.36] |
| early | +0.54 [+0.21, +0.87] | +0.19 [-0.13, +0.51] | +0.22 [-0.11, +0.56] | +0.70 [+0.38, +1.01] |
| double | +1.26 [+0.86, +1.67] | +0.98 [+0.60, +1.36] | +0.81 [+0.43, +1.19] | +0.98 [+0.58, +1.39] |
| single | +0.59 [+0.22, +0.97] | +0.42 [+0.04, +0.80] | +0.42 [+0.05, +0.79] | +1.09 [+0.75, +1.44] |
| c_late | +0.61 [+0.31, +0.90] | +0.38 [+0.10, +0.65] | +0.24 [-0.03, +0.51] | +0.62 [+0.34, +0.90] |
| c_reverse | +0.44 [+0.19, +0.70] | +0.44 [+0.19, +0.70] | +0.56 [+0.31, +0.81] | +0.37 [+0.10, +0.63] |
| c_oscillate | +0.68 [+0.30, +1.06] | +0.24 [-0.14, +0.62] | +0.26 [-0.12, +0.64] | +0.67 [+0.31, +1.03] |
| c_uniform | -0.42 [-0.75, -0.10] | -0.19 [-0.50, +0.12] | -0.18 [-0.49, +0.14] | -0.12 [-0.44, +0.20] |

## Paired Δ unique FALSE_PASS vs C9-UCBMean (95% CI)

| scenario | CAVER-v0.6 | C10-EvidenceUCB | PH-B1-NoCUSUM | PH-B1-NoEvalStart |
|---|---|---|---|---|
| stationary | +0.02 [-0.18, +0.22] | -0.03 [-0.25, +0.19] | +0.05 [-0.17, +0.27] | +0.16 [-0.03, +0.36] |
| abrupt | -0.93 [-1.23, -0.64] | +0.12 [-0.13, +0.38] | -0.02 [-0.29, +0.26] | -0.19 [-0.47, +0.10] |
| delayed | -0.87 [-1.25, -0.50] | -0.20 [-0.57, +0.17] | -0.43 [-0.83, -0.04] | +0.22 [-0.18, +0.62] |
| recovery | -0.19 [-0.57, +0.19] | +0.06 [-0.37, +0.49] | +0.10 [-0.34, +0.54] | +0.06 [-0.36, +0.48] |
| gradual | -0.84 [-1.24, -0.45] | -0.22 [-0.61, +0.17] | -0.31 [-0.70, +0.08] | +0.14 [-0.21, +0.48] |
| early | -0.54 [-0.87, -0.21] | -0.35 [-0.68, -0.03] | -0.32 [-0.65, +0.02] | +0.16 [-0.15, +0.47] |
| double | -1.26 [-1.67, -0.86] | -0.29 [-0.68, +0.10] | -0.46 [-0.86, -0.06] | -0.28 [-0.71, +0.15] |
| single | -0.59 [-0.97, -0.22] | -0.17 [-0.54, +0.20] | -0.17 [-0.54, +0.20] | +0.50 [+0.11, +0.89] |
| c_late | -0.61 [-0.90, -0.31] | -0.23 [-0.52, +0.06] | -0.36 [-0.65, -0.08] | +0.01 [-0.30, +0.33] |
| c_reverse | -0.44 [-0.70, -0.19] | +0.00 [-0.25, +0.25] | +0.12 [-0.15, +0.38] | -0.08 [-0.33, +0.18] |
| c_oscillate | -0.68 [-1.06, -0.30] | -0.44 [-0.83, -0.05] | -0.42 [-0.81, -0.04] | -0.01 [-0.38, +0.36] |
| c_uniform | +0.42 [+0.10, +0.75] | +0.23 [-0.07, +0.53] | +0.25 [-0.06, +0.56] | +0.31 [-0.03, +0.65] |

## Candidates: paired Δ unique FALSE_PASS vs other references

| scenario | candidate | vs UCB1 | vs Random | vs SW-UCB | vs D-UCB |
|---|---|---|---|---|---|
| stationary | C10-EvidenceUCB | – | – | – | – |
| stationary | PH-B1-NoCUSUM | – | – | – | – |
| stationary | PH-B1-NoEvalStart | – | – | – | – |
| abrupt | C10-EvidenceUCB | – | – | – | – |
| abrupt | PH-B1-NoCUSUM | – | – | – | – |
| abrupt | PH-B1-NoEvalStart | – | – | – | – |
| delayed | C10-EvidenceUCB | – | – | – | – |
| delayed | PH-B1-NoCUSUM | – | – | – | – |
| delayed | PH-B1-NoEvalStart | – | – | – | – |
| recovery | C10-EvidenceUCB | – | – | – | – |
| recovery | PH-B1-NoCUSUM | – | – | – | – |
| recovery | PH-B1-NoEvalStart | – | – | – | – |
| gradual | C10-EvidenceUCB | – | – | – | – |
| gradual | PH-B1-NoCUSUM | – | – | – | – |
| gradual | PH-B1-NoEvalStart | – | – | – | – |
| early | C10-EvidenceUCB | – | – | – | – |
| early | PH-B1-NoCUSUM | – | – | – | – |
| early | PH-B1-NoEvalStart | – | – | – | – |
| double | C10-EvidenceUCB | – | – | – | – |
| double | PH-B1-NoCUSUM | – | – | – | – |
| double | PH-B1-NoEvalStart | – | – | – | – |
| single | C10-EvidenceUCB | – | – | – | – |
| single | PH-B1-NoCUSUM | – | – | – | – |
| single | PH-B1-NoEvalStart | – | – | – | – |
| c_late | C10-EvidenceUCB | – | – | – | – |
| c_late | PH-B1-NoCUSUM | – | – | – | – |
| c_late | PH-B1-NoEvalStart | – | – | – | – |
| c_reverse | C10-EvidenceUCB | – | – | – | – |
| c_reverse | PH-B1-NoCUSUM | – | – | – | – |
| c_reverse | PH-B1-NoEvalStart | – | – | – | – |
| c_oscillate | C10-EvidenceUCB | – | – | – | – |
| c_oscillate | PH-B1-NoCUSUM | – | – | – | – |
| c_oscillate | PH-B1-NoEvalStart | – | – | – | – |
| c_uniform | C10-EvidenceUCB | – | – | – | – |
| c_uniform | PH-B1-NoCUSUM | – | – | – | – |
| c_uniform | PH-B1-NoEvalStart | – | – | – | – |

## Recovery steps (restricted mean; censoring rate; KM median) and Δ

| scenario | policy | recovery | censored | KM median | Δ vs v0.6 | Δ vs C2 |
|---|---|---|---|---|---|---|
| abrupt | CAVER-v0.6 | 16.62 | 0.000 | 14.0 | – | +5.87 [+4.32, +7.42] |
| abrupt | C9-UCBMean | 10.75 | 0.000 | 9.0 | -5.87 [-7.42, -4.32] | – |
| abrupt | C10-EvidenceUCB | 9.96 | 0.000 | 6.0 | -6.66 [-8.28, -5.04] | -0.79 [-2.04, +0.45] |
| abrupt | PH-B1-NoCUSUM | 10.23 | 0.000 | 6.0 | -6.39 [-8.05, -4.73] | -0.52 [-1.81, +0.77] |
| abrupt | PH-B1-NoEvalStart | 13.86 | 0.000 | 12.0 | -2.76 [-4.38, -1.13] | +3.11 [+1.81, +4.42] |
| delayed | CAVER-v0.6 | 16.00 | 0.033 | 13.0 | – | +2.51 [+0.83, +4.18] |
| delayed | C9-UCBMean | 13.49 | 0.017 | 11.0 | -2.51 [-4.18, -0.83] | – |
| delayed | C10-EvidenceUCB | 15.59 | 0.030 | 13.0 | -0.41 [-2.06, +1.25] | +2.10 [+0.71, +3.49] |
| delayed | PH-B1-NoCUSUM | 17.25 | 0.033 | 15.0 | +1.26 [-0.46, +2.98] | +3.76 [+2.30, +5.22] |
| delayed | PH-B1-NoEvalStart | 15.99 | 0.023 | 14.0 | -0.01 [-1.56, +1.55] | +2.50 [+1.09, +3.91] |
| recovery | CAVER-v0.6 | 18.16 | 0.073 | 12.0 | – | +5.65 [+3.64, +7.66] |
| recovery | C9-UCBMean | 12.51 | 0.020 | 10.0 | -5.65 [-7.66, -3.64] | – |
| recovery | C10-EvidenceUCB | 16.27 | 0.040 | 13.0 | -1.89 [-4.01, +0.23] | +3.77 [+2.08, +5.45] |
| recovery | PH-B1-NoCUSUM | 17.85 | 0.057 | 14.0 | -0.31 [-2.58, +1.96] | +5.34 [+3.39, +7.29] |
| recovery | PH-B1-NoEvalStart | 16.08 | 0.043 | 13.0 | -2.08 [-4.29, +0.13] | +3.57 [+1.83, +5.32] |
| gradual | CAVER-v0.6 | 27.47 | 0.020 | 26.0 | – | +3.67 [+0.95, +6.39] |
| gradual | C9-UCBMean | 23.80 | 0.007 | 20.0 | -3.67 [-6.39, -0.95] | – |
| gradual | C10-EvidenceUCB | 27.20 | 0.017 | 25.0 | -0.27 [-2.83, +2.29] | +3.40 [+0.98, +5.83] |
| gradual | PH-B1-NoCUSUM | 29.30 | 0.027 | 26.0 | +1.84 [-0.79, +4.46] | +5.51 [+2.99, +8.02] |
| gradual | PH-B1-NoEvalStart | 28.84 | 0.017 | 25.0 | +1.37 [-1.35, +4.10] | +5.04 [+2.48, +7.60] |
| early | CAVER-v0.6 | 15.52 | 0.000 | 11.0 | – | +5.12 [+3.48, +6.76] |
| early | C9-UCBMean | 10.40 | 0.000 | 8.0 | -5.12 [-6.76, -3.48] | – |
| early | C10-EvidenceUCB | 12.44 | 0.000 | 9.0 | -3.08 [-4.73, -1.43] | +2.04 [+0.72, +3.36] |
| early | PH-B1-NoCUSUM | 13.11 | 0.000 | 9.0 | -2.41 [-4.13, -0.69] | +2.71 [+1.32, +4.11] |
| early | PH-B1-NoEvalStart | 14.12 | 0.000 | 13.0 | -1.40 [-3.01, +0.21] | +3.72 [+2.41, +5.04] |
| double | CAVER-v0.6 | 15.07 | 0.240 | 13.0 | – | +3.21 [+2.33, +4.08] |
| double | C9-UCBMean | 11.87 | 0.140 | 10.0 | -3.21 [-4.08, -2.33] | – |
| double | C10-EvidenceUCB | 14.05 | 0.173 | 12.0 | -1.02 [-1.93, -0.12] | +2.18 [+1.39, +2.98] |
| double | PH-B1-NoCUSUM | 14.09 | 0.197 | 12.0 | -0.98 [-1.87, -0.10] | +2.22 [+1.44, +3.00] |
| double | PH-B1-NoEvalStart | 14.62 | 0.187 | 13.0 | -0.46 [-1.38, +0.46] | +2.75 [+1.93, +3.57] |
| single | CAVER-v0.6 | 21.43 | 0.050 | 19.0 | – | +6.78 [+4.72, +8.84] |
| single | C9-UCBMean | 14.65 | 0.010 | 11.0 | -6.78 [-8.84, -4.72] | – |
| single | C10-EvidenceUCB | 19.32 | 0.023 | 17.0 | -2.11 [-4.27, +0.05] | +4.67 [+2.83, +6.51] |
| single | PH-B1-NoCUSUM | 21.16 | 0.020 | 18.0 | -0.27 [-2.53, +1.99] | +6.51 [+4.58, +8.44] |
| single | PH-B1-NoEvalStart | 19.65 | 0.013 | 17.0 | -1.78 [-3.86, +0.30] | +5.00 [+3.34, +6.67] |
| c_late | CAVER-v0.6 | 15.14 | 0.403 | 17.0 | – | +1.54 [+0.58, +2.50] |
| c_late | C9-UCBMean | 13.60 | 0.300 | 14.0 | -1.54 [-2.50, -0.58] | – |
| c_late | C10-EvidenceUCB | 14.71 | 0.323 | 16.0 | -0.43 [-1.32, +0.46] | +1.11 [+0.22, +2.00] |
| c_late | PH-B1-NoCUSUM | 16.20 | 0.463 | 19.0 | +1.06 [+0.19, +1.92] | +2.60 [+1.76, +3.44] |
| c_late | PH-B1-NoEvalStart | 14.55 | 0.367 | 16.0 | -0.59 [-1.50, +0.32] | +0.95 [+0.05, +1.84] |
| c_reverse | CAVER-v0.6 | 26.15 | 0.003 | 24.0 | – | +3.12 [+0.91, +5.34] |
| c_reverse | C9-UCBMean | 23.03 | 0.003 | 20.0 | -3.12 [-5.34, -0.91] | – |
| c_reverse | C10-EvidenceUCB | 18.59 | 0.003 | 16.0 | -7.56 [-9.99, -5.13] | -4.44 [-6.49, -2.38] |
| c_reverse | PH-B1-NoCUSUM | 20.61 | 0.000 | 17.0 | -5.54 [-8.06, -3.03] | -2.42 [-4.60, -0.24] |
| c_reverse | PH-B1-NoEvalStart | 25.25 | 0.000 | 23.0 | -0.90 [-3.03, +1.23] | +2.22 [+0.25, +4.19] |
| c_oscillate | CAVER-v0.6 | 9.08 | 0.860 | 8.0 | – | +0.24 [-0.06, +0.53] |
| c_oscillate | C9-UCBMean | 8.84 | 0.787 | 8.0 | -0.24 [-0.53, +0.06] | – |
| c_oscillate | C10-EvidenceUCB | 9.32 | 0.840 | 9.0 | +0.24 [-0.04, +0.52] | +0.48 [+0.19, +0.76] |
| c_oscillate | PH-B1-NoCUSUM | 9.20 | 0.840 | 9.0 | +0.12 [-0.16, +0.39] | +0.35 [+0.06, +0.64] |
| c_oscillate | PH-B1-NoEvalStart | 9.44 | 0.847 | 9.0 | +0.36 [+0.08, +0.65] | +0.60 [+0.30, +0.90] |
| c_uniform | CAVER-v0.6 | 30.32 | 0.133 | 26.0 | – | +4.71 [+2.05, +7.37] |
| c_uniform | C9-UCBMean | 25.61 | 0.093 | 20.0 | -4.71 [-7.37, -2.05] | – |
| c_uniform | C10-EvidenceUCB | 29.34 | 0.107 | 25.0 | -0.98 [-3.51, +1.54] | +3.72 [+1.00, +6.45] |
| c_uniform | PH-B1-NoCUSUM | 29.97 | 0.120 | 26.0 | -0.35 [-2.84, +2.14] | +4.36 [+1.59, +7.13] |
| c_uniform | PH-B1-NoEvalStart | 29.96 | 0.100 | 26.0 | -0.36 [-2.96, +2.25] | +4.35 [+1.87, +6.83] |

## False-alarm rate, exploration entropy, CPU µs/probe

| scenario | policy | false-alarm rate | alarm rate | entropy | CPU µs/probe |
|---|---|---|---|---|---|
| stationary | CAVER-v0.6 | 0.140 | 0.140 | 0.942 | 9.5 |
| stationary | C9-UCBMean | 0.147 | 0.147 | 0.948 | 9.1 |
| stationary | C10-EvidenceUCB | 0.160 | 0.160 | 0.944 | 11.1 |
| stationary | PH-B1-NoCUSUM | 0.170 | 0.170 | 0.938 | 11.3 |
| stationary | PH-B1-NoEvalStart | 0.183 | 0.183 | 0.939 | 11.1 |
| abrupt | CAVER-v0.6 | – | 0.530 | 0.951 | 9.4 |
| abrupt | C9-UCBMean | – | 0.583 | 0.948 | 9.2 |
| abrupt | C10-EvidenceUCB | – | 0.600 | 0.942 | 11.2 |
| abrupt | PH-B1-NoCUSUM | – | 0.607 | 0.938 | 11.3 |
| abrupt | PH-B1-NoEvalStart | – | 0.593 | 0.941 | 11.2 |
| delayed | CAVER-v0.6 | 0.083 | 0.340 | 0.857 | 10.9 |
| delayed | C9-UCBMean | 0.093 | 0.467 | 0.909 | 10.4 |
| delayed | C10-EvidenceUCB | 0.103 | 0.403 | 0.888 | 12.7 |
| delayed | PH-B1-NoCUSUM | 0.107 | 0.373 | 0.872 | 12.9 |
| delayed | PH-B1-NoEvalStart | 0.103 | 0.380 | 0.875 | 12.9 |
| recovery | CAVER-v0.6 | 0.037 | 0.253 | 0.808 | 10.6 |
| recovery | C9-UCBMean | 0.067 | 0.383 | 0.890 | 10.2 |
| recovery | C10-EvidenceUCB | 0.073 | 0.350 | 0.851 | 12.4 |
| recovery | PH-B1-NoCUSUM | 0.070 | 0.343 | 0.832 | 12.8 |
| recovery | PH-B1-NoEvalStart | 0.043 | 0.333 | 0.838 | 12.9 |
| gradual | CAVER-v0.6 | 0.037 | 0.293 | 0.855 | 12.6 |
| gradual | C9-UCBMean | 0.017 | 0.410 | 0.913 | 11.8 |
| gradual | C10-EvidenceUCB | 0.033 | 0.373 | 0.883 | 14.4 |
| gradual | PH-B1-NoCUSUM | 0.033 | 0.373 | 0.870 | 14.7 |
| gradual | PH-B1-NoEvalStart | 0.033 | 0.380 | 0.870 | 14.5 |
| early | CAVER-v0.6 | 0.003 | 0.483 | 0.927 | 8.4 |
| early | C9-UCBMean | 0.007 | 0.603 | 0.941 | 8.1 |
| early | C10-EvidenceUCB | 0.010 | 0.530 | 0.936 | 9.9 |
| early | PH-B1-NoCUSUM | 0.010 | 0.547 | 0.931 | 10.0 |
| early | PH-B1-NoEvalStart | 0.007 | 0.540 | 0.928 | 10.3 |
| double | CAVER-v0.6 | 0.063 | 0.270 | 0.817 | 9.8 |
| double | C9-UCBMean | 0.073 | 0.377 | 0.900 | 9.6 |
| double | C10-EvidenceUCB | 0.057 | 0.320 | 0.868 | 11.7 |
| double | PH-B1-NoCUSUM | 0.057 | 0.290 | 0.847 | 11.9 |
| double | PH-B1-NoEvalStart | 0.080 | 0.330 | 0.856 | 12.0 |
| single | CAVER-v0.6 | 0.050 | 0.507 | 0.873 | 8.9 |
| single | C9-UCBMean | 0.040 | 0.563 | 0.920 | 8.6 |
| single | C10-EvidenceUCB | 0.060 | 0.530 | 0.906 | 10.5 |
| single | PH-B1-NoCUSUM | 0.060 | 0.523 | 0.895 | 11.0 |
| single | PH-B1-NoEvalStart | 0.043 | 0.563 | 0.892 | 10.9 |
| c_late | CAVER-v0.6 | 0.113 | 0.167 | 0.878 | 8.6 |
| c_late | C9-UCBMean | 0.123 | 0.243 | 0.902 | 8.4 |
| c_late | C10-EvidenceUCB | 0.120 | 0.220 | 0.887 | 10.2 |
| c_late | PH-B1-NoCUSUM | 0.123 | 0.213 | 0.870 | 10.5 |
| c_late | PH-B1-NoEvalStart | 0.133 | 0.237 | 0.879 | 10.3 |
| c_reverse | CAVER-v0.6 | – | 0.617 | 0.952 | 8.4 |
| c_reverse | C9-UCBMean | – | 0.667 | 0.948 | 8.1 |
| c_reverse | C10-EvidenceUCB | – | 0.650 | 0.947 | 9.9 |
| c_reverse | PH-B1-NoCUSUM | – | 0.653 | 0.938 | 10.2 |
| c_reverse | PH-B1-NoEvalStart | – | 0.650 | 0.946 | 10.2 |
| c_oscillate | CAVER-v0.6 | 0.013 | 0.247 | 0.855 | 9.7 |
| c_oscillate | C9-UCBMean | 0.020 | 0.357 | 0.909 | 9.2 |
| c_oscillate | C10-EvidenceUCB | 0.013 | 0.310 | 0.887 | 11.2 |
| c_oscillate | PH-B1-NoCUSUM | 0.013 | 0.290 | 0.870 | 11.7 |
| c_oscillate | PH-B1-NoEvalStart | 0.013 | 0.287 | 0.873 | 11.7 |
| c_uniform | CAVER-v0.6 | 0.050 | 0.197 | 0.861 | 9.5 |
| c_uniform | C9-UCBMean | 0.060 | 0.237 | 0.917 | 9.0 |
| c_uniform | C10-EvidenceUCB | 0.050 | 0.193 | 0.890 | 10.9 |
| c_uniform | PH-B1-NoCUSUM | 0.050 | 0.197 | 0.878 | 11.3 |
| c_uniform | PH-B1-NoEvalStart | 0.057 | 0.187 | 0.875 | 11.3 |

## Candidate diagnostics (descriptive)

| scenario | candidate | mean eval C | CUSUM trigger rate | mean CUSUM events | alarm-event rate | mean p0 |
|---|---|---|---|---|---|---|
| stationary | C10-EvidenceUCB | 0.412 | 0.410 | 0.55 | 0.160 | 0.118 |
| stationary | PH-B1-NoCUSUM | 0.389 | 0.000 | 0.00 | 0.170 | 0.118 |
| stationary | PH-B1-NoEvalStart | 0.331 | 0.453 | 0.61 | 0.183 | 0.118 |
| abrupt | C10-EvidenceUCB | 0.438 | 0.427 | 0.57 | 0.600 | 0.120 |
| abrupt | PH-B1-NoCUSUM | 0.415 | 0.000 | 0.00 | 0.607 | 0.120 |
| abrupt | PH-B1-NoEvalStart | 0.368 | 0.450 | 0.63 | 0.593 | 0.120 |
| delayed | C10-EvidenceUCB | 0.430 | 0.483 | 0.66 | 0.403 | 0.120 |
| delayed | PH-B1-NoCUSUM | 0.401 | 0.000 | 0.00 | 0.373 | 0.120 |
| delayed | PH-B1-NoEvalStart | 0.345 | 0.473 | 0.63 | 0.380 | 0.120 |
| recovery | C10-EvidenceUCB | 0.429 | 0.467 | 0.63 | 0.350 | 0.120 |
| recovery | PH-B1-NoCUSUM | 0.401 | 0.000 | 0.00 | 0.343 | 0.120 |
| recovery | PH-B1-NoEvalStart | 0.347 | 0.490 | 0.65 | 0.333 | 0.120 |
| gradual | C10-EvidenceUCB | 0.424 | 0.423 | 0.56 | 0.373 | 0.120 |
| gradual | PH-B1-NoCUSUM | 0.399 | 0.000 | 0.00 | 0.373 | 0.120 |
| gradual | PH-B1-NoEvalStart | 0.346 | 0.507 | 0.63 | 0.380 | 0.120 |
| early | C10-EvidenceUCB | 0.440 | 0.480 | 0.64 | 0.530 | 0.122 |
| early | PH-B1-NoCUSUM | 0.412 | 0.000 | 0.00 | 0.547 | 0.122 |
| early | PH-B1-NoEvalStart | 0.364 | 0.443 | 0.61 | 0.540 | 0.122 |
| double | C10-EvidenceUCB | 0.428 | 0.483 | 0.66 | 0.320 | 0.120 |
| double | PH-B1-NoCUSUM | 0.398 | 0.000 | 0.00 | 0.290 | 0.120 |
| double | PH-B1-NoEvalStart | 0.350 | 0.497 | 0.69 | 0.330 | 0.120 |
| single | C10-EvidenceUCB | 0.439 | 0.480 | 0.67 | 0.530 | 0.120 |
| single | PH-B1-NoCUSUM | 0.410 | 0.000 | 0.00 | 0.523 | 0.120 |
| single | PH-B1-NoEvalStart | 0.359 | 0.490 | 0.64 | 0.563 | 0.120 |
| c_late | C10-EvidenceUCB | 0.418 | 0.527 | 0.68 | 0.220 | 0.120 |
| c_late | PH-B1-NoCUSUM | 0.390 | 0.000 | 0.00 | 0.213 | 0.120 |
| c_late | PH-B1-NoEvalStart | 0.335 | 0.533 | 0.73 | 0.237 | 0.120 |
| c_reverse | C10-EvidenceUCB | 0.472 | 0.733 | 1.45 | 0.650 | 0.156 |
| c_reverse | PH-B1-NoCUSUM | 0.419 | 0.000 | 0.00 | 0.653 | 0.156 |
| c_reverse | PH-B1-NoEvalStart | 0.414 | 0.767 | 1.47 | 0.650 | 0.156 |
| c_oscillate | C10-EvidenceUCB | 0.427 | 0.477 | 0.69 | 0.310 | 0.120 |
| c_oscillate | PH-B1-NoCUSUM | 0.396 | 0.000 | 0.00 | 0.290 | 0.120 |
| c_oscillate | PH-B1-NoEvalStart | 0.344 | 0.470 | 0.65 | 0.287 | 0.120 |
| c_uniform | C10-EvidenceUCB | 0.415 | 0.427 | 0.54 | 0.193 | 0.120 |
| c_uniform | PH-B1-NoCUSUM | 0.391 | 0.000 | 0.00 | 0.197 | 0.120 |
| c_uniform | PH-B1-NoEvalStart | 0.333 | 0.437 | 0.59 | 0.187 | 0.120 |
