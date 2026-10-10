"""kadi command line.

    kadi init                         write an example kadi.toml
    kadi serve --config kadi.toml     run the decision service + Divan dashboard
    kadi replay logs.jsonl ...        estimate savings & error on your history, before going live
    kadi dashboard --db kadi.db       read-only dashboard over an existing ledger
    kadi stats --db kadi.db           JSON summary
    kadi prune --db kadi.db --days 30 delete old ledger rows
    kadi verify --db kadi.db          check the tamper-evident hash chain
    kadi anchor --db kadi.db          print the chain head for external safekeeping
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time


def _cmd_init(a) -> int:
    from .config import EXAMPLE
    if os.path.exists(a.path) and not a.force:
        print(f"{a.path} exists (use --force to overwrite)", file=sys.stderr)
        return 1
    with open(a.path, "w") as f:
        f.write(EXAMPLE)
    print(f"wrote {a.path}. Secrets go in env vars: KADI_TOKEN, ANTHROPIC_API_KEY, KADI_WEBHOOK.")
    return 0


def _cmd_serve(a) -> int:
    from .config import build_engine, load
    from .server import serve
    cfg = load(a.config)
    host, port = a.host or cfg.server.host, a.port or cfg.server.port
    engine = build_engine(cfg)
    stop = threading.Event()

    def _maintenance():
        while not stop.wait(15):
            engine.checkpoint()
            if cfg.server.retention_days and int(time.time()) % 3600 < 15:
                engine.store.prune(cfg.server.retention_days)

    threading.Thread(target=_maintenance, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    qs = ", ".join(f"{q.name}[{q.mode}]" for q in cfg.questions)
    print(f"Kadı serving {qs}\n  API + Divan → http://{host}:{port}  (auth: {'token' if cfg.server.token else 'NONE'})")
    try:
        serve(engine.store, host, port, engine=engine, token=cfg.server.token,
              rate_limit_per_minute=cfg.server.rate_limit_per_minute, allow_insecure=a.insecure)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        engine.close()
        print("checkpointed, bye.")
    return 0


def _read_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if not isinstance(r.get("text"), str) or not isinstance(r.get("label"), str):
                raise ValueError(f"{path}:{n}: each line needs string 'text' and 'label'")
            rows.append(r)
    return rows


def replay(rows: list[dict], options: tuple[str, ...], alpha: float, cost_per_call: float,
           conditional: bool = False, redact: bool = True, name: str = "replay",
           policy: str = "conformal", audit_rate: float = 0.05) -> dict:
    """Run a fresh Kadı over labelled history, in order, with the labels as oracle."""
    from .engine import Kadi
    from .oracles import FunctionOracle
    from .questions import Question

    q = Question(name, options, target_error=alpha, conditional=conditional, policy=policy)
    current = {"label": None}
    calls = {"n": 0}

    def oracle(*_):
        calls["n"] += 1
        return current["label"]
    k = Kadi(FunctionOracle(oracle, cost_per_call), db=":memory:",
             audit_rate=audit_rate, redact=redact, secret=b"replay", store_inputs=False, seed=0)
    n = len(rows)
    local = wrong = local_wrong = 0
    half_local = half_wrong = 0
    for i, r in enumerate(rows):
        if r["label"] not in options:
            raise ValueError(f"label {r['label']!r} not in options")
        current["label"] = r["label"]
        d = k.decide(q, r["text"], r.get("context"))
        is_local = d.tier in ("memory", "reflex")
        bad = d.label != r["label"]
        local += is_local
        wrong += bad
        local_wrong += bad and is_local
        if i >= n // 2:
            half_local += is_local
            half_wrong += bad
    k.close()
    calls = calls["n"]  # includes audit calls
    h = n - n // 2
    return {"alpha": alpha, "n": n, "local_rate": local / n, "error_rate": wrong / n,
            "local_error_rate": (local_wrong / local) if local else 0.0,
            "steady_local_rate": half_local / h, "steady_error_rate": half_wrong / h,
            "oracle_calls": calls, "cost": calls * cost_per_call, "frontier_only_cost": n * cost_per_call,
            "savings": 1 - calls / n}


def _cmd_replay(a) -> int:
    rows = _read_jsonl(a.data)
    if not rows:
        print("no rows", file=sys.stderr)
        return 1
    conditional = a.conditional
    if a.options:
        options = tuple(o.strip() for o in a.options.split(","))
    elif a.config:
        from .config import load
        qs = {q.name: q for q in load(a.config).questions}
        if a.question not in qs:
            print(f"--question must be one of {sorted(qs)}", file=sys.stderr)
            return 1
        options = qs[a.question].options
        conditional = conditional or qs[a.question].conditional
    else:
        options = tuple(sorted({r["label"] for r in rows}))
    alphas = [float(x) for x in a.alphas.split(",")]
    results = [replay(rows, options, al, a.cost, conditional, policy=a.policy, audit_rate=a.audit_rate)
               for al in alphas]
    if a.json:
        print(json.dumps(results, indent=2))
        return 0
    kind = "LTT (holds w.p. ≥ 95%)" if a.policy == "ltt" else ("per-label" if conditional else "marginal")
    print(f"replayed {len(rows)} decisions · options: {', '.join(options)} · "
          f"{kind} guarantee · ${a.cost}/oracle call · audits {a.audit_rate:.0%}\n")
    hdr = f"{'target α':>9} {'local':>7} {'error':>7} {'local err':>9} {'steady local':>13} {'steady err':>11} {'cost':>10} {'vs frontier':>12}"
    print(hdr)
    print("─" * len(hdr))
    for r in results:
        print(f"{r['alpha']:>9.1%} {r['local_rate']:>7.1%} {r['error_rate']:>7.2%} {r['local_error_rate']:>9.2%} "
              f"{r['steady_local_rate']:>13.1%} {r['steady_error_rate']:>11.2%} ${r['cost']:>9.2f} "
              f"{'-' + format(r['savings'], '.0%'):>12}")
    print("\n'error' is disagreement with your labels over the whole stream, including warm-up.\n"
          "'steady' columns cover the second half, after Kadı has learned.")
    return 0


def _cmd_dashboard(a) -> int:
    from .server import serve
    from .store import Store
    print(f"Divan (read-only) → http://{a.host}:{a.port}")
    serve(Store(a.db), a.host, a.port, token=os.environ.get("KADI_TOKEN"))
    return 0


def _cmd_stats(a) -> int:
    from .server import summary
    from .store import Store
    print(json.dumps(summary(Store(a.db), a.window), indent=2, default=float))
    return 0


def _ledger_key(store) -> bytes:
    from .store import derive_chain_key
    env = os.environ.get("KADI_SECRET")
    if not env:
        print("note: KADI_SECRET not set; using the key stored in the database. Anyone who can write the\n"
              "      database can also re-forge the chain. Set KADI_SECRET for real tamper evidence.",
              file=sys.stderr)
    return derive_chain_key(env.encode() if env else store.secret())


def _cmd_verify(a) -> int:
    from .store import Store
    st = Store(a.db)
    try:
        res = st.verify(_ledger_key(st))
    finally:
        st.close()
    if res["ok"]:
        print(f"ledger OK: {res['rows']} chained decisions, head {res['head'][:16]}…")
        return 0
    print(f"LEDGER TAMPERED at decision #{res['first_bad_id']} (after {res['rows']} valid rows): {res['reason']}")
    return 3


def _cmd_anchor(a) -> int:
    """Print the chain head so it can be stored somewhere the DB owner cannot rewrite
    (a git commit, a ticket, a transparency log). A later `verify` + matching head
    proves no history was rewritten even by someone holding the key."""
    from .store import Store
    st = Store(a.db)
    try:
        res = st.verify(_ledger_key(st))
    finally:
        st.close()
    if not res["ok"]:
        print(f"refusing to anchor a broken chain: {res}", file=sys.stderr)
        return 3
    print(json.dumps({"db": os.path.abspath(a.db), "rows": res["rows"], "head": res["head"],
                      "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
    return 0


def _cmd_prune(a) -> int:
    from .store import Store
    print(f"deleted {Store(a.db).prune(a.days)} rows older than {a.days} days")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kadi", description="Kadı: a calibrated judge in front of your frontier model")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="write an example kadi.toml")
    s.add_argument("path", nargs="?", default="kadi.toml")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=_cmd_init)

    s = sub.add_parser("serve", help="run the decision service")
    s.add_argument("--config", default="kadi.toml")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--insecure", action="store_true", help="allow non-loopback host without a token")
    s.set_defaults(fn=_cmd_serve)

    s = sub.add_parser("replay", help="estimate savings and error on labelled history (JSONL: text, label)")
    s.add_argument("data")
    s.add_argument("--config")
    s.add_argument("--question")
    s.add_argument("--options", help="comma-separated; default: labels found in data")
    s.add_argument("--alphas", default="0.01,0.02,0.05,0.1")
    s.add_argument("--cost", type=float, default=0.01, help="USD per oracle call")
    s.add_argument("--conditional", action="store_true")
    s.add_argument("--policy", choices=("conformal", "ltt"), default="conformal")
    s.add_argument("--audit-rate", type=float, default=0.05)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=_cmd_replay)

    s = sub.add_parser("dashboard", help="read-only dashboard over a ledger")
    s.add_argument("--db", default="kadi.db")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=_cmd_dashboard)

    s = sub.add_parser("stats", help="print a JSON summary")
    s.add_argument("--db", default="kadi.db")
    s.add_argument("--window", type=float, help="seconds")
    s.set_defaults(fn=_cmd_stats)

    s = sub.add_parser("verify", help="verify the tamper-evident ledger chain")
    s.add_argument("--db", default="kadi.db")
    s.set_defaults(fn=_cmd_verify)

    s = sub.add_parser("anchor", help="print the ledger chain head for external safekeeping")
    s.add_argument("--db", default="kadi.db")
    s.set_defaults(fn=_cmd_anchor)

    s = sub.add_parser("prune", help="delete old ledger rows")
    s.add_argument("--db", default="kadi.db")
    s.add_argument("--days", type=float, required=True)
    s.set_defaults(fn=_cmd_prune)

    a = p.parse_args(argv)
    from .oracles import OracleError
    try:
        return a.fn(a)
    except (OracleError, ValueError, KeyError, FileNotFoundError) as e:  # config/user errors: no traceback
        print(f"kadi: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
