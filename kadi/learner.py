"""Online multinomial logistic regression with AdaGrad on sparse features.

Learns continuously from oracle verdicts (online distillation): every time the
frontier model answers, this model gets one gradient step closer to it.
"""
from __future__ import annotations

import math


class OnlineSoftmax:
    def __init__(self, n_classes: int, lr: float = 0.6, l2: float = 1e-5):
        self.k = n_classes
        self.lr = lr
        self.l2 = l2
        self.w: dict[int, list[float]] = {}
        self.g: dict[int, list[float]] = {}  # AdaGrad accumulators
        self.b = [0.0] * n_classes
        self.gb = [1e-8] * n_classes
        self.seen = 0

    def predict_proba(self, x: dict[int, float]) -> list[float]:
        z = list(self.b)
        for f, v in x.items():
            row = self.w.get(f)
            if row is not None:
                for c in range(self.k):
                    z[c] += row[c] * v
        m = max(z)
        e = [math.exp(t - m) for t in z]
        s = sum(e)
        return [t / s for t in e]

    def novelty(self, x: dict[int, float]) -> float:
        """Share of the (L2-normalised) input mass on features never trained on.
        1.0 = completely unlike anything seen; used to refuse OOD/adversarial inputs."""
        return sum(v * v for f, v in x.items() if f not in self.w)

    def update(self, x: dict[int, float], y: int, weight: float = 1.0) -> None:
        p = self.predict_proba(x)
        grad = [(p[c] - (1.0 if c == y else 0.0)) * weight for c in range(self.k)]
        for c in range(self.k):
            self.gb[c] += grad[c] ** 2
            self.b[c] -= self.lr * grad[c] / math.sqrt(self.gb[c])
        for f, v in x.items():
            row = self.w.setdefault(f, [0.0] * self.k)
            acc = self.g.setdefault(f, [1e-8] * self.k)
            for c in range(self.k):
                gc = grad[c] * v + self.l2 * row[c]
                acc[c] += gc * gc
                row[c] -= self.lr * gc / math.sqrt(acc[c])
        self.seen += 1

    def state(self) -> dict:
        return {"k": self.k, "lr": self.lr, "l2": self.l2, "b": self.b, "gb": self.gb,
                "seen": self.seen,
                "w": {str(f): r for f, r in self.w.items()},
                "g": {str(f): r for f, r in self.g.items()}}

    @classmethod
    def from_state(cls, s: dict) -> "OnlineSoftmax":
        m = cls(s["k"], s["lr"], s["l2"])
        m.b, m.gb, m.seen = s["b"], s["gb"], s["seen"]
        m.w = {int(f): r for f, r in s["w"].items()}
        m.g = {int(f): r for f, r in s["g"].items()}
        return m
