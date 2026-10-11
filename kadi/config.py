"""kadi.toml loader. Secrets are never stored in the file, only env var names.

    [kadi]
    db = "kadi.db"
    audit_rate = 0.05
    store_inputs = true
    redact = true              # PII redaction before storage / featurization
    redact_oracle = false      # also redact what is sent to the oracle
    on_oracle_error = "best_guess"   # or "raise"
    retention_days = 30
    reflex = "hashed"          # or "embed": semantic k-NN + embeddings (pip install "kadi-cascade[embed]")
    # embed_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    [server]
    host = "127.0.0.1"
    port = 8765
    token_env = "KADI_TOKEN"
    rate_limit_per_minute = 1200

    [oracle]
    provider = "anthropic"     # or "openai_compatible"
    model = "claude-opus-5-5"
    api_key_env = "ANTHROPIC_API_KEY"
    input_usd_per_mtok = 0.0
    output_usd_per_mtok = 0.0

    [alerts]
    webhook_env = "KADI_WEBHOOK"

    [[question]]
    name = "route_ticket"
    options = ["billing", "bug", "feature_request", "account", "spam"]
    instructions = "Which team should handle this support ticket?"
    target_error = 0.03
    mode = "shadow"
    policy = "ltt"             # "conformal" (expected bound) or "ltt" (holds with prob 1 - delta)
    delta = 0.05
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field

from .alerts import webhook
from .engine import Kadi
from .oracles import AnthropicOracle, OpenAICompatibleOracle
from .questions import Question

EXAMPLE = __doc__.split("\n\n", 1)[1].replace("\n    ", "\n").strip() + "\n"


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    token: str | None = None
    rate_limit_per_minute: int = 1200
    retention_days: float | None = None


@dataclass
class Config:
    kadi: dict = field(default_factory=dict)
    server: ServerConfig = field(default_factory=ServerConfig)
    oracle: dict = field(default_factory=dict)
    alerts: dict = field(default_factory=dict)
    questions: list[Question] = field(default_factory=list)


def _env(name: str | None) -> str | None:
    return os.environ.get(name) if name else None


def load(path: str) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    unknown = set(raw) - {"kadi", "server", "oracle", "alerts", "question"}
    if unknown:
        raise ValueError(f"unknown sections in {path}: {sorted(unknown)}")
    s = raw.get("server", {})
    k = raw.get("kadi", {})
    cfg = Config(
        kadi=k,
        server=ServerConfig(host=s.get("host", "127.0.0.1"), port=int(s.get("port", 8765)),
                            token=_env(s.get("token_env", "KADI_TOKEN")),
                            rate_limit_per_minute=int(s.get("rate_limit_per_minute", 1200)),
                            retention_days=k.get("retention_days")),
        oracle=raw.get("oracle", {}),
        alerts=raw.get("alerts", {}),
    )
    names = set()
    for qd in raw.get("question", []):
        q = Question(name=qd["name"], options=tuple(qd["options"]), instructions=qd.get("instructions", ""),
                     target_error=float(qd.get("target_error", 0.05)), mode=qd.get("mode", "live"),
                     conditional=bool(qd.get("conditional", False)),
                     novelty_threshold=float(qd.get("novelty_threshold", 0.8)),
                     policy=qd.get("policy", "conformal"), delta=float(qd.get("delta", 0.05)),
                     meta={"kind": qd.get("kind", "choice")})
        if q.name in names:
            raise ValueError(f"duplicate question {q.name!r}")
        names.add(q.name)
        cfg.questions.append(q)
    if not cfg.questions:
        raise ValueError("config defines no [[question]]")
    return cfg


def build_oracle(o: dict):
    provider = o.get("provider", "anthropic")
    common = dict(input_usd_per_mtok=float(o.get("input_usd_per_mtok", 0)),
                  output_usd_per_mtok=float(o.get("output_usd_per_mtok", 0)),
                  timeout=float(o.get("timeout", 60)))
    if provider == "anthropic":
        return AnthropicOracle(model=o.get("model", "claude-opus-5-5"),
                               api_key=_env(o.get("api_key_env", "ANTHROPIC_API_KEY")), **common)
    if provider == "openai_compatible":
        return OpenAICompatibleOracle(model=o["model"], base_url=o.get("base_url", "http://localhost:11434/v1"),
                                      api_key=_env(o.get("api_key_env", "OPENAI_API_KEY")), **common)
    raise ValueError(f"unknown oracle provider {provider!r}")


def build_engine(cfg: Config, oracle=None) -> Kadi:
    k = cfg.kadi
    hook_url = _env(cfg.alerts.get("webhook_env", "KADI_WEBHOOK"))
    featurizer = reflex = None
    if k.get("reflex", "hashed") == "embed":
        from .embed import MULTILINGUAL, FastEmbedder, HybridFeaturizer, KNNHybridReflex
        featurizer = HybridFeaturizer(FastEmbedder(k.get("embed_model", MULTILINGUAL)))
        reflex = KNNHybridReflex()
    elif k.get("reflex", "hashed") != "hashed":
        raise ValueError('kadi.reflex must be "hashed" or "embed"')
    engine = Kadi(oracle or build_oracle(cfg.oracle), db=k.get("db", "kadi.db"), featurizer=featurizer, reflex=reflex,
                  audit_rate=float(k.get("audit_rate", 0.05)), store_inputs=bool(k.get("store_inputs", True)),
                  redact=bool(k.get("redact", True)), redact_oracle=bool(k.get("redact_oracle", False)),
                  on_oracle_error=k.get("on_oracle_error", "raise"),
                  alert_hook=webhook(hook_url) if hook_url else None)
    engine.register(*cfg.questions)
    return engine
