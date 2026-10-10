"""The Kadı cascade.

    input ──► memory  (exact replay of a past oracle verdict)        ~µs, $0
          └─► reflex  (local model, answers only if its conformal
                       prediction set is a single label, the input is
                       not novel, and the court is not on probation)  ~ms, $0
          └─► oracle  (frontier model; its verdict trains the reflex
                       and calibrates the guarantee)                  ~s,  $$
          └─► fallback (oracle down + on_oracle_error="best_guess":
                       best local guess, flagged)                     ~ms, $0

Safety layers, in order:
  * schema lock     - every answer is one of the declared options
  * conformal set   - local answers only when the error bound allows (marginal
                      or per-label / Mondrian)
  * novelty guard   - inputs unlike anything trained on are escalated
  * audits          - a random slice of local answers is re-asked to the oracle
  * drift breaker   - if audited disagreement is significantly above target,
                      the court goes on probation (escalate everything) and an
                      alert fires
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
import threading
import time
import warnings
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from typing import Callable

from .conformal import AdaptiveConformal, LearnThenTest, MondrianConformal, conformal_from_state
from .features import HashingFeaturizer, normalize
from .learner import OnlineSoftmax
from .oracles import Oracle, OracleError, Verdict
from .questions import Question
from .store import Store, derive_chain_key

MAX_INPUT_CHARS = 32_000
RESCORE_EVERY = 25          # re-score calibration set after this many training updates...
RESCORE_BUDGET = 0.10       # ...but spend at most ~10% of wall time re-scoring
WARMUP_HOLDOUT = 0.25       # share of warm-up oracle labels held out for calibration
SHADOW_HOLDOUT = 0.20       # same, in shadow mode (every decision has an oracle label)
TIERS = ("memory", "reflex", "oracle", "fallback")
PENDING_TTL = 3600.0        # seconds a deferred decision stays resolvable
MAX_PENDING = 10_000


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
    probs: list[float]
    pset_labels: list[str]
    local: int | None
    reason: str
    sampled: bool
    t0: float
    created: float


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


class _Brain:
    def __init__(self, q: Question, memory_size: int, reflex=OnlineSoftmax):
        self.q = q
        self.model = reflex(len(q.options))
        self.conformal = (LearnThenTest(q.target_error, q.delta) if q.policy == "ltt"
                          else MondrianConformal(len(q.options), q.target_error) if q.conditional
                          else AdaptiveConformal(q.target_error))
        self.memory: OrderedDict[str, str] = OrderedDict()
        self.memory_size = memory_size
        self.lock = threading.Lock()
        self.oracle_cost: deque[float] = deque(maxlen=200)
        self.recent_tiers: deque[str] = deque(maxlen=500)
        self.checks: deque[bool] = deque(maxlen=300)   # audit + shadow agreement, for drift
        self.counts = {t: 0 for t in TIERS}
        self.cost_total = 0.0
        self.audits = self.audit_agree = 0
        self.shadow_n = self.shadow_local = self.shadow_agree = 0
        self.probation = 0
        self.last_alert = 0.0
        self.dirty = 0
        self.updates_since_rescore = RESCORE_EVERY   # force a first rescore (e.g. after a reload)
        self.last_rescore = 0.0
        self.rescore_cost = 0.0
        self.last_save = time.time()
        self.last_stats = 0.0

    # all methods below assume self.lock is held
    def remember(self, key: str, label: str) -> None:
        self.memory[key] = label
        self.memory.move_to_end(key)
        while len(self.memory) > self.memory_size:
            self.memory.popitem(last=False)

    def learn(self, x, probs, label: str, calibrate: bool) -> None:
        """Train on an oracle/gold label. Only *randomly sampled* labels may
        calibrate: escalated examples are a biased sample (their true label is
        in the set by construction), and calibrating on them makes the
        threshold ratchet looser and looser."""
        y = self.q.index(label)
        if calibrate:
            self.conformal.observe(x, probs, y)   # held out: never trained on
        else:
            self.model.update(x, y)
            self.updates_since_rescore += 1
        self.dirty += 1

    def refresh(self) -> None:
        now = time.perf_counter()
        if (self.updates_since_rescore >= RESCORE_EVERY
                and now - self.last_rescore >= self.rescore_cost / RESCORE_BUDGET):
            self.conformal.rescore(self.model.predict_proba)
            self.last_rescore = time.perf_counter()
            self.rescore_cost = self.last_rescore - now
            self.updates_since_rescore = 0

    def avg_oracle_cost(self) -> float:
        return sum(self.oracle_cost) / len(self.oracle_cost) if self.oracle_cost else 0.0

    def drift(self) -> tuple[float, float, int]:
        """(observed disagreement, lower 95% bound, n) over recent checks."""
        n = len(self.checks)
        if not n:
            return 0.0, 0.0, 0
        rate = 1 - sum(self.checks) / n
        return rate, rate - 1.96 * math.sqrt(max(rate * (1 - rate), 1e-9) / n), n

    def stats(self) -> dict:
        n = len(self.recent_tiers) or 1
        c = self.conformal
        rate, lower, nchk = self.drift()
        return {
            "question": self.q.name, "options": list(self.q.options), "kind": self.q.meta.get("kind"),
            "mode": self.q.mode, "conditional": self.q.conditional, "policy": self.q.policy,
            "calibrator": {k: v for k, v in c.info().items() if v is None or isinstance(v, (int, float))
                           and math.isfinite(v)},
            "target_error": self.q.target_error, "alpha_t": round(c.alpha_t, 5),
            "calibration_size": c.calibration_size, "calibrated": c.calibrated,
            "realized_miscoverage": (c.misses / c.observed) if c.observed else None,
            "trained_on": self.model.seen,
            "local_rate_recent": sum(t in ("memory", "reflex") for t in self.recent_tiers) / n,
            "counts": dict(self.counts), "cost_total": self.cost_total,
            "audits": self.audits,
            "audit_agreement": (self.audit_agree / self.audits) if self.audits else None,
            "shadow": {"n": self.shadow_n,
                       "would_be_local": (self.shadow_local / self.shadow_n) if self.shadow_n else None,
                       "agreement": (self.shadow_agree / self.shadow_local) if self.shadow_local else None},
            "drift": {"disagreement": rate, "lower_bound": lower, "n": nchk},
            "probation": self.probation,
            "avg_oracle_cost": self.avg_oracle_cost(), "memory_entries": len(self.memory),
        }


class Kadi:
    def __init__(self, oracle: Oracle, db: str = "kadi.db", *, audit_rate: float = 0.05,
                 store_inputs: bool = True, redact: bool | Callable[[str], str] = True,
                 redact_oracle: bool = False, secret: bytes | str | None = None,
                 on_oracle_error: str = "raise", memory_size: int = 50_000,
                 checkpoint_seconds: float = 15.0, probation_length: int = 300,
                 alert_hook: Callable[[dict], None] | None = None, seed: int | None = None,
                 featurizer: Callable[[str], dict[int, float]] | None = None, reflex=None):
        if not 0 <= audit_rate <= 1:
            raise ValueError("audit_rate must be in [0, 1]")
        if on_oracle_error not in ("raise", "best_guess"):
            raise ValueError('on_oracle_error must be "raise" or "best_guess"')
        self.oracle = oracle
        self.store = Store(db)
        self.audit_rate = audit_rate
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
        self.alert_hook = alert_hook
        self.featurize = featurizer or HashingFeaturizer()
        self.novelty_limit = getattr(self.featurize, "hashed_dim", None)
        # reflex factory: callable(n_classes) -> model, plus .from_state(dict) -> model
        self.reflex = reflex or OnlineSoftmax
        self.rng = random.Random(seed)
        self._brains: dict[str, _Brain] = {}
        self._reg = threading.Lock()
        self._pending: OrderedDict[str, _Case] = OrderedDict()

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
            raise ValueError(f"label {label!r} not in {list(case.brain.q.options)}")
        latency = (time.perf_counter() - case.t0) * 1000
        return self._complete(case, Verdict(label, float(cost_usd), latency, model))

    # ------------------------------------------------------------- the cascade
    def _route(self, question, text, context) -> "Decision | _Case":
        t0 = time.perf_counter()
        brain = self._brain(question)
        q = brain.q
        clean, ctx, key, x = self._prepare(text, context)

        with brain.lock:
            brain.refresh()
            cached = brain.memory.get(key)
            probs = brain.model.predict_proba(x)
            pset = brain.conformal.prediction_set(probs)
            novel = brain.model.novelty(x, self.novelty_limit) > q.novelty_threshold
            calibrating = not brain.conformal.calibrated
            probation = brain.probation > 0
            if probation and cached is None and q.mode == "live":
                brain.probation -= 1  # only real (non-replayed) live decisions serve the sentence

        if cached is not None:
            return self._finish(brain, clean, key, cached, "memory", "memory", 1.0, [cached], 0.0, t0)

        # Calibration sample: an i.i.d. slice of the stream whose oracle label is held
        # out for calibration (and, for local answers, doubles as an audit).
        p_sample = WARMUP_HOLDOUT if calibrating else SHADOW_HOLDOUT if q.mode == "shadow" else self.audit_rate
        sampled = self.rng.random() < p_sample
        top = max(range(len(probs)), key=probs.__getitem__)

        local, reason = None, None
        if calibrating:
            reason = "uncalibrated"
        elif len(pset) != 1:
            reason = "empty_set" if not pset else "ambiguous"
        elif pset[0] != top:
            reason = "inconsistent"  # singleton that isn't the model's own best guess
        elif novel:
            reason = "novel"
        elif probation and q.mode == "live":  # shadow keeps measuring, so probation can end
            reason = "probation"
        else:
            local = pset[0]
        pset_labels = [q.options[i] for i in pset]

        if q.mode == "shadow":
            kind = "shadow"
        elif local is not None:
            if not sampled:
                return self._finish(brain, clean, key, q.options[local], "reflex", "confident", probs[local],
                                    [q.options[local]], 0.0, t0)
            kind, reason = "audit", "audit"
        else:
            kind = "escalate"
        return _Case(brain, kind, text, clean, context, ctx, key, x, probs, pset_labels, local, reason,
                     sampled, t0, time.monotonic())

    def _complete(self, c: "_Case", v: Verdict) -> Decision:
        brain, q = c.brain, c.brain.q
        if c.kind == "shadow":
            would = q.options[c.local] if c.local is not None else None
            with brain.lock:
                brain.shadow_n += 1
                if would is not None:
                    brain.shadow_local += 1
                    brain.shadow_agree += would == v.label
                    brain.checks.append(would == v.label)
                self._absorb(brain, c.key, c.x, c.probs, v, calibrate=c.sampled)
                self._check_drift(brain)
            return self._finish(brain, c.clean, c.key, v.label, "oracle", "shadow", 1.0, c.pset_labels, v.cost_usd,
                                c.t0, oracle_label=v.label, shadow_label=would,
                                agreed=None if would is None else int(would == v.label))
        if c.kind == "audit":
            label = q.options[c.local]
            with brain.lock:
                brain.audits += 1
                brain.audit_agree += v.label == label
                brain.checks.append(v.label == label)
                self._absorb(brain, c.key, c.x, c.probs, v, calibrate=True)
                self._check_drift(brain)
            # we paid for the oracle's verdict: return it, even if the reflex disagreed
            return self._finish(brain, c.clean, c.key, v.label, "reflex", "audited", c.probs[c.local], [label],
                                v.cost_usd, c.t0, oracle_label=v.label, audited=1,
                                agreed=int(v.label == label), flagged=int(v.label != label))
        with brain.lock:
            self._absorb(brain, c.key, c.x, c.probs, v, calibrate=c.sampled)
        return self._finish(brain, c.clean, c.key, v.label, "oracle", c.reason, 1.0, c.pset_labels, v.cost_usd,
                            c.t0, oracle_label=v.label)

    def _no_verdict(self, c: "_Case") -> Decision:
        if c.kind == "audit":  # the audit failed, the local answer still stands
            label = c.brain.q.options[c.local]
            return self._finish(c.brain, c.clean, c.key, label, "reflex", "confident", c.probs[c.local], [label],
                                0.0, c.t0)
        return self._fallback(c.brain, c.clean, c.key, c.probs, c.pset_labels, c.t0)

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
        reflex but never calibrates: you choose which items to label, so they
        are not a random sample."""
        brain = self._brain(question)
        if label not in brain.q.options:
            raise ValueError(f"label {label!r} not in {brain.q.options}")
        _, _, key, x = self._prepare(text, context)
        with brain.lock:
            brain.learn(x, brain.model.predict_proba(x), label, calibrate=False)
            brain.remember(key, label)

    def stats(self) -> list[dict]:
        out = []
        for b in list(self._brains.values()):
            with b.lock:
                out.append(b.stats())
        return out

    def checkpoint(self) -> None:
        for b in list(self._brains.values()):
            with b.lock:
                self._save(b)

    def close(self) -> None:
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

    def _absorb(self, b: _Brain, key: str, x, probs, v: Verdict, calibrate: bool) -> None:
        b.oracle_cost.append(v.cost_usd)
        b.learn(x, probs, v.label, calibrate)
        b.remember(key, v.label)

    def _fallback(self, b: _Brain, clean, key, probs, pset_labels, t0) -> Decision:
        i = max(range(len(probs)), key=probs.__getitem__)
        return self._finish(b, clean, key, b.q.options[i], "fallback", "oracle_error", probs[i],
                            pset_labels, 0.0, t0, flagged=1)

    def _check_drift(self, b: _Brain) -> None:
        rate, lower, n = b.drift()
        if n < 50 or lower <= b.q.target_error:
            return
        if b.probation == 0:
            b.probation = self.probation_length
        now = time.time()
        if now - b.last_alert < 3600:
            return
        b.last_alert = now
        alert = {"question": b.q.name, "kind": "drift", "disagreement": round(rate, 4),
                 "lower_bound": round(lower, 4), "target_error": b.q.target_error, "checks": n,
                 "action": f"probation for next {b.probation} decisions (all escalated)"}
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
                raise KeyError(f"unknown question {q!r}")
            return b
        b = self._brains.get(q.name)
        if b is not None:
            if b.q.options != q.options:
                raise ValueError(f"question {q.name!r} re-registered with different options")
            return b
        with self._reg:
            if q.name in self._brains:
                return self._brains[q.name]
            b = _Brain(q, self.memory_size, self.reflex)
            saved = self.store.load_model(q.name)
            if saved and tuple(saved[0]["options"]) == q.options \
                    and saved[0].get("conditional", False) == q.conditional \
                    and saved[0].get("policy", "conformal") == q.policy:
                st = saved[1]
                b.model = self.reflex.from_state(st["model"])
                b.conformal = conformal_from_state(st["conformal"])
                b.conformal.target = q.target_error
                b.memory.update(st.get("memory", {}))
                for k in ("audits", "audit_agree", "shadow_n", "shadow_local", "shadow_agree",
                          "probation", "cost_total"):
                    setattr(b, k, st.get(k, getattr(b, k)))
                b.counts.update(st.get("counts", {}))
                b.oracle_cost.extend(st.get("oracle_cost", []))
                b.checks.extend(st.get("checks", []))
            self._brains[q.name] = b
            return b

    def _save(self, b: _Brain) -> None:
        state = {"model": b.model.state(), "conformal": b.conformal.state(),
                 "memory": dict(list(b.memory.items())[-5000:]),
                 "audits": b.audits, "audit_agree": b.audit_agree,
                 "shadow_n": b.shadow_n, "shadow_local": b.shadow_local, "shadow_agree": b.shadow_agree,
                 "probation": b.probation, "cost_total": b.cost_total, "counts": b.counts,
                 "oracle_cost": list(b.oracle_cost), "checks": list(b.checks)}
        q = b.q
        self.store.save_model(q.name, {"options": list(q.options), "instructions": q.instructions,
                                       "target_error": q.target_error, "mode": q.mode,
                                       "conditional": q.conditional, "policy": q.policy}, state)
        self.store.save_qstats(q.name, b.stats())
        b.dirty = 0
        b.last_save = b.last_stats = time.time()

    def _finish(self, b: _Brain, clean, key, label, tier, reason, conf, pset, cost, t0,
                oracle_label=None, shadow_label=None, audited=0, agreed=None, flagged=0) -> Decision:
        latency = (time.perf_counter() - t0) * 1000
        did = self.store.record(
            ts=time.time(), question=b.q.name, input_hash=key,
            preview=(" ".join(clean.split())[:160] if self.store_inputs else None),
            label=label, tier=tier, reason=reason, confidence=round(conf, 5), set_size=len(pset),
            oracle_label=oracle_label, shadow_label=shadow_label, audited=audited, agreed=agreed,
            flagged=flagged, cost=cost, latency_ms=round(latency, 3))
        with b.lock:
            b.recent_tiers.append(tier)
            b.counts[tier] += 1
            b.cost_total += cost
            now = time.time()
            if b.dirty and now - b.last_save > self.checkpoint_seconds:
                self._save(b)
            elif now - b.last_stats > 1.0:
                self.store.save_qstats(b.q.name, b.stats())
                b.last_stats = now
        return Decision(did, b.q.name, label, tier, round(conf, 5), pset, cost, round(latency, 3),
                        reason, bool(flagged))
