"""v0.11 Agent B: dual-memory policies (caver11/agent_b.py). Unit tests, interface rules and
information hygiene. No Claude CLI calls; the only harness run uses the dev salt via the devkit."""
import ast
import inspect
import math
import random
import unittest

from caver5.fixtures import FAMILIES
from caver9.exploration import UCBMeanCAVER
from caver11 import agent_b as B
from caver11 import devkit as dk
from caver9 import evaluation as ev

ALL = B.CANDIDATES + B.ABLATIONS


def drive(cls, seed=0, n_train=90, n_eval=90, n_cases=20, ids=None, p=None):
    """Synthetic driver (no benchmark data): random opaque case IDs and Bernoulli outcomes per arm."""
    pol = cls(random.Random(f'pol{seed}'))
    env = random.Random(f'env{seed}')
    ids = ids or [f'c{i:03d}' for i in range(n_cases)]
    p = p or {f: 0.05 + 0.05 * i for i, f in enumerate(FAMILIES)}
    seen, choices = {}, []
    for step in range(n_train + n_eval):
        if step == n_train:
            pol.begin_evaluation()
        k = env.randrange(len(ids))
        cid = ids[k]
        avail = pol.available(cid)
        arm = pol.select(cid)
        assert arm in avail
        seen.setdefault(cid, set()).add(arm)
        y = env.random() < p[arm]
        v = y or env.random() < 0.1
        pol.update(cid, arm, v, y, learn=True)
        choices.append((k, arm))
    return pol, choices


class C2Quarter(UCBMeanCAVER):
    name = 'test-C2-c0.25'
    C = 0.25


class AgentBTests(unittest.TestCase):
    def test_long_only_ablation_equals_c2_with_c_quarter(self):
        for seed in range(5):
            _, a = drive(B.AblLongOnly, seed)
            _, b = drive(C2Quarter, seed)
            self.assertEqual(a, b)

    def test_available_rule_and_determinism(self):
        for cls in ALL:
            self.assertTrue(issubclass(cls, UCBMeanCAVER))
            _, a = drive(cls, 3)
            _, b = drive(cls, 3)
            self.assertEqual(a, b, cls.name)

    def test_case_ids_are_opaque(self):
        """A bijective renaming of case IDs leaves every choice unchanged (no ID parsing)."""
        other = [f'zz-{i * 7919 % 1000:04d}-q' for i in range(20)]
        for cls in ALL:
            _, a = drive(cls, 4)
            _, b = drive(cls, 4, ids=other)
            self.assertEqual(a, b, cls.name)

    def test_b1_short_weight_rises_after_yield_drop_and_resets(self):
        pol = B.DualMemoryUCB(random.Random(0))
        f = FAMILIES[0]
        for i in range(40):
            pol._predict(f, i % 4 == 0)
            pol._remember(f, i % 4 == 0)
            pol.counts[f] += 1
            pol.successes[f] += int(i % 4 == 0)
            pol.failures[f] += int(i % 4 != 0)
        w_before = pol.weight(f)
        for _ in range(10):
            pol._predict(f, False)
            pol._remember(f, False)
            pol.counts[f] += 1
            pol.failures[f] += 1
        self.assertGreater(pol.weight(f), w_before)
        self.assertLess(pol.short_mean(f), pol.long_mean(f))
        pol._reset_arm(f)
        self.assertEqual(pol.lam[f], pol.lam0)
        self.assertEqual(pol.n_s[f], 0.0)

    def test_b1_fixed_weights(self):
        self.assertEqual(B.AblShortOnly(random.Random(0)).weight(FAMILIES[1]), 1.0)
        self.assertEqual(B.AblFixedBlend(random.Random(0)).weight(FAMILIES[1]), 0.5)
        self.assertAlmostEqual(B.DualMemoryUCB(random.Random(0)).weight(FAMILIES[1]), 0.5)

    def test_b2_coef_range_and_global_discount(self):
        pol, _ = drive(B.PooledDualMemoryUCB, 1)
        self.assertTrue(0.25 <= pol.coef() <= 0.5)
        self.assertAlmostEqual(B.PooledDualMemoryUCB(random.Random(0)).weight(), 0.2)
        n_before = dict(pol.n_s)
        pol._remember(FAMILIES[0], True)
        for f in FAMILIES[1:]:
            self.assertAlmostEqual(pol.n_s[f], 0.95 * n_before[f])
        self.assertAlmostEqual(pol.n_s[FAMILIES[0]], 0.95 * n_before[FAMILIES[0]] + 1)
        self.assertEqual(B.AblB2NoCoupling(random.Random(0)).coef(), 0.25)

    def test_b3_blocks_and_hedge(self):
        pol, _ = drive(B.MemoryHedgeUCB, 2)
        self.assertAlmostEqual(sum(pol.pi), 1.0)
        self.assertTrue(all(x >= 0.1 / 3 - 1e-12 for x in pol.pi))
        self.assertEqual(sum(pol.picks_eval), 9)            # 90 eval probes = 9 blocks of 10
        h = B.MemoryHedgeUCB(random.Random(0))
        h.block_loss = [1.0, 5.0, 5.0]
        h._end_block()
        self.assertGreater(h.pi[0], h.pi[1])
        u = B.AblB3UniformMeta(random.Random(0))
        u.block_loss = [1.0, 5.0, 5.0]
        u._end_block()
        for x in u.pi:
            self.assertAlmostEqual(x, 1 / 3)

    def test_loglik_clipped(self):
        self.assertTrue(math.isfinite(B.loglik(0.0, True)))
        self.assertAlmostEqual(B.loglik(0.25, False), math.log(0.75))

    def test_information_hygiene_update_signature(self):
        """update receives exactly (str, str, bool, bool) plus learn=True, through the shared devkit."""
        table = dk.load_table()
        train, hold, sd = dk.build_schedule(dk.DEV_SALT, 0, 'abrupt')
        for base in B.CANDIDATES:
            calls = []

            class Rec(base):
                def select(self, case_id):
                    assert type(case_id) is str
                    return super().select(case_id)

                def update(self, case_id, arm, violated, newly_found, learn=True):
                    calls.append((type(case_id), type(arm), type(violated), type(newly_found), learn))
                    super().update(case_id, arm, violated, newly_found, learn)
            Rec.name = base.name
            r = dk.run_one_ext(Rec, dk.DEV_SALT, 0, 'abrupt', table, train, hold, sd)
            self.assertEqual(r['selects'], 180)
            self.assertEqual(set(calls), {(str, str, bool, bool, True)})

    def test_no_hidden_information_in_source(self):
        src = inspect.getsource(B)
        tree = ast.parse(src)
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for bad in ('defects', 'observe_outcome', 'split', 'scenario', 'sd', 'events', 'table'):
            self.assertNotIn(bad, names)
        for cls in ALL:
            self.assertFalse(callable(getattr(cls, 'observe_outcome', None)))
        # case_id is only ever forwarded (to available()/select()/update()), never inspected
        for node in ast.walk(tree):
            if isinstance(node, (ast.Subscript, ast.Attribute)):
                inner = node.value
                self.assertFalse(isinstance(inner, ast.Name) and inner.id == 'case_id')

    def test_resolvable_by_devkit(self):
        for cls in ALL:
            self.assertIs(ev.resolve_policy(f'caver11.agent_b:{cls.__name__}'), cls)
        self.assertEqual(len({c.name for c in ALL}), len(ALL))


if __name__ == '__main__':
    unittest.main()
