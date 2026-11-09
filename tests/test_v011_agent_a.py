"""v0.11 Agent A: pooled GLR detector, window cut, interface and information hygiene."""
import inspect
import math
import random
import re
import unittest

from caver5.fixtures import FAMILIES
from caver6.policies import CAVERv06
from caver9 import evaluation as ev
from caver11 import agent_a as A
from caver11 import devkit as dk


def feed(det, stream):
    out = []
    for fam, v in stream:
        out.append(det.observe(fam, v))
    return out


class DetectorTests(unittest.TestCase):
    def test_threshold_and_kl(self):
        self.assertAlmostEqual(A.glr_threshold(1, 4.0), 0.5 + 2.0 + 4.0)
        self.assertAlmostEqual(A.glr_threshold(4, 4.0), 2.0 + 4.0 + 4.0)
        self.assertAlmostEqual(A.kl_bern(0.3, 0.3), 0.0, places=12)
        self.assertGreater(A.kl_bern(0.05, 0.3), 0)

    def test_no_alarm_in_training_and_on_constant_stream(self):
        for mode in A.MODES:
            d = A.PooledGLRDetector(4.0, mode=mode)
            rng = random.Random(1)
            tr = [(FAMILIES[i % 6], (i // 6) % 4 == 0) for i in range(90)]
            self.assertTrue(all(r is None for r in feed(d, tr)))
            self.assertEqual(d.step, 0)
            d.begin_evaluation()
            ev_ = [(FAMILIES[i % 6], (i // 6) % 4 == 0) for i in range(90)]   # same pattern as training
            self.assertTrue(all(r is None for r in feed(d, ev_)), mode)
            self.assertEqual(d.alarm_events, [])
            del rng

    def test_strong_global_change_alarms_with_split_near_boundary(self):
        d = A.PooledGLRDetector(4.0, mode='sum')
        feed(d, [(FAMILIES[i % 3], 1) for i in range(90)])        # three arms always violate in training
        d.begin_evaluation()
        res = feed(d, [(FAMILIES[i % 3], 0) for i in range(30)])   # then never
        hits = [(t + 1, r) for t, r in enumerate(res) if r is not None]
        self.assertTrue(hits)
        step, (p, arm) = hits[0]
        self.assertIsNone(arm)                                     # pooled -> global scope
        self.assertEqual(p, 90)                                    # split at the train/eval boundary
        self.assertEqual(d.alarm_events[0]['eval_step'], step)
        self.assertEqual(d.alarm_events[0]['scope'], 'global')

    def test_perarm_mode_is_local(self):
        d = A.PooledGLRDetector(4.0, mode='perarm')
        feed(d, [(FAMILIES[0], 1) for _ in range(40)] + [(FAMILIES[1], 0) for _ in range(40)])
        d.begin_evaluation()
        res = [r for r in feed(d, [(FAMILIES[0], 0) for _ in range(30)]) if r is not None]
        self.assertTrue(res)
        self.assertEqual(res[0][1], 0)
        self.assertEqual(d.alarm_events[0]['scope'], 'local')

    def test_split_positions_respect_min_segments(self):
        d = A.PooledGLRDetector(4.0, mode='sum')
        feed(d, [(FAMILIES[0], 1)] * 20)
        d.begin_evaluation()
        res = feed(d, [(FAMILIES[0], 0)] * 7)                      # fewer than MIN_POST eval obs
        self.assertTrue(all(r is None for r in res))


class WindowTests(unittest.TestCase):
    def _policy(self, cls):
        return cls(random.Random(0))

    def _drive(self, pol, n_train=90, n_eval=40, train_v=True, eval_v=False, train_nf=True):
        for i in range(n_train):
            arm = pol.select(f't{i}')
            pol.update(f't{i}', arm, train_v, train_nf and i % 3 == 0, True)
        pol.begin_evaluation()
        for i in range(n_eval):
            arm = pol.select(f'e{i}')
            pol.update(f'e{i}', arm, eval_v, False, True)

    def test_reset_drops_pre_split_evidence(self):
        pol = self._policy(A.PooledGLRReset)
        self._drive(pol)
        self.assertTrue(pol.detector.alarm_events)
        self.assertEqual(pol.reset_log[0]['scope'], 'global')
        # posterior = carry (0 for A1) + window evidence; all window obs are post-split evaluation obs
        win = {f: [r for a, r in zip(pol.detector.arms, pol.win_rewards) if FAMILIES[a] == f] for f in FAMILIES}
        for f in FAMILIES:
            self.assertEqual(pol.carry_s[f], 0.0)
            self.assertEqual(pol.counts[f], len(win[f]))
            self.assertEqual(pol.successes[f], sum(win[f]))
        self.assertTrue(all(pol.detector.is_eval))

    def test_shrink_keeps_weighted_evidence(self):
        pol = self._policy(A.PooledGLRShrink)
        self._drive(pol)
        self.assertTrue(pol.detector.alarm_events)
        self.assertGreater(sum(pol.carry_s.values()) + sum(pol.carry_f.values()), 0)
        for f in FAMILIES:
            nwin = sum(1 for a in pol.detector.arms if FAMILIES[a] == f)
            self.assertAlmostEqual(pol.counts[f], pol.carry_s[f] + pol.carry_f[f] + nwin)

    def test_no_detect_never_alarms(self):
        pol = self._policy(A.AblNoDetect)
        self._drive(pol)
        self.assertEqual(pol.detector.alarm_events, [])
        self.assertEqual(pol.alarm_count, 0)

    def test_monitor_probe_period(self):
        pol = self._policy(A.PooledGLRMonitor)
        self._drive(pol, n_eval=0)
        sources = []
        for i in range(30):
            arm = pol.select(f'm{i}')
            sources.append(pol.last_source)
            pol.update(f'm{i}', arm, False, False, True)
        self.assertEqual([i + 1 for i, s in enumerate(sources) if s == 'monitor'], [10, 20, 30])

    def test_training_identical_to_v06(self):
        """No sentinel/epsilon/reset in training: selections match CAVER v0.6 exactly."""
        for seed in range(5):
            a, b = CAVERv06(random.Random(seed)), A.PooledGLRReset(random.Random(seed))
            out = random.Random(100 + seed)
            for i in range(90):
                cid = f'c{out.randrange(30):03d}'
                fa, fb = a.select(cid), b.select(cid)
                self.assertEqual(fa, fb, (seed, i))
                v = out.random() < 0.3
                nf = v and out.random() < 0.5
                a.update(cid, fa, v, nf, True)
                b.update(cid, fb, v, nf, True)

    def test_available_rule(self):
        for cls in A.CANDIDATES + A.ABLATIONS:
            pol = cls(random.Random(3))
            pol.begin_evaluation()
            seen = set()
            for k in range(6):
                arm = pol.select('cX')
                self.assertNotIn(arm, seen)
                seen.add(arm)
                pol.update('cX', arm, False, False, True)
            self.assertEqual(seen, set(FAMILIES))
            self.assertIn(pol.select('cX'), FAMILIES)              # exhausted -> any arm allowed


class HygieneTests(unittest.TestCase):
    def test_update_receives_only_str_str_bool_bool(self):
        calls = []
        sel = []

        class Spy(A.PooledGLRReset):
            name = 'A11-Spy'

            def select(self, case_id):
                sel.append(case_id)
                return super().select(case_id)

            def update(self, case_id, arm, violated, newly_found, learn=True):
                calls.append((case_id, arm, violated, newly_found, learn))
                return super().update(case_id, arm, violated, newly_found, learn)

        table = dk.load_table()
        for sc in ('stationary', 'abrupt'):
            train, hold, sd = dk.build_schedule(dk.DEV_SALT, 0, sc)
            r = dk.run_one_ext(Spy, dk.DEV_SALT, 0, sc, table, train, hold, sd)
            self.assertEqual(r['selects'], 180)
        self.assertEqual(len(calls), 360)
        for cid, arm, v, nf, learn in calls:
            self.assertIs(type(cid), str)
            self.assertIs(type(arm), str)
            self.assertIs(type(v), bool)
            self.assertIs(type(nf), bool)
            self.assertIs(learn, True)
            self.assertRegex(cid, r'^c\d{3}$')                    # opaque ids only
            self.assertIn(arm, FAMILIES)
        self.assertTrue(all(re.fullmatch(r'c\d{3}', c) for c in sel))

    def test_source_does_not_parse_case_ids_or_read_hidden_state(self):
        src = inspect.getsource(A)
        self.assertNotRegex(src, r'case_id\s*\[')
        self.assertNotRegex(src, r'case_id\.(split|partition|startswith|endswith|strip)')
        for hidden in (r'\.defects\b', r'\bW_BASE\b', r'\bW_SHIFT\b', r'\bShiftEvent\b', r'\bsd\.',
                       r'\.events\b', r'\bchange_at\b', r'final_env', r'\bfalse_pass\b', r'outcome_table'):
            self.assertNotRegex(src, hidden)
        params = list(inspect.signature(A.WindowedCAVER.update).parameters)
        self.assertEqual(params, ['self', 'case_id', 'arm', 'violated', 'newly_found', 'learn'])
        self.assertEqual(list(inspect.signature(A.WindowedCAVER.select).parameters), ['self', 'case_id'])

    def test_resolvable_by_devkit(self):
        for cls in A.CANDIDATES + A.ABLATIONS:
            self.assertIs(ev.resolve_policy(f'caver11.agent_a:{cls.__name__}'), cls)
        self.assertEqual(len({c.name for c in A.CANDIDATES + A.ABLATIONS}), 7)

    def test_alarm_events_feed_false_alarm_metric(self):
        table = dk.load_table()
        train, hold, sd = dk.build_schedule(dk.DEV_SALT, 2, 'stationary')
        r = dk.run_one_ext(A.AblSensitive, dk.DEV_SALT, 2, 'stationary', table, train, hold, sd)
        self.assertTrue(r['has_detector'])
        self.assertEqual(r['prechange_alarms'] is not None, True)
        self.assertTrue(math.isfinite(r['cpu_us_per_probe']))


if __name__ == '__main__':
    unittest.main()
