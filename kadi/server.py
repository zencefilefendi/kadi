"""Kadı HTTP service + Divan dashboard. Zero dependencies.

Security posture:
  * bearer-token auth on every /api/* and /metrics route (constant-time compare)
  * refuses to listen on a non-loopback address without a token
  * per-client token-bucket rate limit, 256 KB body cap, strict JSON validation
  * CSP / frame / sniffing / referrer headers; the dashboard page itself holds
    no data and fetches everything through the authenticated API
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .oracles import OracleError
from .store import Store

DASHBOARD = Path(__file__).with_name("dashboard.html")
MAX_BODY = 256 * 1024
MAX_BATCH = 100
SECURITY_HEADERS = {
    "content-security-policy": ("default-src 'none'; script-src 'self' 'unsafe-inline'; "
                                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                "font-src https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:; "
                                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"),
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


# ------------------------------------------------------------------ queries
def summary(store: Store, window: float | None = None) -> dict:
    since = time.time() - window if window else 0.0
    qrows = store.query("SELECT question, stats FROM qstats ORDER BY question")
    qstats = {r["question"]: json.loads(r["stats"]) for r in qrows}
    per_q = {r["question"]: r for r in store.query("""
        SELECT question, COUNT(*) n,
               SUM(tier='memory') memory, SUM(tier='reflex') reflex, SUM(tier='oracle') oracle,
               SUM(tier='fallback') fallback, SUM(cost) cost, AVG(latency_ms) latency,
               SUM(audited) audits, SUM(CASE WHEN audited=1 THEN agreed END) agreed
        FROM decisions WHERE ts >= ? GROUP BY question""", (since,))}
    reasons = store.query("""SELECT question, reason, COUNT(*) n FROM decisions
                             WHERE ts >= ? AND tier='oracle' GROUP BY question, reason""", (since,))
    questions, total_cf = [], 0.0
    for name in sorted(set(qstats) | set(per_q)):
        s = qstats.get(name, {})
        r = per_q.get(name) or {"question": name, "n": 0, "memory": 0, "reflex": 0, "oracle": 0,
                                "fallback": 0, "cost": 0.0, "latency": None, "audits": 0, "agreed": 0}
        cf = r["n"] * (s.get("avg_oracle_cost") or 0.0)
        total_cf += cf
        questions.append({**s, **r, "counterfactual": cf,
                          "escalations": {x["reason"]: x["n"] for x in reasons if x["question"] == name}})
    t = store.query("""
        SELECT COUNT(*) n, COALESCE(SUM(tier='memory'),0) memory, COALESCE(SUM(tier='reflex'),0) reflex,
               COALESCE(SUM(tier='oracle'),0) oracle, COALESCE(SUM(tier='fallback'),0) fallback,
               COALESCE(SUM(cost),0) cost, COALESCE(SUM(audited),0) audits, COALESCE(SUM(agreed),0) agreed,
               AVG(CASE WHEN tier IN ('memory','reflex') THEN latency_ms END) local_latency,
               AVG(CASE WHEN tier='oracle' THEN latency_ms END) oracle_latency,
               MIN(ts) t0, MAX(ts) t1
        FROM decisions WHERE ts >= ?""", (since,))[0]
    t["agreed"] = store.query("SELECT COALESCE(SUM(agreed),0) a FROM decisions WHERE ts >= ? AND audited=1",
                              (since,))[0]["a"]
    t["counterfactual"] = total_cf
    t["saved"] = max(0.0, total_cf - (t["cost"] or 0.0))
    alerts = store.query("SELECT id, ts, question, kind, detail FROM alerts ORDER BY id DESC LIMIT 10")
    for a in alerts:
        a["detail"] = json.loads(a["detail"])
    return {"totals": t, "questions": questions, "alerts": alerts, "window": window}


def timeline(store: Store, bins: int = 60, window: float | None = None) -> list[dict]:
    bins = max(1, min(bins, 500))
    since = time.time() - window if window else 0.0
    span = store.query("SELECT MIN(ts) a, MAX(ts) b FROM decisions WHERE ts >= ?", (since,))[0]
    if span["a"] is None:
        return []
    a, b = span["a"], span["b"]
    width = max((b - a) / bins, 1e-6)
    rows = store.query(f"""
        SELECT MIN(CAST((ts - ?) / ? AS INTEGER), {bins - 1}) bin,
               SUM(tier='memory') memory, SUM(tier='reflex') reflex, SUM(tier='oracle') oracle,
               SUM(tier='fallback') fallback, SUM(cost) cost
        FROM decisions WHERE ts >= ? GROUP BY bin ORDER BY bin""", (a, width, a))
    by = {r["bin"]: r for r in rows}
    empty = {"memory": 0, "reflex": 0, "oracle": 0, "fallback": 0, "cost": 0.0}
    return [{"t": a + i * width, **(by.get(i) or empty)} for i in range(bins)]


def feed(store: Store, after: int = 0, limit: int = 40) -> list[dict]:
    return store.query("""SELECT id, ts, question, preview, label, tier, reason, confidence, set_size,
                                 oracle_label, shadow_label, audited, agreed, flagged, cost, latency_ms
                          FROM decisions WHERE id > ? ORDER BY id DESC LIMIT ?""", (after, min(limit, 200)))


def metrics(store: Store) -> str:
    lines = [
        "# HELP kadi_decisions_total Decisions by tier.", "# TYPE kadi_decisions_total counter",
    ]
    stats = [json.loads(r["stats"]) for r in store.query("SELECT stats FROM qstats")]
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    for s in stats:
        for tier, n in (s.get("counts") or {}).items():
            lines.append(f'kadi_decisions_total{{question="{esc(s["question"])}",tier="{tier}"}} {n}')
    gauges = [("kadi_cost_usd_total", "cost_total", "counter", "Oracle spend in USD."),
              ("kadi_alpha_t", "alpha_t", "gauge", "Live ACI miscoverage level."),
              ("kadi_target_error", "target_error", "gauge", "Configured error target."),
              ("kadi_local_rate", "local_rate_recent", "gauge", "Share decided locally (recent 500)."),
              ("kadi_audit_agreement", "audit_agreement", "gauge", "Audited agreement with oracle."),
              ("kadi_probation", "probation", "gauge", "Decisions left on probation (drift breaker).")]
    for metric, key, typ, help_ in gauges:
        lines += [f"# HELP {metric} {help_}", f"# TYPE {metric} {typ}"]
        for s in stats:
            if s.get(key) is not None:
                lines.append(f'{metric}{{question="{esc(s["question"])}"}} {float(s[key])}')
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- server
class _RateLimiter:
    def __init__(self, per_minute: int):
        self.rate = per_minute / 60.0
        self.cap = max(1.0, per_minute / 6.0)  # 10 s burst
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()
        self.last_prune = 0.0

    def allow(self, key: str) -> float:
        """0 if allowed, else seconds until a token is available."""
        if self.rate <= 0:
            return 0.0
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(key, (self.cap, now))
            tokens = min(self.cap, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self.buckets[key] = (tokens - 1, now)
                if len(self.buckets) > 10_000 and now - self.last_prune > 10:
                    self.last_prune = now
                    live = sorted(self.buckets.items(), key=lambda kv: kv[1][1], reverse=True)
                    self.buckets = dict(kv for kv in live[:10_000] if now - kv[1][1] < 120)
                return 0.0
            self.buckets[key] = (tokens, now)
            return (1 - tokens) / self.rate


class _HTTPError(Exception):
    def __init__(self, code: int, msg: str, headers: dict | None = None):
        super().__init__(msg)
        self.code, self.msg, self.headers = code, msg, headers or {}


def make_handler(store: Store, engine=None, token: str | None = None, rate_limit_per_minute: int = 1200):
    limiter = _RateLimiter(rate_limit_per_minute)
    failed_auth = _RateLimiter(max(6, rate_limit_per_minute // 20))  # separate bucket: bad tokens can't
                                                                       # exhaust legitimate callers' quota
    token_b = token.encode() if token else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "kadi"
        sys_version = ""
        timeout = 15  # slow-client (slowloris) guard

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
                self.send_header(k, v)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200, extra=None):
            self._send(code, json.dumps(obj, default=float).encode(), "application/json", extra)

        def _origin_guard(self):
            """Anti DNS-rebinding / CSRF: the Host must be ours, and a browser Origin must match it."""
            host = (self.headers.get("host") or "").lower()
            if host.startswith("["):
                hostname = host[1:host.find("]")] if "]" in host else ""
            else:
                hostname = host.rsplit(":", 1)[0]
            if token_b is None and hostname not in ("localhost", "127.0.0.1", "::1"):
                raise _HTTPError(403, "forbidden host")
            origin = self.headers.get("origin")
            if origin and origin != "null":
                o = urlparse(origin)
                if o.netloc.lower() != host.lower():
                    raise _HTTPError(403, "cross-origin request refused")
            elif origin == "null":
                raise _HTTPError(403, "cross-origin request refused")

        def _auth(self):
            if token_b is None:
                return
            h = self.headers.get("authorization", "")
            given = h[7:].strip().encode() if h[:7].lower() == "bearer " else b""
            if not hmac.compare_digest(given, token_b):
                raise _HTTPError(401, "unauthorized", {"www-authenticate": "Bearer"})

        def _limit(self):
            wait = limiter.allow(self.client_address[0])
            if wait:
                raise _HTTPError(429, "rate limited", {"retry-after": str(max(1, round(wait)))})

        def _body(self) -> dict:
            try:
                n = int(self.headers.get("content-length", "0"))
            except ValueError:
                raise _HTTPError(400, "bad content-length")
            if n < 0:
                raise _HTTPError(400, "bad content-length")
            if n > MAX_BODY:
                raise _HTTPError(413, "body too large")
            if self.headers.get_content_type() != "application/json":
                raise _HTTPError(415, "content-type must be application/json")
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
                raise _HTTPError(400, "invalid JSON")
            if not isinstance(data, dict):
                raise _HTTPError(400, "body must be a JSON object")
            return data

        def _dispatch(self, method: str):
            u = urlparse(self.path)
            qs = parse_qs(u.query)
            arg = lambda k, d: qs.get(k, [d])[0]  # noqa: E731
            if method == "GET" and u.path in ("/", "/index.html"):
                return self._send(200, DASHBOARD.read_bytes(), "text/html; charset=utf-8")
            if method == "GET" and u.path == "/healthz":
                return self._json({"ok": True})
            if not (u.path.startswith("/api/") or u.path == "/metrics"):
                raise _HTTPError(404, "not found")
            self._origin_guard()
            try:
                self._auth()
            except _HTTPError:
                wait = failed_auth.allow(self.client_address[0])
                if wait:
                    raise _HTTPError(429, "rate limited", {"retry-after": str(max(1, round(wait)))})
                raise
            self._limit()
            try:
                window = float(arg("window", "0")) or None
                if method == "GET" and u.path == "/metrics":
                    return self._send(200, metrics(store).encode(), "text/plain; version=0.0.4")
                if method == "GET" and u.path == "/api/summary":
                    return self._json(summary(store, window))
                if method == "GET" and u.path == "/api/timeline":
                    return self._json(timeline(store, int(arg("bins", "60")), window))
                if method == "GET" and u.path == "/api/feed":
                    return self._json(feed(store, int(arg("after", "0"))))
            except ValueError:
                raise _HTTPError(400, "bad query parameter")
            if method == "GET" and u.path == "/api/questions":
                qs_ = engine.questions.values() if engine else []
                return self._json([{"name": q.name, "options": list(q.options), "mode": q.mode,
                                    "target_error": q.target_error, "conditional": q.conditional,
                                    "policy": q.policy, "delta": q.delta,
                                    "instructions": q.instructions} for q in qs_])
            if method == "POST" and u.path in ("/api/decide", "/api/decide/batch", "/api/teach"):
                if engine is None:
                    raise _HTTPError(503, "dashboard-only server: no engine")
                body = self._body()
                if u.path == "/api/decide":
                    return self._json(self._decide(body).to_dict())
                if u.path == "/api/teach":
                    q, text, label = self._fields(body, "label")
                    engine.teach(q, text, label, body.get("context"))
                    return self._json({"ok": True})
                items = body.get("items")
                if not isinstance(items, list) or not 0 < len(items) <= MAX_BATCH:
                    raise _HTTPError(400, f"items must be a list of 1..{MAX_BATCH}")
                out = []
                for it in items:
                    try:
                        if not isinstance(it, dict):
                            raise _HTTPError(400, "item must be an object")
                        out.append(self._decide(it).to_dict())
                    except _HTTPError as e:
                        out.append({"error": e.msg})
                return self._json({"results": out})
            raise _HTTPError(404, "not found")

        def _fields(self, body: dict, *extra):
            q, text = body.get("question"), body.get("text")
            if not isinstance(q, str) or not isinstance(text, str):
                raise _HTTPError(400, "question and text must be strings")
            if q not in engine.questions:
                raise _HTTPError(404, f"unknown question {q!r}")
            vals = [body.get(k) for k in extra]
            if any(not isinstance(v, str) for v in vals):
                raise _HTTPError(400, f"{', '.join(extra)} must be strings")
            return (q, text, *vals)

        def _decide(self, body: dict):
            q, text = self._fields(body)
            try:
                return engine.decide(q, text, body.get("context"))
            except ValueError as e:
                raise _HTTPError(400, str(e))
            except OracleError:
                raise _HTTPError(502, "oracle unavailable")

        def _handle(self, method: str):
            try:
                self._dispatch(method)
            except _HTTPError as e:
                self._json({"error": e.msg}, e.code, e.headers)
            except ValueError as e:
                self._json({"error": str(e)}, 400)
            except Exception:  # never leak internals
                self._json({"error": "internal error"}, 500)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def serve(store: Store, host: str = "127.0.0.1", port: int = 8765, engine=None, token: str | None = None,
          rate_limit_per_minute: int = 1200, background: bool = False,
          allow_insecure: bool = False) -> ThreadingHTTPServer:
    if not token and not _is_loopback(host) and not allow_insecure:
        raise SystemExit(f"refusing to listen on {host} without an API token (set KADI_TOKEN)")
    httpd = ThreadingHTTPServer((host, port), make_handler(store, engine, token, rate_limit_per_minute))
    httpd.daemon_threads = True
    if background:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    else:
        httpd.serve_forever()
    return httpd
