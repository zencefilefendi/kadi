"""Conformal prediction: the part that makes Kadı trustworthy.

Instead of "the model is 92% confident" (a number nobody calibrated), Kadı
builds a *prediction set* of labels that contains the oracle's answer with
probability >= 1 - alpha. If that set holds exactly one label, Kadı answers
locally; otherwise it escalates, and escalated answers come from the oracle
itself. So the share of decisions that disagree with the oracle is bounded
by alpha (marginally, under exchangeability).

Getting this right in an online system takes three rules:

1. **Held-out calibration.** Calibration examples are a random sample of the
   stream and are never used to train the model. (Training on them makes
   their scores optimistic; calibrating only on escalated examples is worse,
   because their label is inside the set by construction, so the threshold
   ratchets looser and looser.)
2. **Fresh scores.** The model keeps learning, so stored calibration inputs
   are re-scored with the current model rather than keeping stale scores
   from an early, weaker model.
3. **Adaptive alpha.** Adaptive Conformal Inference (Gibbs & Candès, 2021)
   nudges alpha_t after every calibration example, so long-run miscoverage
   tracks the target under distribution shift.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Callable

Sparse = dict[int, float]
ProbaFn = Callable[[Sparse], list[float]]


def _pack(x: Sparse) -> list:
    return [[k, round(v, 5)] for k, v in x.items()]


def _unpack(p: list) -> Sparse:
    return {int(k): v for k, v in p}


class AdaptiveConformal:
    def __init__(self, target_error: float = 0.05, window: int = 400,
                 gamma: float = 0.005, min_calibration: int = 40):
        if not 0 < target_error < 1:
            raise ValueError("target_error must be in (0, 1)")
        self.target = target_error
        self.alpha_t = target_error
        self.gamma = gamma
        self.min_calibration = min_calibration
        self.samples: deque[tuple[Sparse, int]] = deque(maxlen=window)
        self._sorted: list[float] = []
        self.stale = True
        self.observed = 0
        self.misses = 0

    @property
    def calibrated(self) -> bool:
        return len(self.samples) >= self.min_calibration

    @property
    def calibration_size(self) -> int:
        return len(self.samples)

    def rescore(self, proba: ProbaFn) -> None:
        self._sorted = sorted(1.0 - proba(x)[y] for x, y in self.samples)
        self.stale = False

    def threshold(self) -> float | None:
        """Nonconformity cutoff q; None means 'not calibrated yet'."""
        n = len(self._sorted)
        if n < self.min_calibration:
            return None
        if self.alpha_t <= 0:
            return math.inf
        if self.alpha_t >= 1:
            return -math.inf
        k = math.ceil((n + 1) * (1 - self.alpha_t))
        if k > n:
            return math.inf
        return self._sorted[k - 1]

    def prediction_set(self, probs: list[float]) -> list[int]:
        q = self.threshold()
        if q is None or q == math.inf:
            return list(range(len(probs)))
        return [i for i, p in enumerate(probs) if 1.0 - p <= q]

    def observe(self, x: Sparse, probs: list[float], y: int) -> bool:
        """Add a held-out, randomly sampled, oracle-labelled example."""
        q = self.threshold()
        covered = q is None or 1.0 - probs[y] <= q
        if q is not None:
            self.observed += 1
            self.misses += 0 if covered else 1
            err = 0.0 if covered else 1.0
            self.alpha_t = min(0.999, max(0.0, self.alpha_t + self.gamma * (self.target - err)))
        self.samples.append((x, y))
        self.stale = True
        return covered

    def state(self) -> dict:
        return {"kind": "marginal", "target": self.target, "alpha_t": self.alpha_t, "gamma": self.gamma,
                "min_calibration": self.min_calibration, "window": self.samples.maxlen,
                "samples": [[_pack(x), y] for x, y in self.samples],
                "observed": self.observed, "misses": self.misses}

    @classmethod
    def from_state(cls, s: dict) -> "AdaptiveConformal":
        c = cls(s["target"], s["window"], s["gamma"], s["min_calibration"])
        c.alpha_t, c.observed, c.misses = s["alpha_t"], s["observed"], s["misses"]
        c.samples.extend((_unpack(x), y) for x, y in s.get("samples", []))
        return c


class MondrianConformal:
    """Class-conditional conformal: one adaptive calibrator per label.

    The error bound then holds for each label on its own, so a rare but
    important label (fraud, "urgent", "unsafe") cannot hide behind a good
    average. Until every label has evidence, the court counts as uncalibrated
    and escalates.
    """

    def __init__(self, n_classes: int, target_error: float = 0.05, window: int = 250,
                 gamma: float = 0.005, min_calibration: int = 20):
        self.per = [AdaptiveConformal(target_error, window, gamma, min_calibration)
                    for _ in range(n_classes)]

    @property
    def target(self) -> float:
        return self.per[0].target

    @target.setter
    def target(self, v: float) -> None:
        for c in self.per:
            c.target = v

    @property
    def alpha_t(self) -> float:
        return sum(c.alpha_t for c in self.per) / len(self.per)

    @property
    def calibrated(self) -> bool:
        return all(c.calibrated for c in self.per)

    @property
    def calibration_size(self) -> int:
        return sum(c.calibration_size for c in self.per)

    @property
    def observed(self) -> int:
        return sum(c.observed for c in self.per)

    @property
    def misses(self) -> int:
        return sum(c.misses for c in self.per)

    @property
    def stale(self) -> bool:
        return any(c.stale for c in self.per)

    @stale.setter
    def stale(self, v: bool) -> None:
        for c in self.per:
            c.stale = v

    def rescore(self, proba: ProbaFn) -> None:
        for c in self.per:
            c.rescore(proba)

    def prediction_set(self, probs: list[float]) -> list[int]:
        out = []
        for i, p in enumerate(probs):
            q = self.per[i].threshold()
            if q is None or 1.0 - p <= q:
                out.append(i)
        return out

    def observe(self, x: Sparse, probs: list[float], y: int) -> bool:
        return self.per[y].observe(x, probs, y)

    def state(self) -> dict:
        return {"kind": "mondrian", "per": [c.state() for c in self.per]}

    @classmethod
    def from_state(cls, s: dict) -> "MondrianConformal":
        m = cls.__new__(cls)
        m.per = [AdaptiveConformal.from_state(c) for c in s["per"]]
        return m


def conformal_from_state(s: dict):
    return MondrianConformal.from_state(s) if s.get("kind") == "mondrian" else AdaptiveConformal.from_state(s)
