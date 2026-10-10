"""Pre-compute and cache sentence embeddings for a benchmark dataset.

Embedding the same text twice is wasted work across 9+ runs per dataset, so
vectors are computed once per (dataset, model) and stored as .npy next to the
dataset cache. Workers memory-map the file and look rows up by text.
"""
from __future__ import annotations

import os

import datasets

MODELS = {
    "bge": "BAAI/bge-small-en-v1.5",
    "minilm": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
}


def path(ds: str, key: str) -> str:
    return os.path.join(datasets.cache_dir(), f"emb-{ds}-{key}.npy")


def ensure(ds: str, key: str) -> str:
    p = path(ds, key)
    if not os.path.exists(p):
        import numpy as np
        from fastembed import TextEmbedding
        texts = sorted({t for t, _ in datasets.load(ds)})
        m = TextEmbedding(MODELS[key], cache_dir=os.path.join(os.path.expanduser("~"), ".cache", "kadi-models"))
        a = np.asarray(list(m.embed(texts, batch_size=128)), dtype=np.float32)
        a /= np.linalg.norm(a, axis=1, keepdims=True)
        np.save(p, a)
    return p


class Lookup:
    """text -> L2-normalised vector, backed by the cached .npy (memory-mapped)."""

    def __init__(self, ds: str, key: str):
        import numpy as np
        self.texts = {t: i for i, t in enumerate(sorted({t for t, _ in datasets.load(ds)}))}
        self.a = np.load(ensure(ds, key), mmap_mode="r")

    def __call__(self, texts):
        return [self.a[self.texts[t]].tolist() for t in texts]
