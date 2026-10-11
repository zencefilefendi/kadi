"""Benchmark machinery that the published numbers depend on (no downloads)."""
import importlib.util
import math
import os
import random
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "benchmarks"))
spec = importlib.util.spec_from_file_location("bench_run", os.path.join(ROOT, "benchmarks", "run.py"))
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

from kadi import Choice  # noqa: E402
from kadi.oracles import Verdict  # noqa: E402


class TestStats(unittest.TestCase):
    def test_clopper_pearson_upper(self):
        self.assertAlmostEqual(run.cp_upper(0, 10), 1 - 0.05 ** (1 / 10), places=4)   # exact for k = 0
        self.assertAlmostEqual(run.cp_upper(0, 126), 1 - 0.05 ** (1 / 126), places=4)
        self.assertEqual(run.cp_upper(5, 5), 1.0)
        self.assertGreater(run.cp_upper(2, 10), run.cp_upper(1, 10))

    def test_bootstrap_ci_brackets_the_mean(self):
        vals = [0.61, 0.64, 0.66, 0.63, 0.65, 0.62, 0.67, 0.60, 0.64, 0.66]
        lo, hi = run.boot_ci(vals)
        m = sum(vals) / len(vals)
        self.assertLess(lo, m)
        self.assertGreater(hi, m)
        self.assertLess(hi - lo, 0.04)


class TestBaselinePick(unittest.TestCase):
    def test_pick_is_the_loosest_threshold_meeting_the_prefix_risk(self):
        rng = random.Random(0)
        scores = [rng.random() for _ in range(2000)]
        correct = [rng.random() < s for s in scores]      # calibrated toy scorer
        t = run._pick(scores, correct, 0.05)
        risk = sum(1 for s, c in zip(scores, correct) if s >= t and not c) / len(scores)
        self.assertLessEqual(risk, 0.05)
        looser = max(x for x in set(run.GRID) | set(scores) if x < t)
        risk2 = sum(1 for s, c in zip(scores, correct) if s >= looser and not c) / len(scores)
        self.assertGreater(risk2, 0.05)


class TestOracles(unittest.TestCase):
    def test_noisy_oracle_flip_rate_and_determinism(self):
        data = [(f"text {i}", "a") for i in range(20000)]
        o1, meta = run.oracle_labels("noisy:0.05", "x", data, ["a", "b", "c"], "", 1, 0)
        o2, _ = run.oracle_labels("noisy:0.05", "x", data, ["a", "b", "c"], "", 1, 0)
        flips = sum(v != "a" for v in o1.values()) / len(o1)
        self.assertAlmostEqual(flips, 0.05, delta=0.006)
        self.assertEqual(o1, o2)                       # a cached verdict never changes
        self.assertEqual(meta["flip_rate"], 0.05)

    def test_cached_oracle_pays_once(self):
        calls = []

        class Fake:
            name = "fake-model"

            def judge(self, q, text, ctx):
                calls.append(text)
                return Verdict("a", 0.002, 5.0, "fake-model")
        path = os.path.join(tempfile.mkdtemp(), "v.jsonl")
        q = Choice("q", ["a", "b"])
        c = run.CachedOracle(Fake(), path)
        for _ in range(3):
            self.assertEqual(c.judge_cached(q, "hello")["label"], "a")
        self.assertEqual(len(calls), 1)
        self.assertTrue(math.isclose(c.paid_cost, 0.002))
        c2 = run.CachedOracle(Fake(), path)            # survives a restart
        c2.judge_cached(q, "hello")
        self.assertEqual(len(calls), 1)
        c2.judge_cached(q, "hello", sample=1)          # self-consistency samples are distinct keys
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
