"""The Kadı cascade.

    input ──► memory  (exact replay of a past oracle verdict)        ~µs, $0
          └─► reflex  (the SERVED frozen model version answers, only if
                       its certificate allows it, the input is not
                       novel, and the court is not on probation)      ~ms, $0
          └─► oracle  (frontier model; its verdict trains the LIVE
                       model and calibrates certified versions)       ~s,  $$
          └─► fallback (oracle down + on_oracle_error="best_guess":
                       best local guess, flagged)                     ~ms, $0

Versioned certification (v0.6)
-------------------------------
Training never touches the model that answers. A `live` model learns from
every oracle label; from time to time it is frozen into a `candidate` version
whose calibrator sees only calibration samples drawn *after* the freeze, so
the scored model is independent of its calibration data (split-conformal /
LTT hold exactly, no re-scoring). A candidate that earns a certificate and
answers at least as often as the served version on the same samples replaces
it. Certificates spend the failure budget as delta_v = delta * 6/(pi^2 v^2),
so all of them hold simultaneously with probability >= 1 - delta.

Safety layers, in order:
  * schema lock     - every answer is one of the declared options
  * certificate     - conformal singleton or anytime-valid LTT threshold
  * novelty guard   - inputs unlike anything trained on are escalated
  * audits          - a random slice of decisions is re-asked to the oracle
  * drift detector  - Shiryaev-Roberts e-detector on the deployed risk; on
                      alarm the served version is re-certified on fresh data
                      and the court escalates in the meantime
  * privacy         - PII redaction before storage/featurization (and
                      optionally before the oracle); keyed HMAC input hashes
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import random
import secrets
import sys
import threading
import time
import warnings
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from typing import Callable

from . import snapshot as snapfmt
from .conformal import DriftDetector, conformal_from_state, make_calibrator, version_delta, would_answer
from .features import HashingFeaturizer, normalize
from .learner import OnlineSoftmax
from .oracles import Oracle, OracleError, Verdict
from .questions import Question, quote
from .store import Store, derive_chain_key

MAX_INPUT_CHARS = 32_000
FREEZE_MIN = 300             # first candidate after this many training labels
FREEZE_GROWTH = 2.0         # next candidate once live has seen GROWTH x the served version's data
PROMOTE_TRIAL = 30          # samples on which a certified candidate must match the served version
STALE_SAMPLES = 1500        # give up on a candidate that has not certified after this many samples
TIERS = ("memory", "reflex", "oracle", "fallback")
PENDING_TTL = 3600.0        # seconds a deferred decision stays resolvable
MAX_PENDING = 10_000
SNAPSHOT_FORMAT = 2


@dataclass
class Pending:
    """A case Kadı will not decide alone: the caller must judge it and call resolve()."""
    ticket: str
    question: str
    options: list[str]
    candidates: list[str]      # labels still in play (all options for audits, so audits stay blind)
    reason: str
    instructions: str
    expires_in_s: float
    status: str = "needs_verdict"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class _Case:
    brain: "_Brain"
    kind: str                  # shadow | audit | escalate
    text: str
    clean: str
    context: dict | None
    ctx: dict | None
    key: str
    x: dict
    probs: list[float]         # from the served version at routing time
    pset_labels: list[str]
    local: int | None          # what the served version answered / would answer
    reason: str
    sampled: bool              # calibration sample (chosen independently of the input)
    t0: float
    created: float
    seq: int                   # decision sequence number within the court
    version: int               # served version id at routing time


@dataclass
class Decision:
    id: int
    question: str
    label: str
    tier: str
    confidence: float
    prediction_set: list[str]
    cost_usd: float
    latency_ms: float
    reason: str
    flagged: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class _NoCertificate:
    """Calibrator of version 0 (the untrained initial model): never certifies."""
    calibrated = False
    calibration_size = 0
    alpha_t = 0.0
    observed = misses = 0

    def prediction_set(self, probs):
        return list(range(len(probs)))

    def observe(self, probs, y):
        return True

    def info(self):
        return {}

    def state(self):
        return {"kind": "none"}


@dataclass(slots=True)
class _Version:
    id: int
    model: object              # frozen snapshot: predict_proba / novelty / seen
    cal: object                # its own calibrator (or _NoCertificate)
    frozen_seq: int            # only cases with seq > frozen_seq may calibrate it
    samples: int = 0
    trial_n: int = 0
    trial_self: int = 0
    trial_served: int = 0
    served_pmax: list | None = None   # LTT: the served model's max-p on this candidate's samples

    def meta(self) -> dict:
        return {"id": self.id, "frozen_seq": self.frozen_seq, "samples": self.samples, "trial_n": self.trial_n,
                "trial_self": self.trial_self, "trial_served": self.trial_served,
                "served_pmax": self.served_pmax, "cal": self.cal.state()}


ABLATIONS = frozenset({"calibrate_on_escalated", "no_freeze", "no_novelty", "no_consistency", "fixed_sampling"})


class _Brain:
    def __init__(self, q: Question, memory_size: int, reflex, drift_arl: float, ablate: frozenset = frozenset()):
        self.q = q
        self.reflex = reflex
        self.ablate = ablate
        self.live = reflex(len(q.options))
        self.versions_issued = 0
        self.served = _Version(0, self.live.snapshot(), _NoCertificate(), 0)
        if "no_freeze" in ablate:     # v0.5-style: the learning model itself answers and is calibrated
            self.served = self.new_version(self.live, 0)
        self.candidate: _Version | None = None
        self.refreeze_floor = 0
        self.seq = 0
        self.detector = DriftDetector(q.target_error, drift_arl)
        self.drift_arl = drift_arl
        self.memory: OrderedDict[str, str] = OrderedDict()
        self.memory_size = memory_size
        self.lock = threading.Lock()
        self.oracle_cost: deque[float] = deque(maxlen=200)
        self.recent_tiers: deque[str] = deque(maxlen=500)
        self.counts = {t: 0 for t in TIERS}
        self.cost_total = 0.0
        self.audits = self.audit_agree = 0
        self.shadow_n = self.shadow_local = self.shadow_agree = 0
        self.probation = 0
        self.promotions = 0
        self.last_alert = 0.0
        self.dirty = 0
        self.last_save = time.time()
        self.last_stats = 0.0

    @property
    def model(self):           # the learning model (kept for backwards compatibility)
        return self.live

    # all methods below assume self.lock is held
    def new_version(self, model, seq: int) -> _Version:
        self.versions_issued += 1
        q = self.q
        cal = make_calibrator(q.policy, q.conditional, len(q.options), q.target_error,
                              version_delta(q.delta, self.versions_issued))
        return _Version(self.versions_issued, model, cal, seq)

    def maybe_freeze(self) -> None:
        if "no_freeze" in self.ablate:
            return
        need = max(FREEZE_MIN, FREEZE_GROWTH * self.served.model.seen, self.refreeze_floor)
        if self.candidate is None and self.live.seen >= need:
            self.candidate = self.new_version(self.live.snapshot(), self.seq)

    def remember(self, key: str, label: str) -> None:
        self.memory[key] = label
        self.memory.move_to_end(key)
        while len(self.memory) > self.memory_size:
            self.memory.popitem(last=False)

    def calibrate(self, c: _Case, y: int) -> None:
        """Feed one calibration sample to every version frozen before it was drawn."""
        served, cand = self.served, self.candidate
        s_probs = None
        if served.frozen_seq < c.seq and served.id:
            s_probs = c.probs if served.id == c.version else served.model.predict_proba(c.x)
        if cand is not None and cand.frozen_seq < c.seq:
            c_probs = cand.model.predict_proba(c.x)
            if self.q.policy == "ltt":
                if cand.served_pmax is None:
                    cand.served_pmax = []
                cand.served_pmax.append(max(s_probs) if s_probs is not None else 0.0)
            elif cand.cal.calibrated and served.cal.calibrated and s_probs is not None:
                cand.trial_n += 1
                cand.trial_self += would_answer(cand.cal, c_probs) is not None
                cand.trial_served += would_answer(served.cal, s_probs) is not None
            cand.cal.observe(c_probs, y)
            cand.samples += 1
        if s_probs is not None:
            served.cal.observe(s_probs, y)
            served.samples += 1
        self._promote_or_retire()

    def _promote_or_retire(self) -> None:
        cand = self.candidate
        if cand is None:
            return
        if cand.cal.calibrated:
            if self.q.policy == "ltt":
                # Compare on the candidate's own calibration samples: share it would
                # answer at its certified threshold vs the served version at its own.
                # Every certificate holds simultaneously (delta spending), so choosing
                # among certified versions by this rule is safe.
                served = self.served
                lam = served.cal.lam if served.cal.calibrated else None
                pm = cand.served_pmax or []
                served_share = (sum(p >= lam for p in pm) / len(pm)) if (lam is not None and pm) else 0.0
                if cand.cal.local_share() >= served_share:
                    self._promote(cand)
                elif cand.samples >= STALE_SAMPLES:
                    self.refreeze_floor = int(self.live.seen * 1.5)
                    self.candidate = None
                return
            if not self.served.cal.calibrated or (cand.trial_n >= PROMOTE_TRIAL
                                                 and cand.trial_self >= cand.trial_served):
                self._promote(cand)
                return
            if cand.trial_n >= PROMOTE_TRIAL:   # certified but not better: keep the incumbent
                self.refreeze_floor = int(cand.model.seen * 1.5)
                self.candidate = None
        elif cand.samples >= STALE_SAMPLES:
            self.refreeze_floor = int(self.live.seen * 1.5)
            self.candidate = None

    def _promote(self, cand: _Version) -> None:
        cand.served_pmax = None
        self.served, self.candidate = cand, None
        self.detector = DriftDetector(self.q.target_error, self.drift_arl)
        self.promotions += 1

    def avg_oracle_cost(self) -> float:
        return sum(self.oracle_cost) / len(self.oracle_cost) if self.oracle_cost else 0.0

    def stats(self) -> dict:
        n = len(self.recent_tiers) or 1
        c = self.served.cal
        cand = self.candidate
        return {
            "question": self.q.name, "options": list(self.q.options), "kind": self.q.meta.get("kind"),
            "mode": self.q.mode, "conditional": self.q.conditional, "policy": self.q.policy,
            "calibrator": {k: v for k, v in c.info().items() if v is None or isinstance(v, (int, float))
                           and math.isfinite(v)},
            "target_error": self.q.target_error, "alpha_t": round(c.alpha_t, 5),
            "calibration_size": c.calibration_size, "calibrated": c.calibrated,
            "realized_miscoverage": (c.misses / c.observed) if c.observed else None,
            "trained_on": self.live.seen,
            "version": {"served": self.served.id, "served_trained_on": self.served.model.seen,
                        "candidate": cand.id if cand else None,
                        "candidate_samples": cand.samples if cand else None,
                        "candidate_certified": cand.cal.calibrated if cand else None,
                        "versions_issued": self.versions_issued, "promotions": self.promotions},
            "local_rate_recent": sum(t in ("memory", "reflex") for t in self.recent_tiers) / n,
            "counts": dict(self.counts), "cost_total": self.cost_total,
            "audits": self.audits,
            "audit_agreement": (self.audit_agree / self.audits) if self.audits else None,
            "shadow": {"n": self.shadow_n,
                       "would_be_local": (self.shadow_local / self.shadow_n) if self.shadow_n else None,
                       "agreement": (self.shadow_agree / self.shadow_local) if self.shadow_local else None},
            "drift": self.detector.info(),
            "probation": self.probation,
            "avg_oracle_cost": self.avg_oracle_cost(), "memory_entries": len(self.memory),
        }


class Kadi:
    def __init__(self, oracle: Oracle, db: str = "kadi.db", *, audit_rate: float = 0.05,
                 sample_budget: float = 0.05, store_inputs: bool = True,
                 redact: bool | Callable[[str], str] = True, redact_oracle: bool = False,
                 secret: bytes | str | None = None, on_oracle_error: str = "raise", memory_size: int = 50_000,
                 checkpoint_seconds: float = 15.0, probation_length: int = 300, drift_arl: float = 1000.0,
                 alert_hook: Callable[[dict], None] | None = None, seed: int | None = None,
                 featurizer: Callable[[str], dict[int, float]] | None = None, reflex=None,
                 _ablate: frozenset | set = frozenset()):
        if not 0 <= audit_rate <= 1 or not 0 <= sample_budget <= 1:
            raise ValueError("audit_rate and sample_budget must be in [0, 1]")
        if on_oracle_error not in ("raise", "best_guess"):
            raise ValueError('on_oracle_error must be "raise" or "best_guess"')
        self.oracle = oracle
        self.store = Store(db)
        self.audit_rate = audit_rate
        self.sample_budget = sample_budget
        self.store_inputs = store_inputs
        if redact is True:
            from .redact import DEFAULT_REDACTOR
            self.redactor = DEFAULT_REDACTOR
        else:
            self.redactor = redact or None
        self.redact_oracle = redact_oracle
        secret = secret or os.environ.get("KADI_SECRET")
        if not secret and not store_inputs and db != ":memory:":
            warnings.warn("store_inputs=False without KADI_SECRET: the HMAC key lives in the same database "
                          "as the hashes, so a copy of the DB allows guessing inputs. Set KADI_SECRET.",
                          stacklevel=2)
        self.secret = (secret.encode() if isinstance(secret, str) else secret) or self.store.secret()
        self.store.chain_key = derive_chain_key(self.secret)
        self.on_oracle_error = on_oracle_error
        self.memory_size = memory_size
        self.checkpoint_seconds = checkpoint_seconds
        self.probation_length = probation_length
        self.drift_arl = drift_arl
        self.alert_hook = alert_hook
        self.featurize = featurizer or HashingFeaturizer()
        self.novelty_limit = getattr(self.featurize, "hashed_dim", None)
        # reflex factory: callable(n_classes) -> model, plus .unpack(meta, arrays, prefix, base)
        self.reflex = reflex or OnlineSoftmax
        self.rng = random.Random(seed)
        self._brains: dict[str, _Brain] = {}
        self._reg = threading.Lock()
        self._pending: OrderedDict[str, _Case] = OrderedDict()
        self._writer = _CheckpointWriter(self)
        # Benchmark-only switches that disable one safety mechanism at a time, to
        # measure what it is worth. Never use them in production.
        self._ablate = frozenset(_ablate)
        if self._ablate - ABLATIONS:
            raise ValueError(f"unknown ablations {sorted(self._ablate - ABLATIONS)}")

    # ================================================================ public
    def register(self, *questions: Question) -> None:
        for q in questions:
            self._brain(q)

    @property
    def questions(self) -> dict[str, Question]:
        return {name: b.q for name, b in self._brains.items()}

    def decide(self, question: Question | str, text: str, context: dict | None = None) -> Decision:
        """Decide now. When the oracle is needed it is called synchronously."""
        case = self._route(question, text, context)
        if isinstance(case, Decision):
            return case
        v = self._ask(case.brain.q, case.text, case.clean, case.context, case.ctx)
        return self._complete(case, v) if v is not None else self._no_verdict(case)

    def decide_or_defer(self, question: Question | str, text: str,
                        context: dict | None = None) -> "Decision | Pending":
        """Two-phase decision for callers that *are* the oracle (e.g. an LLM agent
        using Kadı over MCP). Returns a Decision when Kadı can answer on its own,
        otherwise a Pending ticket: the caller judges the case itself and reports
        the verdict with ``resolve(ticket, label)``. Audit samples are deferred
        too, without revealing Kadı's own answer, so audits stay unbiased."""
        case = self._route(question, text, context)
        if isinstance(case, Decision):
            return case
        ticket = secrets.token_urlsafe(12)
        now = time.monotonic()
        with self._reg:
            while self._pending and (len(self._pending) >= MAX_PENDING
                                     or now - next(iter(self._pending.values())).created > PENDING_TTL):
                self._pending.popitem(last=False)
            self._pending[ticket] = case
        q = case.brain.q
        shown = list(q.options) if case.kind == "audit" else case.pset_labels or list(q.options)
        return Pending(ticket=ticket, question=q.name, options=list(q.options), candidates=shown,
                       reason=case.reason, instructions=q.instructions, expires_in_s=PENDING_TTL)

    def resolve(self, ticket: str, label: str, cost_usd: float = 0.0, model: str = "caller") -> Decision:
        """Complete a deferred decision with the caller's verdict (it becomes the
        oracle label: it trains or calibrates Kadı exactly like an API oracle)."""
        with self._reg:
            case = self._pending.pop(ticket, None)
        if case is None or time.monotonic() - case.created > PENDING_TTL:
            raise KeyError("unknown or expired ticket")
        if label not in case.brain.q.options:
            with self._reg:  # let the caller retry with a valid label
                self._pending[ticket] = case
            raise ValueError(f"label {quote(label)} not in {list(case.brain.q.options)}")
        latency = (time.perf_counter() - case.t0) * 1000
        return self._complete(case, Verdict(label, float(cost_usd), latency, model))

    # ------------------------------------------------------------- the cascade
    def _route(self, question, text, context) -> "Decision | _Case":
        t0 = time.perf_counter()
        brain = self._brain(question)
        q = brain.q
        clean, ctx, key, x = self._prepare(text, context)

        with brain.lock:
            brain.seq += 1
            seq = brain.seq
            brain.maybe_freeze()
            served = brain.served
            cached = brain.memory.get(key)
            probs = served.model.predict_proba(x)
            pset = served.cal.prediction_set(probs)
            novel = served.model.novelty(x, self.novelty_limit) > q.novelty_threshold \
                and "no_novelty" not in self._ablate
            calibrating = not served.cal.calibrated
            recent = brain.recent_tiers
            local_share = (sum(t in ("memory", "reflex") for t in recent) / len(recent)) if recent else 0.0
            probation = brain.probation > 0
            if probation and cached is None and q.mode == "live":
                brain.probation -= 1  # only real (non-replayed) live decisions serve the sentence

        if cached is not None:
            return self._finish(brain, clean, key, cached, "memory", "memory", 1.0, [cached], 0.0, t0)

        # Calibration sample: chosen by a coin whose bias depends only on the
        # court's past (never on this input), so samples stay exchangeable with
        # the traffic. Sampling an escalated case is free (the oracle is called
        # anyway, and the label still trains the live model afterwards); only
        # sampled *local* answers cost an extra oracle call. So the rate is set
        # to keep that extra cost near `sample_budget` calls per decision:
        # everything is sampled while Kadı rarely answers alone, ~audit_rate
        # once it answers most cases itself.
        if "fixed_sampling" in self._ablate:          # v0.5-style fixed rates
            p_sample = 0.25 if calibrating else self.audit_rate
        elif calibrating or q.mode == "shadow":
            p_sample = 1.0
        else:
            p_sample = min(1.0, max(self.audit_rate, self.sample_budget / max(local_share, 1e-3)))
        sampled = self.rng.random() < p_sample
        top = max(range(len(probs)), key=probs.__getitem__)

        local, reason = None, None
        if not pset and not calibrating:
            # An empty set means the oracle's label is outside C(x): a miscoverage
            # event already paid for in the alpha budget. Answering argmax there
            # cannot raise Pr(disagree) above Pr(O(x) not in C(x)) <= alpha, and it
            # keeps the local share monotone in alpha.
            pset = [top]
        if calibrating:
            reason = "uncalibrated"
        elif len(pset) != 1:
            reason = "ambiguous"
        elif pset[0] != top and "no_consistency" not in self._ablate:
            reason = "inconsistent"  # singleton that isn't the model's own best guess
        elif novel:
            reason = "novel"
        elif probation and q.mode == "live":  # shadow keeps measuring, so probation can end
            reason = "probation"
        else:
            local = pset[0]
        pset_labels = [q.options[i] for i in pset]

        if "calibrate_on_escalated" in self._ablate:  # the v0.1 bug: a biased, outcome-dependent sample
            sampled = local is None
        if q.mode == "shadow":
            kind = "shadow"
        elif local is not None:
            if not sampled:
                return self._finish(brain, clean, key, q.options[local], "reflex", "confident", probs[local],
                                    [q.options[local]], 0.0, t0, version=served.id)
            kind, reason = "audit", "audit"
        else:
            kind = "escalate"
        return _Case(brain, kind, text, clean, context, ctx, key, x, probs, pset_labels, local, reason,
                     sampled, t0, time.monotonic(), seq, served.id)

    def _complete(self, c: "_Case", v: Verdict) -> Decision:
        brain, q = c.brain, c.brain.q
        would = q.options[c.local] if c.local is not None else None
        with brain.lock:
            brain.oracle_cost.append(v.cost_usd)
            y = q.index(v.label)
            if c.sampled:
                brain.calibrate(c, y)
            if c.sampled or c.kind == "shadow":   # monitor the deployed risk Pr(local and wrong)
                self._monitor(brain, c, would, v.label)
            brain.live.update(c.x, y)             # every oracle label trains the live model
            brain.dirty += 1
            brain.remember(c.key, v.label)
            if c.kind == "shadow":
                brain.shadow_n += 1
                if would is not None:
                    brain.shadow_local += 1
                    brain.shadow_agree += would == v.label
            elif c.kind == "audit":
                brain.audits += 1
                brain.audit_agree += would == v.label
        if c.kind == "shadow":
            return self._finish(brain, c.clean, c.key, v.label, "oracle", "shadow", 1.0, c.pset_labels, v.cost_usd,
                                c.t0, oracle_label=v.label, shadow_label=would,
                                agreed=None if would is None else int(would == v.label), version=c.version)
        if c.kind == "audit":
            # we paid for the oracle's verdict: return it, even if the reflex disagreed
            return self._finish(brain, c.clean, c.key, v.label, "reflex", "audited", c.probs[c.local], [would],
                                v.cost_usd, c.t0, oracle_label=v.label, audited=1,
                                agreed=int(v.label == would), flagged=int(v.label != would), version=c.version)
        return self._finish(brain, c.clean, c.key, v.label, "oracle", c.reason, 1.0, c.pset_labels, v.cost_usd,
                            c.t0, oracle_label=v.label)

    def _no_verdict(self, c: "_Case") -> Decision:
        if c.kind == "audit":  # the audit failed, the local answer still stands
            label = c.brain.q.options[c.local]
            return self._finish(c.brain, c.clean, c.key, label, "reflex", "confident", c.probs[c.local], [label],
                                0.0, c.t0, version=c.version)
        return self._fallback(c.brain, c.clean, c.key, c.probs, c.pset_labels, c.t0, c.version)

    def decide_many(self, items: list[tuple[Question | str, str, dict | None]]) -> list[Decision | Exception]:
        out: list[Decision | Exception] = []
        for q, text, ctx in items:
            try:
                out.append(self.decide(q, text, ctx))
            except (ValueError, KeyError, OracleError) as e:
                out.append(e)
        return out

    def teach(self, question: Question | str, text: str, label: str, context: dict | None = None) -> None:
        """Feed a gold label (human review, ground truth, backfill). Trains the
        live model but never calibrates: you choose which items to label, so
        they are not a random sample."""
        brain = self._brain(question)
        if label not in brain.q.options:
            raise ValueError(f"label {quote(label)} not in {list(brain.q.options)}")
        _, _, key, x = self._prepare(text, context)
        with brain.lock:
            brain.live.update(x, brain.q.index(label))
            brain.dirty += 1
            brain.remember(key, label)

    def stats(self) -> list[dict]:
        out = []
        for b in list(self._brains.values()):
            with b.lock:
                out.append(b.stats())
        return out

    def checkpoint(self) -> None:
        """Synchronously persist every court (also flushes background writes)."""
        for b in list(self._brains.values()):
            with b.lock:
                job = self._snapshot_job(b)
            self._write(job)

    def close(self) -> None:
        self._writer.stop()
        self.checkpoint()
        self.store.close()

    # ============================================================== internal
    def _prepare(self, text: str, context: dict | None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        if len(text) > MAX_INPUT_CHARS:
            raise ValueError(f"text longer than {MAX_INPUT_CHARS} characters")
        if context is not None and not isinstance(context, dict):
            raise ValueError("context must be an object")
        ctx_json = json.dumps(context, sort_keys=True, ensure_ascii=False) if context else ""
        if len(ctx_json) > MAX_INPUT_CHARS:
            raise ValueError(f"context larger than {MAX_INPUT_CHARS} characters")
        # memory key on the RAW input: redaction must never merge two different inputs
        key = hmac.new(self.secret, normalize(text + "\n" + ctx_json).encode(), hashlib.sha256).hexdigest()
        clean = self.redactor(text) if self.redactor else text
        ctx = context
        if context and self.redactor:
            try:
                ctx = json.loads(self.redactor(ctx_json))
            except json.JSONDecodeError:  # a redaction spanned JSON syntax: keep it as opaque text
                ctx = {"redacted": self.redactor(ctx_json)}
            ctx_json = json.dumps(ctx, sort_keys=True, ensure_ascii=False)
        payload = clean if not ctx_json else clean + "\n" + ctx_json
        return clean, ctx, key, self.featurize(payload)

    def _ask(self, q: Question, text: str, clean: str, context, clean_ctx) -> Verdict | None:
        try:
            if self.redact_oracle:
                return self.oracle.judge(q, clean, clean_ctx)
            return self.oracle.judge(q, text, context)
        except OracleError:
            if self.on_oracle_error == "raise":
                raise
            return None
        except Exception as e:  # network stacks raise many things; never leak them as 500s
            if self.on_oracle_error == "raise":
                raise OracleError(f"{type(e).__name__}: {e}") from e
            return None

    def _fallback(self, b: _Brain, clean, key, probs, pset_labels, t0, version=None) -> Decision:
        i = max(range(len(probs)), key=probs.__getitem__)
        return self._finish(b, clean, key, b.q.options[i], "fallback", "oracle_error", probs[i],
                            pset_labels, 0.0, t0, flagged=1, version=version)

    def _monitor(self, b: _Brain, c: _Case, would: str | None, label: str) -> None:
        """Feed the e-detector with the deployed loss 1{local and wrong} of the
        version that made this decision (lock held)."""
        if c.version != b.served.id or not b.served.cal.calibrated:
            return
        loss = 1.0 if (would is not None and would != label) else 0.0
        if not b.detector.update(loss):
            return
        # Alarm: the served model's risk is above target with strong evidence.
        # Re-certify the same frozen model on data drawn from now on, and
        # escalate at least `probation_length` decisions meanwhile.
        info = b.detector.info()
        b.served = b.new_version(b.served.model, b.seq)
        b.detector = DriftDetector(b.q.target_error, b.drift_arl)
        b.probation = max(b.probation, self.probation_length)
        now = time.time()
        if now - b.last_alert < 3600:
            return
        b.last_alert = now
        alert = {"question": b.q.name, "kind": "drift", "disagreement": info["observed_risk"],
                 "lower_bound": None, "target_error": b.q.target_error, "checks": info["observations"],
                 "detector": info,
                 "action": f"re-certifying the served model; probation for next {b.probation} decisions"}
        self.store.record_alert(b.q.name, "drift", alert)
        if self.alert_hook:
            threading.Thread(target=self._safe_hook, args=(alert,), daemon=True).start()

    def _safe_hook(self, alert: dict) -> None:
        try:
            self.alert_hook(alert)
        except Exception:
            pass

    def _brain(self, q: Question | str) -> _Brain:
        if isinstance(q, str):
            b = self._brains.get(q)
            if b is None:
                raise KeyError(f"unknown question {quote(q)}")
            return b
        b = self._brains.get(q.name)
        if b is not None:
            if b.q.options != q.options:
                raise ValueError(f"question {q.name!r} re-registered with different options")
            return b
        with self._reg:
            if q.name in self._brains:
                return self._brains[q.name]
            b = _Brain(q, self.memory_size, self.reflex, self.drift_arl, self._ablate)
            saved = self.store.load_model(q.name)
            if saved and tuple(saved[0]["options"]) == q.options \
                    and saved[0].get("conditional", False) == q.conditional \
                    and saved[0].get("policy", "conformal") == q.policy:
                self._restore(b, saved[1])
            self._brains[q.name] = b
            return b

    # ------------------------------------------------------------ persistence
    def _restore(self, b: _Brain, st: dict) -> None:
        if st.get("format") == SNAPSHOT_FORMAT:
            try:
                blob = self.store.load_snapshot(b.q.name, st["snapshot_sha256"])
                meta, arrays = snapfmt.loads(blob)
                b.live = self.reflex.unpack(meta["live"], arrays, "live.")
                vs = {}
                for role in ("served", "candidate"):
                    vm = st.get(role)
                    if vm is None:
                        continue
                    model = self.reflex.unpack(meta[role], arrays, role + ".", base=b.live)
                    cal = conformal_from_state(vm["cal"]) if vm["cal"].get("kind") != "none" else _NoCertificate()
                    if hasattr(cal, "target"):
                        cal.target = b.q.target_error
                    vs[role] = _Version(vm["id"], model, cal, vm["frozen_seq"], vm["samples"], vm["trial_n"],
                                        vm["trial_self"], vm["trial_served"], vm.get("served_pmax"))
                b.served = vs["served"]
                b.candidate = vs.get("candidate")
                b.versions_issued, b.seq = st["versions_issued"], st["seq"]
                b.refreeze_floor, b.promotions = st.get("refreeze_floor", 0), st.get("promotions", 0)
                b.detector = DriftDetector.from_state(st["detector"])
            except (OSError, ValueError, KeyError) as e:
                print(f"kadi: could not restore snapshot for {b.q.name!r} ({e}); starting fresh",
                      file=sys.stderr)
                return
        elif "model" in st:
            # v0.5 JSON state: keep what the model learned, but re-issue certificates
            # (old calibration samples were drawn before the current model froze).
            b.live = self.reflex.from_state(st["model"])
            b.served = b.new_version(b.live.snapshot(), 0)
        b.memory.update(st.get("memory", {}))
        for k in ("audits", "audit_agree", "shadow_n", "shadow_local", "shadow_agree", "probation", "cost_total"):
            setattr(b, k, st.get(k, getattr(b, k)))
        b.counts.update(st.get("counts", {}))
        b.oracle_cost.extend(st.get("oracle_cost", []))

    def _snapshot_job(self, b: _Brain) -> dict:
        """Everything needed to persist the court, captured cheaply under its
        lock: frozen versions are immutable, the live model is shallow-copied."""
        live = b.live.snapshot(keep_optimizer=True)
        q = b.q
        # Never hand a mutable object to the background writer: a version whose
        # model *is* the live model (the no_freeze ablation) is packed from the
        # live snapshot, and calibrator / detector states are deep-copied here.
        served_model = live if b.served.model is b.live else b.served.model
        cand_model = None if b.candidate is None else (live if b.candidate.model is b.live else b.candidate.model)
        state = {"format": SNAPSHOT_FORMAT, "versions_issued": b.versions_issued, "seq": b.seq,
                 "refreeze_floor": b.refreeze_floor, "promotions": b.promotions,
                 "served": b.served.meta(), "candidate": b.candidate.meta() if b.candidate else None,
                 "detector": b.detector.state(),
                 "memory": dict(list(b.memory.items())[-5000:]),
                 "audits": b.audits, "audit_agree": b.audit_agree,
                 "shadow_n": b.shadow_n, "shadow_local": b.shadow_local, "shadow_agree": b.shadow_agree,
                 "probation": b.probation, "cost_total": b.cost_total, "counts": dict(b.counts),
                 "oracle_cost": list(b.oracle_cost)}
        spec = {"options": list(q.options), "instructions": q.instructions, "target_error": q.target_error,
                "mode": q.mode, "conditional": q.conditional, "policy": q.policy}
        b.dirty = 0
        b.last_save = b.last_stats = time.time()
        state = json.loads(json.dumps(state))
        return {"name": q.name, "spec": spec, "state": state, "stats": b.stats(), "live": live,
                "served": served_model, "candidate": cand_model}

    def _write(self, job: dict) -> None:
        """Pack and persist a captured job. Runs without any court lock."""
        meta, arrays = {}, {}
        m, a = job["live"].pack("live.")
        meta["live"] = m
        arrays.update(a)
        for role in ("served", "candidate"):
            model = job[role]
            if model is not None:
                m, a = model.pack(role + ".", base=job["live"], trainable=False)
                meta[role] = m
                arrays.update(a)
        blob = snapfmt.dumps(meta, arrays)
        sha = self.store.save_snapshot(job["name"], blob)
        state = dict(job["state"], snapshot_sha256=sha, snapshot_bytes=len(blob))
        self.store.save_model(job["name"], job["spec"], state)
        self.store.save_qstats(job["name"], job["stats"])

    def _finish(self, b: _Brain, clean, key, label, tier, reason, conf, pset, cost, t0,
                oracle_label=None, shadow_label=None, audited=0, agreed=None, flagged=0,
                version=None) -> Decision:
        latency = (time.perf_counter() - t0) * 1000
        did = self.store.record(
            ts=time.time(), question=b.q.name, input_hash=key,
            preview=(" ".join(clean.split())[:160] if self.store_inputs else None),
            label=label, tier=tier, reason=reason, confidence=round(conf, 5), set_size=len(pset),
            oracle_label=oracle_label, shadow_label=shadow_label, audited=audited, agreed=agreed,
            flagged=flagged, cost=cost, latency_ms=round(latency, 3), model_version=version)
        job = None
        with b.lock:
            b.recent_tiers.append(tier)
            b.counts[tier] += 1
            b.cost_total += cost
            now = time.time()
            if b.dirty and now - b.last_save > self.checkpoint_seconds:
                job = self._snapshot_job(b)
            elif now - b.last_stats > 1.0:
                self.store.save_qstats(b.q.name, b.stats())
                b.last_stats = now
        if job is not None:
            self._writer.submit(job)   # packed and written off the request path
        return Decision(did, b.q.name, label, tier, round(conf, 5), pset, cost, round(latency, 3),
                        reason, bool(flagged))


class _CheckpointWriter:
    """Single background thread that packs and writes checkpoints. Jobs are
    coalesced per court (only the newest matters), so a slow disk can never
    queue up work or block decisions."""

    def __init__(self, engine: Kadi):
        self.engine = engine
        self.jobs: dict[str, dict] = {}
        self.cv = threading.Condition()
        self.alive = True
        self.thread: threading.Thread | None = None

    def submit(self, job: dict) -> None:
        with self.cv:
            self.jobs[job["name"]] = job
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name="kadi-checkpoint", daemon=True)
                self.thread.start()
            self.cv.notify()

    def _run(self) -> None:
        while True:
            with self.cv:
                while self.alive and not self.jobs:
                    self.cv.wait()
                if not self.jobs and not self.alive:
                    return
                _, job = self.jobs.popitem()
            try:
                self.engine._write(job)
            except Exception as e:  # never kill the writer; the next checkpoint retries
                print(f"kadi: checkpoint of {job['name']!r} failed: {type(e).__name__}: {e}", file=sys.stderr)

    def stop(self) -> None:
        with self.cv:
            self.alive = False
            self.cv.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=60)
