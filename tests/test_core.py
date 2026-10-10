import json
import math
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kadi import Binary, Choice, FunctionOracle, Kadi, OracleError, Score  # noqa: E402
from kadi.conformal import AdaptiveConformal  # noqa: E402
from kadi.features import HashingFeaturizer  # noqa: E402
from kadi.learner import OnlineSoftmax  # noqa: E402


class TestPieces(unittest.TestCase):
    def test_featurizer_deterministic_and_normalized(self):
        f = HashingFeaturizer()
        a, b = f("Hello  WORLD"), f("hello world")
        self.assertEqual(a, b)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in a.values())), 1.0, places=6)

    def test_learner_learns(self):
        f, m = HashingFeaturizer(), OnlineSoftmax(2)
        for _ in range(30):
            m.update(f("refund my money"), 0)
            m.update(f("app crashes on start"), 1)
        self.assertGreater(m.predict_proba(f("refund money please"))[0], 0.8)
        self.assertGreater(m.predict_proba(f("crashes on start again"))[1], 0.8)
        m2 = OnlineSoftmax.from_state(m.state())
        self.assertEqual(m.predict_proba(f("x y z")), m2.predict_proba(f("x y z")))

    def test_conformal_uncalibrated_returns_full_set(self):
        c = AdaptiveConformal(0.1, min_calibration=10)
        self.assertEqual(c.prediction_set([0.9, 0.1]), [0, 1])

    def test_conformal_coverage(self):
        rng = random.Random(0)
        c = AdaptiveConformal(0.1, window=2000, gamma=0.0, min_calibration=50)
        proba = lambda x: [x[0], 1 - x[0]]  # noqa: E731  calibrated toy model
        hits = total = 0
        for _ in range(4000):
            p = rng.uniform(0.5, 1.0)
            y = 0 if rng.random() < p else 1
            if c.threshold() is not None:
                total += 1
                hits += y in c.prediction_set([p, 1 - p])
            c.observe({0: p}, [p, 1 - p], y)
        self.assertGreaterEqual(hits / total, 0.88)
        self.assertLessEqual(hits / total, 0.93)

    def test_binom_cdf_exact(self):
        from math import comb
        from kadi.conformal import binom_cdf
        for n, p in ((10, 0.3), (37, 0.05), (200, 0.01)):
            for k in (0, 1, 3, n // 2):
                exact = sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
                self.assertAlmostEqual(binom_cdf(k, n, p), exact, places=10)

    def test_ltt_certificate_is_valid(self):
        """Toy calibrated model: p ~ U(0.5, 1), correct w.p. p, so the true risk at
        threshold lam is (1 - lam)^2. The certificate may fail at most ~delta of the time."""
        from kadi.conformal import LearnThenTest
        rng = random.Random(1)
        alpha, delta, trials, fails, certified = 0.02, 0.1, 300, 0, 0
        for _ in range(trials):
            c = LearnThenTest(alpha, delta, window=500)
            for _ in range(500):
                pm = rng.uniform(0.5, 1.0)
                c.evals.append((pm, rng.random() < pm))
                c.samples.append(({}, 0))
            c._certify()
            if c.lam is not None:
                certified += 1
                fails += (1 - c.lam) ** 2 > alpha
        self.assertGreater(certified, trials * 0.9)
        self.assertLessEqual(fails / trials, delta + 0.03)

    def test_ltt_needs_enough_samples(self):
        from kadi.conformal import LearnThenTest
        c = LearnThenTest(0.01, 0.05)
        self.assertEqual(c.min_samples, 299)  # (1 - 0.01)^n <= 0.05
        with self.assertRaises(ValueError):
            Choice("x", ["a", "b"], policy="ltt", conditional=True)

    def test_mondrian_state_roundtrip(self):
        from kadi.conformal import MondrianConformal, conformal_from_state
        m = MondrianConformal(3, 0.05, min_calibration=2)
        for i in range(9):
            m.observe({i: 1.0}, [0.6, 0.3, 0.1], i % 3)
        m2 = conformal_from_state(json.loads(json.dumps(m.state())))
        self.assertEqual(m2.calibration_size, 9)
        self.assertTrue(m2.calibrated)

    def test_question_validation(self):
        with self.assertRaises(ValueError):
            Choice("x", ["a"])
        with self.assertRaises(ValueError):
            Choice("x", ["a", "a"])
        self.assertEqual(Score("s", 1, 3).options, ("1", "2", "3"))
        with self.assertRaises(ValueError):
            Choice("bad name!", ["a", "b"])
        with self.assertRaises(ValueError):
            Choice("x", ["a", "b"], mode="yolo")


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "k.db")

    def _workload(self, n, rng):
        bank = {"pos": ["love it", "great product", "works perfectly", "amazing support"],
                "neg": ["hate it", "broken again", "terrible support", "waste of money"]}
        for _ in range(n):
            y = rng.choice(["pos", "neg"])
            yield f"{rng.choice(bank[y])} {rng.randint(0, 10**6)}", y

    def test_cascade_goes_local_and_stays_accurate(self):
        q = Choice("sentiment", ["pos", "neg"], target_error=0.05)
        truth = {}
        calls = []
        oracle = FunctionOracle(lambda q_, t, c: (calls.append(1), truth[t])[1], cost_per_call=0.01)
        k = Kadi(oracle, db=self.db, audit_rate=0.0, seed=0)
        rng = random.Random(1)
        wrong = 0
        items = list(self._workload(3000, rng))
        for text, y in items:
            truth[text] = y
            wrong += k.decide(q, text).label != y
        self.assertLess(len(calls), 1200, "most decisions should be local")
        self.assertLess(wrong / len(items), 0.05)
        k.close()

    def test_memory_tier_and_persistence(self):
        q = Binary("spam", "Is it spam?")
        oracle = FunctionOracle(lambda *_: "yes", cost_per_call=0.01)
        k = Kadi(oracle, db=self.db, audit_rate=0.0)
        self.assertEqual(k.decide(q, "buy now").tier, "oracle")
        self.assertEqual(k.decide(q, "  BUY   now ").tier, "memory")
        k.close()
        k2 = Kadi(oracle, db=self.db, audit_rate=0.0)
        self.assertEqual(k2.decide(q, "buy now").tier, "memory")
        k2.close()

    def test_out_of_schema_oracle_rejected(self):
        q = Binary("b", "?")
        k = Kadi(FunctionOracle(lambda *_: "maybe"), db=self.db)
        with self.assertRaises(OracleError):
            k.decide(q, "hello")
        k.close()

    def test_option_change_rejected(self):
        k = Kadi(FunctionOracle(lambda *_: "a"), db=self.db)
        k.decide(Choice("c", ["a", "b"]), "x")
        with self.assertRaises(ValueError):
            k.decide(Choice("c", ["a", "b", "z"]), "y")
        k.close()


if __name__ == "__main__":
    unittest.main()
