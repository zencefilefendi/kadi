"""Online multinomial logistic regression with AdaGrad on sparse features.

Learns continuously from oracle verdicts (online distillation): every time the
frontier model answers, this model gets one gradient step closer to it.
"""
from __future__ import annotations

import math
from array import array


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
        w = self.w
        for f, v in x.items():
            row = w.get(f)
            if row is not None:
                z = [a + r * v for a, r in zip(z, row)]
        m = max(z)
        e = [math.exp(t - m) for t in z]
        s = sum(e)
        return [t / s for t in e]

    def novelty(self, x: dict[int, float], limit: int | None = None) -> float:
        """Share of the input mass on features never trained on (only features
        with index < `limit`, e.g. the sparse part of a hybrid representation).
        1.0 = completely unlike anything seen; used to refuse OOD/adversarial inputs."""
        tot = unseen = 0.0
        for f, v in x.items():
            if limit is None or f < limit:
                tot += v * v
                if f not in self.w:
                    unseen += v * v
        return unseen / tot if tot else 0.0

    def update(self, x: dict[int, float], y: int, weight: float = 1.0) -> None:
        p = self.predict_proba(x)
        grad = [(p[c] - (1.0 if c == y else 0.0)) * weight for c in range(self.k)]
        for c in range(self.k):
            self.gb[c] += grad[c] ** 2
            self.b[c] -= self.lr * grad[c] / math.sqrt(self.gb[c])
        lr, l2, k, sqrt = self.lr, self.l2, self.k, math.sqrt
        for f, v in x.items():
            row = self.w.get(f) or [0.0] * k
            acc = self.g.get(f) or [1e-8] * k
            g = [gc * v + l2 * r for gc, r in zip(grad, row)]
            acc = [a + gi * gi for a, gi in zip(acc, g)]
            self.w[f] = [r - lr * gi / sqrt(a) for r, gi, a in zip(row, g, acc)]
            self.g[f] = acc
        self.seen += 1

    # -------------------------------------------------------------- snapshots
    def snapshot(self, keep_optimizer: bool = False) -> "OnlineSoftmax":
        """Frozen copy for serving, in O(#features) pointer copies. update()
        replaces rows instead of mutating them, so rows are shared, not copied:
        a snapshot costs a dict copy, and unchanged rows stay identical objects
        (which `pack(base=live)` uses to store only the rows that differ)."""
        s = OnlineSoftmax(self.k, self.lr, self.l2)
        s.w = dict(self.w)
        if keep_optimizer:          # for checkpoints of the live model
            s.g = dict(self.g)
        s.b = list(self.b)
        s.gb = list(self.gb)
        s.seen = self.seen
        return s

    def pack(self, prefix: str, base: "OnlineSoftmax | None" = None, trainable: bool = True):
        """-> (meta, arrays) for kadi.snapshot. With `base`, only rows that are
        not the very same object as in `base` are written."""
        ids = array("q", self.w.keys())
        changed = [f for f, r in self.w.items() if base is None or base.w.get(f) is not r]
        w = array("f")
        for f in changed:
            w.extend(self.w[f])
        arrays = {prefix + "ids": ids, prefix + "changed": array("q", changed), prefix + "w": w}
        if trainable:
            g = array("f")
            for f in changed:
                g.extend(self.g.get(f) or [1e-8] * self.k)
            arrays[prefix + "g"] = g
        meta = {"k": self.k, "lr": self.lr, "l2": self.l2, "seen": self.seen, "b": self.b, "gb": self.gb,
                "trainable": trainable, "based": base is not None}
        return meta, arrays

    @classmethod
    def unpack(cls, meta: dict, arrays: dict, prefix: str, base: "OnlineSoftmax | None" = None):
        k = meta["k"]
        m = cls(k, meta["lr"], meta["l2"])
        m.b, m.gb, m.seen = list(meta["b"]), list(meta["gb"]), meta["seen"]
        changed = arrays[prefix + "changed"]
        w = arrays[prefix + "w"]
        rows = {f: w[i * k:(i + 1) * k].tolist() for i, f in enumerate(changed)}
        if meta.get("based"):
            if base is None:
                raise ValueError("snapshot was packed against a base model")
            m.w = {f: rows[f] if f in rows else base.w[f] for f in arrays[prefix + "ids"]}
        else:
            m.w = rows
        if meta.get("trainable"):
            g = arrays[prefix + "g"]
            m.g = {f: g[i * k:(i + 1) * k].tolist() for i, f in enumerate(changed)}
        return m

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
