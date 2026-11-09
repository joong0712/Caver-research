"""Agent A: synthetic calibration of the detector constant X (NOT dev; no devkit, no salt, no table).

Synthetic streams only: 90 training + 90 evaluation (arm, violated) observations, with fixed arm-
selection mixes and generic per-arm violation rates. Two null models:
  iid  : violated ~ Bernoulli(P[arm]) in both phases;
  pool : finite case pools (32 training cases, 28 evaluation cases), each case violating on arm a with
         probability P[a]; an observation draws a random case from the phase's pool. The two pools
         differ by sampling, which mimics the case-pool overdispersion of CAVER schedules.
Change model ("power"): from evaluation step 1 the rates are reversed (a global change).
Output: per mode and X, the share of null runs with >= 1 alarm in 90 evaluation steps (fa), and
under the change the share detected within 90 steps (power) and the median detection step.

Run: python3 reports/v011/agent_a/calibrate_null.py 400 > reports/v011/agent_a/calibrate_null.txt
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from caver11.agent_a import PooledGLRDetector, FAMILIES  # noqa: E402

P = (0.30, 0.22, 0.15, 0.12, 0.10, 0.06)
P_CHG = tuple(reversed(P))
SEL_TR = (0.30, 0.25, 0.15, 0.12, 0.10, 0.08)
SEL_EV = (0.40, 0.30, 0.10, 0.08, 0.07, 0.05)


def pool(rng, n, p):
    return [[int(rng.random() < q) for q in p] for _ in range(n)]


def run(x, model, rng, change_at=None, mode='sum'):
    d = PooledGLRDetector(x, mode=mode)
    tp, ep, cp = pool(rng, 32, P), pool(rng, 28, P), pool(rng, 28, P_CHG)
    for _ in range(90):
        a = rng.choices(range(6), SEL_TR)[0]
        v = rng.choice(tp)[a] if model == 'pool' else int(rng.random() < P[a])
        d.observe(FAMILIES[a], v)
    d.begin_evaluation()
    for t in range(1, 91):
        a = rng.choices(range(6), SEL_EV)[0]
        post = change_at is not None and t > change_at
        if model == 'pool':
            v = rng.choice(cp if post else ep)[a]
        else:
            v = int(rng.random() < (P_CHG if post else P)[a])
        if d.observe(FAMILIES[a], v) is not None:
            return t
    return None


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    print('mode X model fa power median_delay')
    for mode in ('sum', 'resid', 'perarm'):
        for x in (2.0, 2.5, 3.0, 4.0, 5.0):
            for model in ('iid', 'pool'):
                rng = random.Random(f'agentA-calib:{x}:{model}:{mode}')
                fa = sum(run(x, model, rng, mode=mode) is not None for _ in range(n)) / n
                dl = [run(x, model, rng, change_at=0, mode=mode) for _ in range(n // 2)]
                hit = sorted(t for t in dl if t is not None)
                print(mode, x, model, round(fa, 3), round(len(hit) / len(dl), 3),
                      hit[len(hit) // 2] if hit else None, flush=True)


if __name__ == '__main__':
    main()
