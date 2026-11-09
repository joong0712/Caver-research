"""v0.11 Agent C: candidate policies (interface, information hygiene, mechanics) and the
independent de-duplication audit (metric recomputation). REPLAY only; never calls the CLI."""
import hashlib
import inspect
import json
import math
import random
import types
import unittest
from pathlib import Path

from caver5.fixtures import FAMILIES
from caver9 import evaluation as ev
from caver9.exploration import UCBMeanCAVER
from caver10 import variants_ext as vx
from caver11 import agent_c as ac
from caver11 import devkit as dk

ROOT = Path(__file__).resolve().parents[1]
SPECS = ('caver11.agent_c:PopBayesUCB', 'caver11.agent_c:PopDivBUCB', 'caver11.agent_c:C2Div')
POLICY_CLASSES = ac.CANDIDATES + ac.POST_HOC


def drive(cls, ids, outcomes, seed=0, eval_at=None):
    """Feed a synthetic stream: ids[i] is the case id at step i, outcomes(i, arm) -> (violated, fp)."""
    p = cls(random.Random(seed))
    seen, arms = set(), []
    for i, cid in enumerate(ids):
        if eval_at is not None and i == eval_at and hasattr(p, 'begin_evaluation'):
            p.begin_evaluation()
            seen = set()
        a = p.select(cid)
        assert a in p.available(cid), (cls.name, i)
        v, fp = outcomes(i, a)
        new = v and (cid, a) not in seen
        if new:
            seen.add((cid, a))
        p.update(cid, a, v, bool(new and fp))
        arms.append(a)
    return p, arms


def synthetic(n=180, n_cases=30, seed=3):
    rng = random.Random(seed)
    order = [rng.randrange(n_cases) for _ in range(n)]
    truth = {(c, f): rng.random() < (0.35 if f in FAMILIES[:2] else 0.08) for c in range(n_cases) for f in FAMILIES}
    return order, (lambda i, a: (truth[(order[i], a)], truth[(order[i], a)]))


class CandidateInterfaceTests(unittest.TestCase):
    def test_resolve_and_names(self):
        names = [ev.resolve_policy(s).name for s in SPECS]
        self.assertEqual(len(set(names)), 3)
        for cls in POLICY_CLASSES:
            self.assertTrue(cls.name)

    def test_available_rule_respected_including_exhaustion(self):
        order, out = synthetic(n_cases=6)       # few cases: exhaustion happens
        for cls in POLICY_CLASSES:
            drive(cls, [f'k{c}' for c in order], out, eval_at=90)

    def test_devkit_runs_candidates_with_exact_budget(self):
        table = dk.load_table()
        for sc in ('stationary', 'f_abrupt_boundary'):
            train, hold, sd = dk.build_schedule(dk.DEV_SALT, 0, sc)
            for spec in SPECS:
                r = dk.run_one_ext(ev.resolve_policy(spec), dk.DEV_SALT, 0, sc, table, train, hold, sd)
                self.assertEqual(r['selects'], 180)
                self.assertEqual(r['rule_violations'], 0)


class InformationHygieneTests(unittest.TestCase):
    FORBIDDEN = {'defects', 'variant', 'scenario', 'salt', 'seed', 'table', 'hold', 'cohort', 'split', 'rsplit',
                 'partition', 'startswith', 'endswith', 'devkit', 're', 'findall', 'AuditTable', 'audit_trace',
                 'audit_metrics', 'run_audit', 'build_schedule', 'Case8', 'ScenarioDef', 'events'}
    ID_NAMES = {'case_id', 'cid', 'c'}

    def _trees(self):
        import ast
        import textwrap
        objs = {ac._DiversityMixin, ac._entropy} | set(POLICY_CLASSES)
        return {o.__name__: ast.parse(textwrap.dedent(inspect.getsource(o))) for o in objs}

    def _violations(self, tree) -> list:
        """AST check: forbidden identifiers/attributes, string operations on case ids (attribute
        access, indexing, int/len/str/ord/hash/float/sorted on a case id), imports."""
        import ast
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in self.FORBIDDEN:
                bad.append(node.id)
            if isinstance(node, ast.Attribute):
                if node.attr in self.FORBIDDEN:
                    bad.append(node.attr)
                if isinstance(node.value, ast.Name) and node.value.id in self.ID_NAMES:
                    bad.append('attribute on a case id')
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in self.ID_NAMES:
                bad.append('indexing a case id')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in (
                    'int', 'len', 'str', 'ord', 'hash', 'float', 'sorted'):
                bad += [node.func.id for a in node.args if isinstance(a, ast.Name) and a.id in self.ID_NAMES]
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bad.append('import')
        return bad

    def test_policy_source_has_no_hidden_information_access(self):
        for name, tree in self._trees().items():
            self.assertEqual(self._violations(tree), [], name)

    def test_hygiene_checker_catches_parsing(self):
        import ast
        for src in ('def select(self, case_id):\n    return case_id.split("-")[2]',
                    'def select(self, case_id):\n    return case_id[-3:]',
                    'def select(self, case_id):\n    return int(case_id)',
                    'def update(self, x):\n    return x.defects'):
            self.assertTrue(self._violations(ast.parse(src)), src)

    def test_policy_code_objects_reference_no_audit_names(self):
        bad = {'AuditTable', 'audit_trace', 'audit_metrics', 'run_audit', 'read_runs', 'dk', 'ev', 'json', 'gzip'}
        for cls in POLICY_CLASSES:
            for klass in cls.__mro__:
                if klass.__module__ != ac.__name__:
                    continue
                for v in vars(klass).values():
                    if isinstance(v, types.FunctionType):
                        self.assertFalse(bad & set(v.__code__.co_names), (cls.name, v.__name__))

    def test_case_ids_are_opaque_keys(self):
        """Renaming case ids (same equality pattern) never changes a decision, including names that
        look like benchmark ids with cohort tags."""
        order, out = synthetic()
        styles = [lambda c: f'c{c:03d}',
                  lambda c: hashlib.sha1(str(c).encode()).hexdigest(),
                  lambda c: f'v011dev-eval-shift-{(7 * c) % 30:03d}' if c % 2 else f'v011dev-eval-base-{c:03d}x']
        for cls in POLICY_CLASSES:
            runs = [drive(cls, [st(c) for c in order], out, eval_at=90)[1] for st in styles]
            self.assertEqual(runs[0], runs[1], cls.name)
            self.assertEqual(runs[0], runs[2], cls.name)

    def test_no_observe_outcome_dependency(self):
        for cls in ac.CANDIDATES:
            self.assertFalse(callable(getattr(cls, 'observe_outcome', None)), cls.name)


class MechanicsTests(unittest.TestCase):
    def test_empty_posterior_is_the_beta_prior(self):
        p = ac.PopBayesUCB(random.Random(0))
        post = p.posterior('x')
        for f in FAMILIES:
            m, sd = post[f]
            self.assertAlmostEqual(m, 0.5)
            self.assertAlmostEqual(sd, math.sqrt(4 / (16 * 5)))      # Beta(2, 2) at LAMBDA = 4

    def test_active_population_window_and_recurrence(self):
        p = ac.PopBayesUCB(random.Random(0))
        a = FAMILIES[0]
        p.update('X', a, True, True)
        self.assertGreater(p.posterior()[a][0], 0.5)
        for i in range(p.W_POP):
            p.update(f'o{i}', FAMILIES[1], False, False)
        self.assertNotIn('X', p.active_cases())
        m_out = p.posterior()[a][0]
        m_back = p.posterior('X')[a][0]          # X is drawn again: its old evidence is back
        self.assertGreater(m_back, m_out)

    def test_repeat_probes_are_not_double_counted(self):
        p = ac.PopBayesUCB(random.Random(0))
        for f in FAMILIES:
            p.update('X', f, False, False)
        p.update('X', FAMILIES[0], True, False)
        self.assertEqual(p.n_all[FAMILIES[0]], 1)
        self.assertEqual(p.case_obs['X'][FAMILIES[0]], 0)

    def test_entropy_gain_prefers_rare_arms(self):
        p = ac.PopDivBUCB(random.Random(0))
        p.found[FAMILIES[0]] = 5
        self.assertLess(p.entropy_gain(FAMILIES[0]), p.entropy_gain(FAMILIES[1]))

    def test_diversity_only_among_near_optimal_arms(self):
        p = ac.PopDivBUCB(random.Random(0))
        a, b, c = FAMILIES[:3]
        p.found[a] = 3
        rates = {a: 0.3, b: 0.3, c: 0.3}
        self.assertEqual(p._div_pick([a, b, c], {a: 0.50, b: 0.47, c: 0.10}, rates), b)
        self.assertEqual(p._div_pick([a, b, c], {a: 0.50, b: 0.40, c: 0.10}, rates), a)
        inf = float('inf')
        self.assertIn(p._div_pick([a, b, c], {a: inf, b: inf, c: 0.9}, rates), (b,))

    def test_begin_evaluation_resets_found_counts(self):
        p = ac.PopDivBUCB(random.Random(0))
        p.update('X', FAMILIES[0], True, True)
        self.assertEqual(p.found[FAMILIES[0]], 1)
        p.begin_evaluation()
        self.assertEqual(sum(p.found.values()), 0)

    def test_c2div_is_c2_plus_tiebreak(self):
        """Same RNG call sequence as C2 (fresh case each step), and every choice lies in C2's
        DELTA-near-optimal set computed on C2Div's own state."""
        rng = random.Random(5)
        q = ac.C2Div(random.Random(1))
        c2 = UCBMeanCAVER(random.Random(1))
        for i in range(150):
            if i == 90:
                q.begin_evaluation()
                c2.begin_evaluation()
            cid = f'u{i}'
            scores = {f: q.score(f) for f in q.available(cid)}
            arm = q.select(cid)
            c2.select(cid)
            top = max(scores.values())
            self.assertTrue(math.isinf(scores[arm]) if math.isinf(top) else scores[arm] >= top - q.DELTA)
            v = rng.random() < 0.3
            q.update(cid, arm, v, v)
            c2.update(cid, arm, v, v)
        self.assertEqual(q.rng.getstate(), c2.rng.getstate())


class AuditTests(unittest.TestCase):
    def test_audit_table_matches_harness_sampling(self):
        doc = json.loads(dk.TABLE_PATH.read_text())
        mine, theirs = ac.AuditTable(doc), vx.ExtOutcomeTable(doc)
        for (f, v) in theirs.rows:
            for k in range(3):
                key = f'v011dev:0:outcome9:eval:x:{f}:{k}'
                o = ev._sample(theirs, f, v, 'crn', None, key)
                self.assertEqual(mine.outcome(f, v, key), (o['violated'], o['false_pass']))
            self.assertEqual(mine.fp_config(f, v), theirs.is_fp_defect(f, v))

    def test_metrics_on_handmade_trace(self):
        T = lambda c, f, v, viol, fp: {'case': c, 'family': f, 'variant': v, 'violated': viol, 'false_pass': fp}
        trace = [T('c1', 'schema', 'top_level', True, True),
                 T('c2', 'schema', 'top_level', True, True),          # new case-level, known variant
                 T('c1', 'schema', 'top_level', True, True),          # case-level duplicate
                 T('c3', 'matcher', 'lowercase_matcher', True, True),
                 T('c4', 'timeout', 'slow_silent', True, False),
                 T('c5', 'timeout', 'slow_silent', True, False),
                 T('c6', 'schema', 'healthy', False, False)]
        hold = [types.SimpleNamespace(id='c1', defects=(('schema', 'top_level'),)),
                types.SimpleNamespace(id='c3', defects=(('matcher', 'lowercase_matcher'), ('timeout', 'slow_deny')))]
        m = ac.audit_metrics(trace, hold, ac.AuditTable.load(dk.TABLE_PATH))
        self.assertEqual(m['unique_false_pass'], 3)
        self.assertEqual(m['unique_variant_false_pass'], 2)
        self.assertEqual(m['violating_probes'], 6)
        self.assertEqual(m['duplicate_rate'], round(1 / 6, 4))
        self.assertEqual(m['variant_duplicate_rate'], 0.5)
        self.assertEqual(m['fp_variant_duplicate_share'], round(1 / 3, 4))
        self.assertEqual(m['available_variant_false_pass'], 3)

    def test_no_violation_run_documents_finding_f2(self):
        m = ac.audit_metrics([], [], ac.AuditTable.load(dk.TABLE_PATH))
        self.assertEqual(m['duplicate_rate'], 0.0)          # devkit convention (F2: should be None)
        self.assertIsNone(m['variant_duplicate_rate'])

    def test_independent_reimplementation_equals_devkit(self):
        table = dk.load_table()
        atab = ac.AuditTable.load(dk.TABLE_PATH)
        for sc in ('stationary', 'delayed', 'c_oscillate', 'f_spike'):
            for seed in (0, 11):
                train, hold, sd = dk.build_schedule(dk.DEV_SALT, seed, sc)
                for spec in ('Random', 'CAVER-v0.6', 'caver9.exploration:UCBMeanCAVER') + SPECS:
                    cls = ev.resolve_policy(spec)
                    a = dk.run_one_ext(cls, dk.DEV_SALT, seed, sc, table, train, hold, sd)
                    b = ac.audit_metrics(ac.audit_trace(cls, dk.DEV_SALT, seed, train, hold, atab), hold, atab)
                    for k in ('unique_false_pass', 'unique_variant_false_pass', 'duplicate_rate'):
                        self.assertEqual(a[k], b[k], (sc, seed, spec, k))
                    self.assertLessEqual(b['unique_variant_false_pass'], b['available_variant_false_pass'])

    def test_recompute_from_runs_synthetic(self):
        rows = []
        vals = {'CAVER-v0.6': [1, 2, 3], 'C9-UCBMean': [2, 2, 2], 'X': [3, 5, 4]}
        for sc, off in (('s1', 0), ('s2', 2)):
            for p, v in vals.items():
                for seed in range(3):
                    rows.append({'scenario': sc, 'policy': p, 'seed': seed, 'unique_false_pass': v[seed] + off,
                                 'unique_variant_false_pass': v[seed], 'duplicate_rate': 0.0})
        r = ac.recompute_from_runs(rows)
        self.assertEqual(r['scenario']['s2']['X']['unique_false_pass'], 6.0)
        self.assertEqual(r['pooled']['X']['diff_unique_false_pass_vs_CAVER-v0.6'][0], 2.0)
        self.assertEqual(r['pooled']['X']['diff_unique_false_pass_vs_C9-UCBMean'][0], 2.0)
        lo, hi = r['pooled']['X']['diff_unique_false_pass_vs_CAVER-v0.6'][1]
        self.assertAlmostEqual(hi - 2.0, 2.0 - lo, places=3)

    def test_kendall_tau(self):
        self.assertEqual(ac.kendall_tau(['a', 'b', 'c'], ['a', 'b', 'c']), 1.0)
        self.assertEqual(ac.kendall_tau(['a', 'b', 'c'], ['c', 'b', 'a']), -1.0)

    def test_saved_reports_are_consistent(self):
        for sub, cand in (('audit_baselines', None), ('dev', 'C11C-PopBUCB-Div')):
            p = ROOT / 'reports/v011/agent_c' / sub
            if not (p / 'dedup_audit.json').exists():
                self.skipTest('reports not generated')
            a = json.loads((p / 'dedup_audit.json').read_text())
            self.assertEqual(a['summary_recompute_mismatches'], [])
            self.assertEqual(a['n_per_run_mismatches'], 0)
            self.assertEqual(a['meta']['n_runs_compared'], 300 * 19 * len(a['pooled_means']))
            if cand:
                s = json.loads((p / 'summary.json').read_text())
                rows = ac.read_runs(p / 'runs.csv.gz')
                rec = ac.recompute_from_runs(rows)
                self.assertEqual(rec['pooled'][cand]['diff_unique_false_pass_vs_CAVER-v0.6'][0],
                                 s['rules'][cand]['pooled_vs_v06'])
                self.assertFalse(any(r['eligible'] for r in s['rules'].values()))


if __name__ == '__main__':
    unittest.main()
