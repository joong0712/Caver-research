"""Generic synthetic Bernoulli check of B1's per-arm weight dynamics (no benchmark code, cases,
weights or tables). Re-created after the dev run so the "prior expectation" numbers quoted in
docs/V011_AGENT_B.md §1 are reproducible; the original scratch script was not committed.

    python3 reports/v011/agent_b/synthetic_prior_check.py
"""
import math
import random


def sim(p_pre, p_post, n_pre=30, n_post=15, g=0.8, m0=1.0, w0=0.5, a=0.9, reps=3000, seed=1):
    rng = random.Random(seed)
    l0 = math.log(w0 / (1 - w0))
    traj = [0.0] * n_post
    for _ in range(reps):
        sL = nL = sS = nS = 0.0
        lam = l0
        for t in range(n_pre + n_post):
            y = rng.random() < (p_pre if t < n_pre else p_post)
            mL = (sL + 1) / (nL + 2)
            mS = (sS + m0 * mL) / (nS + m0)
            ll = (lambda m: math.log(m if y else 1 - m))
            lam = max(-6, min(6, l0 + a * (lam - l0) + ll(mS) - ll(mL)))
            sL, nL = sL + y, nL + 1
            sS, nS = g * sS + y, g * nS + 1
            if t >= n_pre:
                traj[t - n_pre] += 1 / (1 + math.exp(-lam)) / reps
    return traj


if __name__ == '__main__':
    for pre, post in [(0.24, 0.24), (0.24, 0.03), (0.075, 0.2)]:
        tr = sim(pre, post)
        print(f'{pre}->{post}: mean short weight after 1, 6, 15 own pulls:', [round(tr[i], 2) for i in (0, 5, 14)])
