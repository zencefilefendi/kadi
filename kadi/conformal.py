"""Calibrated abstention: the part that makes Kadı trustworthy.

Two policies decide when the reflex may answer:

* ``conformal`` - split conformal prediction with Adaptive Conformal Inference
  (marginal, or per label with Mondrian). Answer locally iff the prediction set
  is a single label. Guarantee: Pr(disagree with oracle) <= alpha, *in
  expectation* (marginal coverage).

* ``ltt`` - Learn then Test (Angelopoulos, Bates, Candès, Jordan & Lei, 2021)
  for selective classification. Answer locally iff max p >= lambda, where lambda
  is the loosest threshold that a fixed-sequence of exact binomial tests can
  certify. Guarantee: with probability >= 1 - delta over the calibration
  sample, the decision risk Pr(local and wrong) <= alpha (a PAC / high-
  probability statement, stronger than marginal coverage).

Shared rules for both policies, because an online system breaks naive
calibration:

1. **Held-out, random calibration.** Calibration examples are an i.i.d.
   sample of the stream that is never trained on. Calibrating on escalated
   examples is biased (their label is in the set by construction) and makes
   the threshold ratchet loose.
2. **Fresh scores.** Stored calibration inputs are periodically re-scored with
   the current model; between re-scores, new samples are scored on arrival.
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


def _argmax(p: list[float]) -> int:
    return max(range(len(p)), key=p.__getitem__)


# ---------------------------------------------------------------- conformal
class AdaptiveConformal:
    kind = "marginal"

    def __init__(self, target_error: float = 0.05, window: int = 400,
                 gamma: float = 0.005, min_calibration: int = 40):
        if not 0 < target_error < 1:
            raise ValueError("target_error must be in (0, 1)")
        self.target = target_error
        self.alpha_t = target_error
        self.gamma = gamma
        self.min_calibration = min_calibration
        self.samples: deque[tuple[Sparse, int]] = deque(maxlen=window)
        self.scores: deque[float] = deque(maxlen=window)   # aligned with samples
        self._sorted: list[float] = []
        self.observed = 0
        self.misses = 0

    @property
    def calibrated(self) -> bool:
        return len(self.samples) >= self.min_calibration

    @property
    def calibration_size(self) -> int:
        return len(self.samples)

    def rescore(self, proba: ProbaFn) -> None:
        self.scores = deque((1.0 - proba(x)[y] for x, y in self.samples), maxlen=self.samples.maxlen)
        self._sorted = sorted(self.scores)

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
        return math.inf if k > n else self._sorted[k - 1]

    def prediction_set(self, probs: list[float]) -> list[int]:
        q = self.threshold()
        if q is None or q == math.inf:
            return list(range(len(probs)))
        return [i for i, p in enumerate(probs) if 1.0 - p <= q]

    def observe(self, x: Sparse, probs: list[float], y: int) -> bool:
        """Add a held-out, randomly sampled, oracle-labelled example."""
        q = self.threshold()
        score = 1.0 - probs[y]
        covered = q is None or score <= q
        if q is not None:
            self.observed += 1
            self.misses += 0 if covered else 1
            err = 0.0 if covered else 1.0
            self.alpha_t = min(0.999, max(0.0, self.alpha_t + self.gamma * (self.target - err)))
        self.samples.append((x, y))
        self.scores.append(score)
        self._sorted = sorted(self.scores)
        return covered

    def info(self) -> dict:
        return {"alpha_t": self.alpha_t, "threshold": self.threshold()}

    def state(self) -> dict:
        return {"kind": self.kind, "target": self.target, "alpha_t": self.alpha_t, "gamma": self.gamma,
                "min_calibration": self.min_calibration, "window": self.samples.maxlen,
                "samples": [[_pack(x), y] for x, y in self.samples],
                "observed": self.observed, "misses": self.misses}

    @classmethod
    def from_state(cls, s: dict) -> "AdaptiveConformal":
        c = cls(s["target"], s["window"], s["gamma"], s["min_calibration"])
        c.alpha_t, c.observed, c.misses = s["alpha_t"], s["observed"], s["misses"]
        c.samples.extend((_unpack(x), y) for x, y in s.get("samples", []))
        return c  # scores are rebuilt by the first rescore()


class MondrianConformal:
    """Class-conditional conformal: one adaptive calibrator per label.

    The error bound then holds for each label on its own, so a rare but
    important label (fraud, "urgent", "unsafe") cannot hide behind a good
    average. Until every label has evidence, the court counts as uncalibrated
    and escalates.
    """
    kind = "mondrian"

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

    def info(self) -> dict:
        return {"alpha_t": self.alpha_t}

    def state(self) -> dict:
        return {"kind": self.kind, "per": [c.state() for c in self.per]}

    @classmethod
    def from_state(cls, s: dict) -> "MondrianConformal":
        m = cls.__new__(cls)
        m.per = [AdaptiveConformal.from_state(c) for c in s["per"]]
        return m


# ------------------------------------------------------------ learn then test
def binom_cdf(k: int, n: int, p: float) -> float:
    """P(Binomial(n, p) <= k), exact, numerically stable in log space."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    lp, lq = math.log(p), math.log1p(-p)
    terms = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq
             for i in range(k + 1)]
    m = max(terms)
    return min(1.0, math.exp(m) * sum(math.exp(t - m) for t in terms))


# Fixed in advance (LTT requires a data-independent grid), ordered from the
# most conservative threshold to the loosest: dense near 1, coarse below.
LTT_GRID: tuple[float, ...] = tuple(sorted(
    {round(1 - 10 ** (-e / 8), 6) for e in range(1, 33)} | {round(i / 20, 2) for i in range(1, 20)},
    reverse=True))


class LearnThenTest:
    """Selective classification with a high-probability risk guarantee.

    Loss of a calibration example at threshold lam:
        L(lam) = 1{ max p >= lam  and  argmax p != oracle label }
    i.e. "Kadı would have answered locally, and wrongly". Escalations cost 0.
    For each lam on a fixed grid (strict -> loose) test H0: E[L(lam)] > alpha
    with the exact binomial p-value P(Bin(n, alpha) <= sum L). Fixed-sequence
    testing stops at the first non-rejection; the loosest rejected lam is used.
    Then, with probability >= 1 - delta, the risk at the chosen lam is <= alpha.
    """
    kind = "ltt"

    def __init__(self, target_error: float = 0.05, delta: float = 0.05, window: int = 1000):
        if not 0 < target_error < 1:
            raise ValueError("target_error must be in (0, 1)")
        if not 0 < delta < 1:
            raise ValueError("delta must be in (0, 1)")
        self.target = target_error
        self.delta = delta
        self.samples: deque[tuple[Sparse, int]] = deque(maxlen=window)
        self.evals: deque[tuple[float, bool]] = deque(maxlen=window)   # (max p, argmax correct)
        self.lam: float | None = None
        self.observed = 0
        self.misses = 0

    # interface shared with the conformal calibrators
    @property
    def alpha_t(self) -> float:
        return self.target

    @property
    def calibrated(self) -> bool:
        return self.lam is not None

    @property
    def calibration_size(self) -> int:
        return len(self.samples)

    @property
    def min_samples(self) -> int:
        """Smallest n at which even a zero-error sample can certify alpha."""
        return math.ceil(math.log(self.delta) / math.log1p(-self.target))

    def _certify(self) -> None:
        n = len(self.evals)
        lam = None
        if n >= self.min_samples:
            for cand in LTT_GRID:
                k = sum(1 for pm, ok in self.evals if pm >= cand and not ok)
                if binom_cdf(k, n, self.target) <= self.delta:
                    lam = cand
                else:
                    break
        self.lam = lam

    def rescore(self, proba: ProbaFn) -> None:
        ev = []
        for x, y in self.samples:
            p = proba(x)
            t = _argmax(p)
            ev.append((p[t], t == y))
        self.evals = deque(ev, maxlen=self.samples.maxlen)
        self._certify()

    def prediction_set(self, probs: list[float]) -> list[int]:
        t = _argmax(probs)
        if self.lam is not None and probs[t] >= self.lam:
            return [t]
        return list(range(len(probs)))

    def observe(self, x: Sparse, probs: list[float], y: int) -> bool:
        t = _argmax(probs)
        local = self.lam is not None and probs[t] >= self.lam
        wrong = local and t != y
        if self.lam is not None:
            self.observed += 1
            self.misses += int(wrong)
        self.samples.append((x, y))
        self.evals.append((probs[t], t == y))
        self._certify()
        return not wrong

    def info(self) -> dict:
        return {"lambda": self.lam, "delta": self.delta, "min_samples": self.min_samples}

    def state(self) -> dict:
        return {"kind": self.kind, "target": self.target, "delta": self.delta, "window": self.samples.maxlen,
                "samples": [[_pack(x), y] for x, y in self.samples],
                "observed": self.observed, "misses": self.misses}

    @classmethod
    def from_state(cls, s: dict) -> "LearnThenTest":
        c = cls(s["target"], s["delta"], s["window"])
        c.observed, c.misses = s["observed"], s["misses"]
        c.samples.extend((_unpack(x), y) for x, y in s.get("samples", []))
        return c


def conformal_from_state(s: dict):
    kind = s.get("kind")
    if kind == "mondrian":
        return MondrianConformal.from_state(s)
    if kind == "ltt":
        return LearnThenTest.from_state(s)
    return AdaptiveConformal.from_state(s)
