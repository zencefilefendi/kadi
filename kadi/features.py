"""Dependency-free text featurizer.

Feature hashing over word uni/bi-grams and character n-grams. Deterministic
across processes (crc32, not Python's salted hash), so saved models reload.
"""
from __future__ import annotations

import math
import re
import unicodedata
import zlib

_WORD = re.compile(r"\w+", re.UNICODE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(text.split())


class HashingFeaturizer:
    def __init__(self, dim_bits: int = 18, char_ngrams: tuple[int, int] = (3, 5),
                 max_chars: int = 4000, max_features: int = 2048):
        self.max_chars = max_chars
        self.max_features = max_features  # bounds model growth, calibration memory, checkpoint size
        self.dim = 1 << dim_bits
        self.mask = self.dim - 1
        self.char_ngrams = char_ngrams

    def _add(self, feats: dict[int, float], token: str, weight: float) -> None:
        h = zlib.crc32(token.encode("utf-8"))
        sign = 1.0 if (h >> 31) & 1 else -1.0
        idx = h & self.mask
        feats[idx] = feats.get(idx, 0.0) + sign * weight

    def __call__(self, text: str) -> dict[int, float]:
        text = normalize(text)[: self.max_chars]
        words = _WORD.findall(text)
        feats: dict[int, float] = {}
        for w in words:
            self._add(feats, "w:" + w, 1.0)
        for a, b in zip(words, words[1:]):
            self._add(feats, "b:" + a + " " + b, 1.0)
        lo, hi = self.char_ngrams
        padded = f" {text} "
        for n in range(lo, hi + 1):
            for i in range(len(padded) - n + 1):
                self._add(feats, "c:" + padded[i : i + n], 0.5)
        if len(feats) > self.max_features:  # keep the strongest, deterministic tie-break
            feats = dict(sorted(feats.items(), key=lambda kv: (-abs(kv[1]), kv[0]))[: self.max_features])
        norm = math.sqrt(sum(v * v for v in feats.values())) or 1.0
        return {k: v / norm for k, v in feats.items() if v}
