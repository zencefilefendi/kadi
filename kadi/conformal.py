"""Calibrated abstention: the part that makes Kadı trustworthy.

Every calibrator belongs to ONE frozen model version and only ever sees
oracle-labelled calibration samples drawn *after* that version was frozen.
The scored model is therefore independent of its calibration data, exactly
as split-conformal / Learn-then-Test require (no re-scoring, no leakage).

Policies
--------
* ``conformal`` - split conformal + Adaptive Conformal Inference (marginal, or
  per label with Mondrian). Answer locally iff the prediction set is a single
  label. Guarantee: Pr(disagree with oracle) <= alpha in expectation.

* ``ltt`` - anytime-valid Learn then Test for selective classification. Answer
  locally iff max p >= lambda, where lambda is the loosest threshold on a fixed
  grid whose risk a betting e-process has refuted being above alpha. By
  Ville's inequality the certificate holds *uniformly over time*: with
  probability >= 1 - delta_v the served threshold never has risk > alpha, at
  any point in the stream, for model version v (under exchangeability).

Monitoring
----------
``DriftDetector`` is a Shiryaev-Roberts e-detector on the deployed joint loss
1{answered locally and wrong}: under "risk <= alpha" its expected time to a
false alarm is at least ``arl`` observations; a sustained rise above alpha is
detected. On alarm the engine re-certifies the served model on fresh data.

Error budget across versions
----------------------------
``version_delta(delta, v) = delta * 6 / (pi^2 v^2)`` sums to delta over all
versions v = 1, 2, ..., so *all* certificates ever issued hold simultaneously
with probability >= 1 - delta (and any rule for choosing which certified
version to serve stays valid).
"""
from __future__ import annotations

import math
from collections import deque


def _argmax(p: list[float]) -> int:
    return max(range(len(p)), key=p.__getitem__)


def version_delta(delta: float, v: int) -> float:
    """Share of the failure budget spent on the v-th certificate (v >= 1)."""
    return delta * 6.0 / (math.pi ** 2 * max(1, v) ** 2)


def would_answer(calibrator, probs: list[float]) -> int | None:
    """Label index this calibrator would answer locally, or None."""
    if not calibrator.calibrated:
        return None
    pset = calibrator.prediction_set(probs) or [_argmax(probs)]   # empty set: answer argmax (see engine)
    if len(pset) == 1 and pset[0] == _argmax(probs):
        return pset[0]
    return None


# ---------------------------------------------------------------- conformal
class AdaptiveConformal:
    kind = "marginal"

    def __init__(self, target_error: float = 0.05, window: int = 1000,
                 gamma: float = 0.005, min_calibration: int = 40):
        if not 0 < target_error < 1:
            raise ValueError("target_error must be in (0, 1)")
        self.target = target_error
        self.alpha_t = target_error
        self.gamma = gamma
        self.min_calibration = min_calibration
        self.scores: deque[float] = deque(maxlen=window)
        self._sorted: list[float] = []
        self.observed = 0
        self.misses = 0

    @property
    def calibrated(self) -> bool:
        return len(self.scores) >= self.min_calibration

    @property
    def calibration_size(self) -> int:
        return len(self.scores)

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

    def observe(self, probs: list[float], y: int) -> bool:
        """Add a calibration sample scored by this version's frozen model."""
        q = self.threshold()
        score = 1.0 - probs[y]
        covered = q is None or score <= q
        if q is not None:
            self.observed += 1
            self.misses += 0 if covered else 1
            err = 0.0 if covered else 1.0
            self.alpha_t = min(0.999, max(0.0, self.alpha_t + self.gamma * (self.target - err)))
        self.scores.append(score)
        self._sorted = sorted(self.scores)
        return covered

    def info(self) -> dict:
        return {"alpha_t": self.alpha_t, "threshold": self.threshold()}

    def state(self) -> dict:
        return {"kind": self.kind, "target": self.target, "alpha_t": self.alpha_t, "gamma": self.gamma,
                "min_calibration": self.min_calibration, "window": self.scores.maxlen,
                "scores": list(self.scores), "observed": self.observed, "misses": self.misses}

    @classmethod
    def from_state(cls, s: dict) -> "AdaptiveConformal":
        c = cls(s["target"], s["window"], s["gamma"], s["min_calibration"])
        c.alpha_t, c.observed, c.misses = s["alpha_t"], s["observed"], s["misses"]
        c.scores.extend(s.get("scores", []))
        c._sorted = sorted(c.scores)
        return c


class MondrianConformal:
    """Class-conditional conformal: one adaptive calibrator per label.

    The error bound then holds for each label on its own, so a rare but
    important label (fraud, "urgent", "unsafe") cannot hide behind a good
    average. Until every label has evidence, the court counts as uncalibrated.
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

    def prediction_set(self, probs: list[float]) -> list[int]:
        out = []
        for i, p in enumerate(probs):
            q = self.per[i].threshold()
            if q is None or 1.0 - p <= q:
                out.append(i)
        return out

    def observe(self, probs: list[float], y: int) -> bool:
        return self.per[y].observe(probs, y)

    def info(self) -> dict:
        return {"alpha_t": self.alpha_t}

    def state(self) -> dict:
        return {"kind": self.kind, "per": [c.state() for c in self.per]}

    @classmethod
    def from_state(cls, s: dict) -> "MondrianConformal":
        m = cls.__new__(cls)
        m.per = [AdaptiveConformal.from_state(c) for c in s["per"]]
        return m


# ------------------------------------------------- anytime-valid Learn then Test
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
# Mixture of constant bets b = f / (1 - alpha), f in FRACS, with prior WEIGHTS.
# Aggressive bets certify clean thresholds fast; small bets survive a few errors.
BET_FRACS = (0.9, 0.5, 0.25, 0.1)
BET_WEIGHTS = (0.6, 0.25, 0.1, 0.05)


class LearnThenTest:
    """Anytime-valid Learn then Test for selective classification.

    Loss at threshold lam:  L(lam) = 1{ max p >= lam and argmax != oracle }.
    For each lam on LTT_GRID we test H0(lam): E[L(lam)] > alpha with the
    betting e-process  K_t = sum_j w_j prod_s (1 + b_j (alpha - L_s(lam))),
    a non-negative supermartingale under H0. Ville: P(sup_t K_t >= 1/delta)
    <= delta, so p_t = 1 / max_{s<=t} K_s is an anytime-valid p-value.
    Fixed-sequence testing over the grid (strict -> loose) controls the
    family-wise error at delta uniformly over time; the certified lam only
    ever loosens as evidence accumulates.
    """
    kind = "ltt"

    def __init__(self, target_error: float = 0.05, delta: float = 0.05):
        if not 0 < target_error < 1:
            raise ValueError("target_error must be in (0, 1)")
        if not 0 < delta < 1:
            raise ValueError("delta must be in (0, 1)")
        self.target = target_error
        self.delta = delta
        g = len(LTT_GRID)
        self.logw = [[0.0] * len(BET_FRACS) for _ in range(g)]
        self.maxk = [1.0] * g
        self.n_local = [0] * g
        self.n = 0
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
        return self.n

    @property
    def min_samples(self) -> int:
        """Exact number of zero-loss samples after which a threshold certifies:
        the smallest n with sum_j w_j (1 + b_j alpha)^n >= 1/delta."""
        a, thr = self.target, 1.0 / self.delta
        growth = [math.log1p(f / (1 - a) * a) for f in BET_FRACS]
        n = 0
        while sum(w * math.exp(g * n) for w, g in zip(BET_WEIGHTS, growth)) < thr:
            n += 1
        return n

    def prediction_set(self, probs: list[float]) -> list[int]:
        t = _argmax(probs)
        if self.lam is not None and probs[t] >= self.lam:
            return [t]
        return list(range(len(probs)))

    def observe(self, probs: list[float], y: int) -> bool:
        t = _argmax(probs)
        pm, ok = probs[t], t == y
        wrong = self.lam is not None and pm >= self.lam and not ok
        if self.lam is not None:
            self.observed += 1
            self.misses += int(wrong)
        a = self.target
        bets = [f / (1 - a) for f in BET_FRACS]
        thr = 1.0 / self.delta
        for i, lam in enumerate(LTT_GRID):
            local = pm >= lam
            self.n_local[i] += local
            if self.maxk[i] >= thr:          # certified for good: no need to keep betting
                continue
            loss = 1.0 if (local and not ok) else 0.0
            row = self.logw[i]
            k = 0.0
            for j, b in enumerate(bets):
                row[j] += math.log1p(b * (a - loss))
                k += BET_WEIGHTS[j] * math.exp(min(row[j], 700.0))
            if k > self.maxk[i]:
                self.maxk[i] = k
        self.n += 1
        self._certify()
        return not wrong

    def _certify(self) -> None:
        thr = 1.0 / self.delta
        lam = None
        for i, cand in enumerate(LTT_GRID):
            if self.maxk[i] >= thr:
                lam = cand
            else:
                break
        self.lam = lam

    def local_share(self) -> float | None:
        """Share of calibration samples the certified threshold would answer locally."""
        if self.lam is None or not self.n:
            return None
        return self.n_local[LTT_GRID.index(self.lam)] / self.n

    def info(self) -> dict:
        return {"lambda": self.lam, "delta": self.delta, "min_samples": self.min_samples}

    def state(self) -> dict:
        return {"kind": self.kind, "anytime": True, "target": self.target, "delta": self.delta,
                "logw": self.logw, "maxk": self.maxk, "n_local": self.n_local, "n": self.n,
                "observed": self.observed, "misses": self.misses}

    @classmethod
    def from_state(cls, s: dict) -> "LearnThenTest":
        c = cls(s["target"], s["delta"])
        c.logw, c.maxk, c.n_local, c.n = s["logw"], s["maxk"], s["n_local"], s["n"]
        c.observed, c.misses = s["observed"], s["misses"]
        c._certify()
        return c


def make_calibrator(policy: str, conditional: bool, n_classes: int, target: float, delta: float):
    if policy == "ltt":
        return LearnThenTest(target, delta)
    if conditional:
        return MondrianConformal(n_classes, target)
    return AdaptiveConformal(target)


def conformal_from_state(s: dict):
    kind = s.get("kind")
    if kind == "mondrian":
        return MondrianConformal.from_state(s)
    if kind == "ltt":
        if not s.get("anytime"):
            raise ValueError("pre-0.6 LTT state cannot be reused (certificates are re-issued)")
        return LearnThenTest.from_state(s)
    return AdaptiveConformal.from_state(s)


# ------------------------------------------------------------------- monitoring
DETECTOR_SCALES = (0.01, 0.025, 0.05, 0.1, 0.2, 0.4)   # bets lambda = c / alpha, c in (0, 1]


class DriftDetector:
    """Shiryaev-Roberts e-detector for H0: E[L_t | past] <= alpha.

    Per bet lam_j = c_j / alpha:  R_j <- (1 + R_j) * (1 + lam_j (L_t - alpha)).
    Each R_j - t is a supermartingale under H0, and so is their average, so the
    rule "alarm when mean_j R_j >= arl" has expected time to false alarm >= arl
    (Shin, Ramdas & Rinaldo, e-detectors). Small bets catch slow drifts, large
    bets catch abrupt ones.
    """

    def __init__(self, alpha: float, arl: float = 1000.0):
        self.alpha = alpha
        self.arl = arl
        self.lams = [c / alpha for c in DETECTOR_SCALES]
        self.r = [0.0] * len(self.lams)
        self.n = 0
        self.losses = 0

    @property
    def statistic(self) -> float:
        return sum(self.r) / len(self.r)

    def update(self, loss: float) -> bool:
        a = self.alpha
        self.r = [(1.0 + r) * (1.0 + lam * (loss - a)) for r, lam in zip(self.r, self.lams)]
        self.n += 1
        self.losses += loss
        if self.statistic >= self.arl:
            self.r = [0.0] * len(self.r)
            return True
        return False

    def info(self) -> dict:
        return {"statistic": round(self.statistic, 3), "threshold": self.arl, "observations": self.n,
                "observed_risk": (self.losses / self.n) if self.n else None}

    def state(self) -> dict:
        return {"alpha": self.alpha, "arl": self.arl, "r": self.r, "n": self.n, "losses": self.losses}

    @classmethod
    def from_state(cls, s: dict) -> "DriftDetector":
        d = cls(s["alpha"], s["arl"])
        d.r, d.n, d.losses = s["r"], s["n"], s["losses"]
        return d
