"""Optional semantic reflex: sentence embeddings + hashed n-grams.

The core of Kadı is standard-library only. This module is the one place that
uses third-party code, and only when you ask for it:

    pip install "kadi-cascade[embed]"   # fastembed (ONNX runtime, no PyTorch)

    from kadi import Kadi
    from kadi.embed import FastEmbedder, HybridFeaturizer
    kadi = Kadi(oracle, featurizer=HybridFeaturizer(FastEmbedder()))

Why hybrid: embeddings carry meaning ("card hasn't arrived" ~ "where is my
card"), n-grams carry exact surface cues (codes, product names) and feed the
novelty guard. The calibration layer is model-agnostic, so a stronger reflex
can only change *how often* Kadı answers locally, never the error bound.
"""
from __future__ import annotations

import math
import os
from collections import OrderedDict
from typing import Callable, Sequence

from .features import HashingFeaturizer

MULTILINGUAL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"   # 50+ languages incl. Turkish
ENGLISH = "BAAI/bge-small-en-v1.5"


class FastEmbedder:
    """fastembed (ONNX) sentence embedder with an LRU cache. L2-normalised output."""

    def __init__(self, model: str = MULTILINGUAL, cache_dir: str | None = None, cache_size: int = 20_000,
                 threads: int | None = None):
        try:
            from fastembed import TextEmbedding
        except ImportError as e:  # pragma: no cover
            raise ImportError('FastEmbedder needs the optional extra: pip install "kadi-cascade[embed]"') from e
        cache_dir = cache_dir or os.environ.get("KADI_MODEL_CACHE") or os.path.join(
            os.path.expanduser("~"), ".cache", "kadi-models")
        self.name = model
        self._m = TextEmbedding(model, cache_dir=cache_dir, threads=threads)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self.cache_size = cache_size
        self.dim = len(self([" "])[0])

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float] | None] = [self._cache.get(t) for t in texts]
        todo = [t for t, v in zip(texts, out) if v is None]
        if todo:
            for t, v in zip(todo, self._m.embed(todo, batch_size=64)):
                v = [float(a) for a in v]
                n = math.sqrt(sum(a * a for a in v)) or 1.0
                self._cache[t] = [a / n for a in v]
                if len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
            out = [self._cache[t] if v is None else v for t, v in zip(texts, out)]
        return out  # type: ignore[return-value]


class HybridFeaturizer:
    """Sparse hashed n-grams (indices < 2**dim_bits) + a dense embedding block
    appended at indices 2**dim_bits .. 2**dim_bits + d - 1, scaled by `weight`."""

    def __init__(self, embedder: Callable[[Sequence[str]], list[list[float]]], weight: float = 1.0,
                 hashing: HashingFeaturizer | None = None):
        self.embedder = embedder
        self.weight = weight
        self.hashing = hashing or HashingFeaturizer()
        self.hashed_dim = self.hashing.dim    # the novelty guard only looks below this index

    def __call__(self, text: str) -> dict[int, float]:
        x = self.hashing(text)
        off, w = self.hashed_dim, self.weight
        for i, v in enumerate(self.embedder([text])[0]):
            if v:
                x[off + i] = w * v
        return x


class KNNHybridReflex:
    """Reflex factory: online logistic regression on the hybrid features, mixed
    with a k-nearest-neighbour vote over the embeddings of oracle-labelled examples.

    k-NN is the classic strong learner for intents with few examples per label:
    one labelled "where is my card?" immediately helps "my card hasn't come".
    Probabilities need not be calibrated; the conformal / LTT layer calibrates them.

        Kadi(oracle, featurizer=HybridFeaturizer(FastEmbedder()), reflex=KNNHybridReflex())
    """

    def __init__(self, k: int = 10, temperature: float = 0.02, mix: float = 0.8,
                 capacity: int = 20_000, persist: int = 5_000, offset: int | None = None):
        self.k, self.temperature, self.mix = k, temperature, mix
        self.capacity, self.persist = capacity, persist
        self.offset = offset if offset is not None else HashingFeaturizer().dim

    def __call__(self, n_classes: int) -> "_KNNHybridModel":
        return _KNNHybridModel(self, n_classes)

    def from_state(self, s: dict) -> "_KNNHybridModel":
        return _KNNHybridModel.from_state(self, s)

    def unpack(self, meta: dict, arrays: dict, prefix: str, base=None) -> "_KNNHybridModel":
        return _KNNHybridModel.unpack(self, meta, arrays, prefix, base)


class _KNNHybridModel:
    def __init__(self, cfg: KNNHybridReflex, n_classes: int):
        import numpy as np
        from .learner import OnlineSoftmax
        self.np = np
        self.cfg = cfg
        self.k = n_classes
        self.lr = OnlineSoftmax(n_classes)
        self.vecs: list = []      # list of float32 arrays (stacked lazily)
        self.labels: list[int] = []
        self.dim: int | None = None   # embedding width, fixed by the first vector
        self._mat = None

    # -------------------------------------------------------- interface
    @property
    def seen(self) -> int:
        return self.lr.seen

    @property
    def w(self):
        return self.lr.w

    def novelty(self, x, limit=None):
        return self.lr.novelty(x, limit)

    def _emb(self, x):
        off = self.cfg.offset
        v = self.np.zeros(0, dtype=self.np.float32)
        dense = sorted((f - off, val) for f, val in x.items() if f >= off)
        if dense:
            v = self.np.zeros(dense[-1][0] + 1, dtype=self.np.float32)
            for i, val in dense:
                v[i] = val
            n = float(self.np.linalg.norm(v))
            if n:
                v /= n
        if v.size and self.dim is not None and v.size != self.dim:   # trailing zeros were dropped
            v = self.np.pad(v, (0, max(0, self.dim - v.size)))[: self.dim]
        return v

    def predict_proba(self, x):
        p = self.lr.predict_proba(x)
        e = self._emb(x)
        if not self.labels or not e.size:
            return p
        np = self.np
        if self._mat is None or self._mat.shape[0] != len(self.vecs):
            self._mat = np.vstack(self.vecs)
        sims = self._mat @ e
        kk = min(self.cfg.k, sims.size)
        idx = np.argpartition(-sims, kk - 1)[:kk]
        w = np.exp((sims[idx] - sims[idx].max()) / self.cfg.temperature)
        votes = np.full(self.k, 1e-3 / self.k)
        for j, wj in zip(idx, w):
            votes[self.labels[j]] += wj
        votes /= votes.sum()
        m = self.cfg.mix
        return [(1 - m) * a + m * float(b) for a, b in zip(p, votes)]

    def update(self, x, y, weight: float = 1.0):
        self.lr.update(x, y, weight)
        e = self._emb(x)
        if e.size:
            if self.dim is None:
                self.dim = int(e.size)
            self.vecs.append(e)
            self.labels.append(y)
            if len(self.labels) > self.cfg.capacity:
                del self.vecs[0], self.labels[0]
                self._mat = None                      # window slid: rebuild once
            elif self._mat is not None and self._mat.shape[0] == len(self.vecs) - 1:
                self._mat = self._grow(e)            # amortised O(d) append instead of O(n d) vstack

    def _grow(self, e):
        """Append one row to the cached matrix, doubling a backing buffer."""
        np = self.np
        n = self._mat.shape[0]
        buf = getattr(self, "_buf", None)
        if buf is None or buf.shape[0] <= n or buf.shape[1] != e.size or not np.shares_memory(buf, self._mat):
            buf = np.empty((max(64, 2 * (n + 1)), e.size), dtype=np.float32)
            buf[:n] = self._mat
            self._buf = buf
        buf[n] = e
        return buf[: n + 1]

    # ------------------------------------------------------ snapshots
    def snapshot(self, keep_optimizer: bool = False) -> "_KNNHybridModel":
        """Frozen copy for serving: the logistic part is snapshotted, the vector
        store is copied by reference (stored vectors are never mutated)."""
        s = _KNNHybridModel.__new__(_KNNHybridModel)
        s.np, s.cfg, s.k, s.dim = self.np, self.cfg, self.k, self.dim
        s.lr = self.lr.snapshot(keep_optimizer)
        s.vecs, s.labels = list(self.vecs), list(self.labels)
        s._mat = None if self._mat is None else self._mat.copy()   # the live buffer keeps growing
        return s

    def pack(self, prefix: str, base=None, trainable: bool = True):
        from array import array
        meta, arrays = self.lr.pack(prefix + "lr.", base.lr if base is not None else None, trainable)
        keep = self.cfg.persist
        vecs = self.vecs[-keep:]
        vec = array("f")
        if vecs:
            vec.frombytes(self.np.vstack(vecs).astype("<f4").tobytes())
        arrays[prefix + "labels"] = array("i", self.labels[-keep:])
        arrays[prefix + "vecs"] = vec
        return {"kind": "knn_hybrid", "lr": meta, "dim": self.dim}, arrays

    @classmethod
    def unpack(cls, cfg, meta: dict, arrays: dict, prefix: str, base=None) -> "_KNNHybridModel":
        from .learner import OnlineSoftmax
        m = cls(cfg, meta["lr"]["k"])
        m.lr = OnlineSoftmax.unpack(meta["lr"], arrays, prefix + "lr.", base.lr if base is not None else None)
        m.dim = meta.get("dim")
        m.labels = arrays[prefix + "labels"].tolist()
        flat = m.np.frombuffer(arrays[prefix + "vecs"].tobytes(), dtype="<f4")
        if m.dim and flat.size:
            m.vecs = list(flat.reshape(-1, m.dim).copy())
        return m

    # ------------------------------------------------------ persistence (legacy JSON)
    def state(self) -> dict:
        keep = self.cfg.persist
        return {"kind": "knn_hybrid", "lr": self.lr.state(), "labels": self.labels[-keep:],
                "vecs": [[round(float(a), 4) for a in v] for v in self.vecs[-keep:]]}

    @classmethod
    def from_state(cls, cfg: KNNHybridReflex, s: dict) -> "_KNNHybridModel":
        from .learner import OnlineSoftmax
        m = cls(cfg, s["lr"]["k"])
        m.lr = OnlineSoftmax.from_state(s["lr"])
        m.labels = list(s.get("labels", []))
        m.vecs = [m.np.asarray(v, dtype=m.np.float32) for v in s.get("vecs", [])]
        m.dim = len(m.vecs[0]) if m.vecs else None
        return m
