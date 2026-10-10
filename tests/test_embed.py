"""Semantic reflex tests. No model download: a deterministic toy embedder stands
in for fastembed. k-NN tests need numpy (installed with the [embed] extra)."""
import importlib.util
import math
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kadi import Choice, FunctionOracle, Kadi  # noqa: E402
from kadi.embed import HybridFeaturizer, KNNHybridReflex  # noqa: E402

HAS_NUMPY = importlib.util.find_spec("numpy") is not None

# Toy "semantic" space: synonyms share a direction, so meaning survives rewording.
CONCEPTS = {"card": 0, "arrive": 1, "refund": 2, "money": 3, "password": 4, "login": 5}
SYNONYMS = {"card": "card", "debit": "card", "visa": "card", "arrive": "arrive", "come": "arrive",
            "delivered": "arrive", "refund": "refund", "reimburse": "refund", "money": "money",
            "cash": "money", "funds": "money", "password": "password", "passcode": "password",
            "login": "login", "signin": "login", "access": "login"}


def toy_embed(texts):
    out = []
    for t in texts:
        v = [0.0] * 8
        for w in t.lower().split():
            c = SYNONYMS.get(w.strip("?.!,"))
            if c:
                v[CONCEPTS[c]] += 1.0
        v[7] = 0.1
        n = math.sqrt(sum(a * a for a in v))
        out.append([a / n for a in v])
    return out


def ticket(rng):
    y = rng.choice(["card_arrival", "refund", "login"])
    pool = {"card_arrival": [["card", "debit", "visa"], ["arrive", "come", "delivered"]],
            "refund": [["refund", "reimburse"], ["money", "cash", "funds"]],
            "login": [["password", "passcode"], ["login", "signin", "access"]]}[y]
    words = [rng.choice(g) for g in pool] + rng.sample(["please", "my", "the", "hi", "still", "not", "why"], 3)
    rng.shuffle(words)
    return " ".join(words) + f" {rng.randint(0, 10**6)}", y


class TestHybridFeaturizer(unittest.TestCase):
    def test_layout_and_novelty_limit(self):
        f = HybridFeaturizer(toy_embed, weight=2.0)
        x = f("where is my visa card")
        dense = {i - f.hashed_dim: v for i, v in x.items() if i >= f.hashed_dim}
        self.assertTrue(dense)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in dense.values())), 2.0, places=6)
        k = Kadi(FunctionOracle(lambda *_: "a"), db=":memory:", featurizer=f)
        self.assertEqual(k.novelty_limit, f.hashed_dim)
        k.close()


@unittest.skipUnless(HAS_NUMPY, "numpy not installed (pip install 'kadi[embed]')")
class TestKNNReflex(unittest.TestCase):
    def test_knn_generalises_across_synonyms(self):
        reflex = KNNHybridReflex(k=5)
        f = HybridFeaturizer(toy_embed)
        m = reflex(3)
        m.update(f("my debit card did not arrive"), 0)
        m.update(f("i want a refund of my money"), 1)
        m.update(f("forgot my password for login"), 2)
        p = m.predict_proba(f("visa still not delivered"))   # no shared surface words with the card example
        self.assertEqual(max(range(3), key=p.__getitem__), 0)

    def test_engine_with_semantic_reflex_and_persistence(self):
        db = os.path.join(tempfile.mkdtemp(), "e.db")
        truth = {}
        q = Choice("intent", ["card_arrival", "refund", "login"], target_error=0.05, policy="ltt")
        mk = lambda: Kadi(FunctionOracle(lambda q_, t, c: truth[t]), db=db, seed=0,  # noqa: E731
                          featurizer=HybridFeaturizer(toy_embed), reflex=KNNHybridReflex())
        k = mk()
        rng = random.Random(0)
        wrong = 0
        for _ in range(1500):
            t, y = ticket(rng)
            truth[t] = y
            wrong += k.decide(q, t).label != y
        st = k.stats()[0]
        self.assertGreater(st["local_rate_recent"], 0.7)
        self.assertLessEqual(wrong / 1500, 0.05)
        k.close()
        k2 = mk()
        k2.register(q)
        self.assertGreater(len(k2._brains["intent"].model.labels), 100)
        k2.close()


if __name__ == "__main__":
    unittest.main()
