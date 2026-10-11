"""Reproducible benchmark: how much does Kadı keep local, and is the error bound honoured?

    python benchmarks/run.py                                    # gold labels as oracle (free)
    python benchmarks/run.py --oracle noisy:0.03                # simulated oracle that is wrong 3% of the time
    python benchmarks/run.py --oracle anthropic --n 2000        # real Claude oracle (needs ANTHROPIC_API_KEY)

Protocol
--------
Each run streams a dataset once, in a seeded random order, through a fresh
Kadı instance. The oracle labels every item ONCE, before any run (a cached,
paid pass for a real LLM); every configuration and seed then replays those
verdicts, so the comparison is exact and the API is paid for once.

Metrics (per run, then mean and 95% bootstrap CI over seeds):

  local         share of decisions answered without an oracle call (memory + reflex)
  steady        local share over the second half of the stream
  err_oracle    share of returned decisions that disagree with the ORACLE (what α bounds)
  err_gold      share of returned decisions that disagree with the gold label
  calls/dec     oracle calls per decision, including audits (1.0 = oracle-only)
  bound met     runs with err_oracle <= α, plus a Clopper-Pearson 95% upper bound
                on the violation probability

Comparators
-----------
  threshold@τ   online reflex, answers whenever max p >= τ (no calibration, no guarantee)
  tuned@α       FAIR baseline: first `--budget` decisions go to the oracle; τ is then the
                loosest threshold whose empirical risk on that prefix is <= α (no guarantee)
  deferral@α    FrugalGPT-style learned deferral: a logistic scorer on (max p, margin,
                entropy, novelty) fitted on the same prefix, thresholded the same way
  <policy>-<ablation>   Kadı with one safety mechanism disabled (see kadi.engine.ABLATIONS)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import datasets  # noqa: E402
from kadi import AnthropicOracle, Choice, FunctionOracle, Kadi  # noqa: E402
from kadi.features import HashingFeaturizer  # noqa: E402
from kadi.learner import OnlineSoftmax  # noqa: E402

INSTRUCTIONS = {
    "banking77": "Which banking intent does this customer message express?",
    "clinc150": "Which intent does this assistant request express?",
    "massive_tr": "Bu Türkçe komut hangi niyeti ifade ediyor? (Which intent does this Turkish command express?)",
    "offenseval_tr": "Is this Turkish tweet offensive? OFF = offensive, NOT = not offensive.",
    "hatespeech_en": "Is this comment hate speech? hateful / not_hateful.",
}


# ------------------------------------------------------------------- oracles
class CachedOracle:
    """Wraps an API oracle with a persistent JSONL verdict cache and cost
    accounting. Key = sha256(model | question | options | text | sample)."""

    def __init__(self, inner, path: str):
        self.inner, self.path, self.name = inner, path, inner.name
        self.lock = threading.Lock()
        self.cache: dict[str, dict] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    self.cache[r["key"]] = r
        self.paid_cost = 0.0
        self.paid_calls = 0

    def key(self, q, text, sample=0):
        h = hashlib.sha256(f"{self.name}|{q.name}|{'|'.join(q.options)}|{text}|{sample}".encode())
        return h.hexdigest()

    def judge_cached(self, q, text, sample=0):
        k = self.key(q, text, sample)
        with self.lock:
            if k in self.cache:
                return self.cache[k]
        v = self.inner.judge(q, text, None)
        rec = {"key": k, "label": v.label, "cost": v.cost_usd, "latency_ms": v.latency_ms, "model": v.model}
        with self.lock:
            self.cache[k] = rec
            self.paid_cost += v.cost_usd
            self.paid_calls += 1
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        return rec


def oracle_labels(kind: str, ds: str, data, labels, model: str, consistency_k: int, consistency_n: int,
                  threads: int = 8):
    """-> ({text: oracle_label}, meta). One pass over the data, cached."""
    meta = {"kind": kind}
    if kind == "labels":
        return {t: y for t, y in data}, meta
    if kind.startswith("noisy:"):
        p = float(kind.split(":", 1)[1])
        out = {}
        for t, y in data:   # deterministic per text, like a cached LLM verdict
            u = int(hashlib.sha256(f"noise|{t}".encode()).hexdigest()[:12], 16) / 16 ** 12
            if u < p:
                others = [lab for lab in labels if lab != y]
                y = others[int(u / p * len(others)) % len(others)]
            out[t] = y
        meta["flip_rate"] = p
        return out, meta
    if kind != "anthropic":
        raise SystemExit(f"unknown oracle {kind!r}")
    q = Choice("intent", labels, INSTRUCTIONS.get(ds, "Choose the correct label."))
    cache = CachedOracle(AnthropicOracle(model=model), os.path.join(datasets.cache_dir(), f"verdicts-{ds}.jsonl"))
    texts = list(dict.fromkeys(t for t, _ in data))
    with ThreadPoolExecutor(threads) as ex:
        recs = list(ex.map(lambda t: cache.judge_cached(q, t), texts))
    out = {t: r["label"] for t, r in zip(texts, recs)}
    costs = [r["cost"] for r in recs]
    meta.update({"model": model, "paid_calls_this_run": cache.paid_calls, "paid_cost_this_run": cache.paid_cost,
                 "mean_cost_per_call": statistics.mean(costs) if costs else 0.0,
                 "p50_latency_ms": statistics.median(r["latency_ms"] for r in recs) if recs else None})
    if consistency_k > 1:   # oracle self-consistency: k independent verdicts on a random subset
        sub = random.Random(7).sample(texts, min(consistency_n, len(texts)))
        agree = []
        for t in sub:
            vs = [cache.judge_cached(q, t, sample=s)["label"] for s in range(consistency_k)]
            agree.append(sum(v == vs[0] for v in vs[1:]) / (consistency_k - 1))
        meta["self_agreement"] = statistics.mean(agree)
        meta["consistency_k"], meta["consistency_n"] = consistency_k, len(sub)
    return out, meta


# ------------------------------------------------------------------- helpers
def stream(rows, seed, n):
    rows = list(rows)
    random.Random(seed).shuffle(rows)
    return rows[:n] if n else rows


def summarize(flags_local, err_o, err_g, calls, t0):
    n = len(flags_local)
    h = n // 2
    return {"n": n, "local": sum(flags_local) / n, "steady_local": sum(flags_local[h:]) / (n - h),
            "error": sum(err_o) / n, "steady_error": sum(err_o[h:]) / (n - h),
            "err_gold": sum(err_g) / n, "calls_per_decision": calls / n, "seconds": time.time() - t0}


def make_featurizer(ds, reflex, weight):
    if reflex == "hashed":
        return None
    import embeddings
    from kadi.embed import HybridFeaturizer
    return HybridFeaturizer(embeddings.Lookup(ds, reflex), weight=weight)


def make_reflex(reflex, knn):
    if reflex == "hashed" or not knn:
        return None
    from kadi.embed import KNNHybridReflex
    return KNNHybridReflex(**knn) if isinstance(knn, dict) else KNNHybridReflex()


# --------------------------------------------------------------------- Kadı
def run_kadi(rows, labels, policy, alpha, seed, audit_rate, ds="", reflex="hashed", emb_weight=1.0, knn=None,
             ablate=()):
    """rows: [(text, oracle_label, gold_label)]"""
    current = {"y": None}
    calls = {"n": 0}

    def fn(q, t, c):
        calls["n"] += 1
        return current["y"]
    q = Choice("intent", labels, INSTRUCTIONS.get(ds, ""), target_error=alpha,
               policy="ltt" if policy == "ltt" else "conformal", conditional=policy == "mondrian")
    k = Kadi(FunctionOracle(fn), db=":memory:", audit_rate=audit_rate, seed=seed, secret=b"bench",
             store_inputs=False, featurizer=make_featurizer(ds, reflex, emb_weight), reflex=make_reflex(reflex, knn),
             _ablate=frozenset(ablate))
    loc, eo, eg = [], [], []
    t0 = time.time()
    for text, yo, yg in rows:
        current["y"] = yo
        d = k.decide(q, text)
        loc.append(d.tier in ("memory", "reflex"))
        eo.append(d.label != yo)
        eg.append(d.label != yg)
    st = k.stats()[0]
    k.close()
    out = summarize(loc, eo, eg, calls["n"], t0)
    out["calibrator"] = st["calibrator"]
    out["versions"] = st["version"]
    return out


# ---------------------------------------------------------------- baselines
GRID = sorted({round(1 - 10 ** (-e / 8), 6) for e in range(1, 33)} | {round(i / 40, 3) for i in range(0, 40)})


def _features(p, novelty):
    s = sorted(p, reverse=True)
    ent = -sum(v * math.log(v) for v in p if v > 0) / math.log(len(p))
    return [1.0, s[0], s[0] - (s[1] if len(s) > 1 else 0.0), ent, novelty]


def _fit_logistic(X, y, steps=300, lr=0.5):
    w = [0.0] * len(X[0])
    for _ in range(steps):
        g = [0.0] * len(w)
        for xi, yi in zip(X, y):
            z = max(-30.0, min(30.0, sum(a * b for a, b in zip(w, xi))))
            e = 1 / (1 + math.exp(-z)) - yi
            for j, v in enumerate(xi):
                g[j] += e * v
        w = [a - lr * b / len(X) for a, b in zip(w, g)]
    return w


def _pick(scores, correct, alpha):
    """Loosest threshold whose empirical risk Pr(score >= t and wrong) on the prefix is <= alpha."""
    n = len(scores)
    best = None
    for t in sorted(set(GRID) | set(scores), reverse=True):
        risk = sum(1 for s, c in zip(scores, correct) if s >= t and not c) / n
        if risk <= alpha:
            best = t
        else:
            break
    return best if best is not None else math.inf


def run_baseline(rows, labels, kind, param, ds="", reflex="hashed", emb_weight=1.0, knn=None, budget=500):
    """kind: threshold (param = tau), tuned / deferral (param = alpha)."""
    feat = make_featurizer(ds, reflex, emb_weight) or HashingFeaturizer()
    m = (make_reflex(reflex, knn) or OnlineSoftmax)(len(labels))
    limit = getattr(feat, "hashed_dim", None)
    idx = {lab: i for i, lab in enumerate(labels)}
    loc, eo, eg, calls = [], [], [], 0
    pref_scores, pref_ok, pref_x = [], [], []
    tau, w = (param if kind == "threshold" else None), None
    t0 = time.time()
    for i, (text, yo, yg) in enumerate(rows):
        x = feat(text)
        p = m.predict_proba(x)
        top = max(range(len(p)), key=p.__getitem__)
        if kind == "threshold":
            go_local = m.seen >= 100 and p[top] >= tau
        elif i < budget:
            go_local = False
            fz = _features(p, m.novelty(x, limit))
            pref_x.append(fz)
            pref_scores.append(p[top])
            pref_ok.append(labels[top] == yo)
        else:
            if tau is None:   # end of prefix: fit once, as the baseline would in practice
                if kind == "tuned":
                    tau = _pick(pref_scores, pref_ok, param)
                else:
                    w = _fit_logistic(pref_x, [1.0 if c else 0.0 for c in pref_ok])
                    sc = [1 / (1 + math.exp(-max(-30, min(30, sum(a * b for a, b in zip(w, fz)))))) for fz in pref_x]
                    tau = _pick(sc, pref_ok, param)
            if kind == "tuned":
                score = p[top]
            else:
                fz = _features(p, m.novelty(x, limit))
                score = 1 / (1 + math.exp(-max(-30, min(30, sum(a * b for a, b in zip(w, fz))))))
            go_local = score >= tau
        if go_local:
            loc.append(True)
            eo.append(labels[top] != yo)
            eg.append(labels[top] != yg)
        else:
            calls += 1
            m.update(x, idx[yo])
            loc.append(False)
            eo.append(False)
            eg.append(yo != yg)
    return summarize(loc, eo, eg, calls, t0)


# -------------------------------------------------------------------- stats
def boot_ci(vals, b=4000, seed=0):
    """95% percentile bootstrap CI of the mean over seeds."""
    if len(vals) < 2:
        return (vals[0], vals[0]) if vals else (float("nan"),) * 2
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(rng.choice(vals) for _ in range(n)) / n for _ in range(b))
    return means[int(0.025 * b)], means[int(0.975 * b) - 1]


def cp_upper(k, n, conf=0.95):
    """Clopper-Pearson upper bound for a binomial proportion (bisection, stdlib)."""
    if k >= n:
        return 1.0
    a = 1 - conf
    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        cdf = sum(math.comb(n, i) * mid ** i * (1 - mid) ** (n - i) for i in range(k + 1))
        lo, hi = (mid, hi) if cdf > a else (lo, mid)
    return hi


def agg(runs, key):
    vals = [r[key] for r in runs]
    return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datasets", default="banking77,clinc150")
    ap.add_argument("--policies", default="conformal,ltt,mondrian")
    ap.add_argument("--alphas", default="0.02,0.05,0.1")
    ap.add_argument("--taus", default="0.5,0.9", help="naive confidence-threshold baselines")
    ap.add_argument("--baselines", default="", help="comma list of: tuned, deferral (evaluated at each α)")
    ap.add_argument("--budget", type=int, default=500, help="oracle-labelled prefix for tuned/deferral baselines")
    ap.add_argument("--ablate", default="", help="comma list of ablations; each is run in place of the full system")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--n", type=int, default=0, help="limit stream length (0 = whole dataset)")
    ap.add_argument("--audit-rate", type=float, default=0.05)
    ap.add_argument("--oracle", default="labels", help="labels | noisy:<p> | anthropic")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--consistency-k", type=int, default=5, help="real oracle: samples per item for self-consistency")
    ap.add_argument("--consistency-n", type=int, default=200)
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--reflex", default="hashed", help="hashed | bge | minilm (embeddings need the [embed] extra)")
    ap.add_argument("--emb-weight", type=float, default=1.0)
    ap.add_argument("--knn", action="store_true", help="mix a k-NN vote over embeddings into the reflex")
    ap.add_argument("--knn-k", type=int, default=10)
    ap.add_argument("--knn-temp", type=float, default=0.02)
    ap.add_argument("--knn-mix", type=float, default=0.8)
    ap.add_argument("--tag", default="", help="suffix for result files")
    ap.add_argument("--estimate-only", action="store_true",
                    help="print the oracle calls and approximate tokens a real-oracle run would need, then exit")
    ap.add_argument("--usd-per-mtok-in", type=float, default=0.0, help="your input price, for --estimate-only")
    ap.add_argument("--usd-per-mtok-out", type=float, default=0.0, help="your output price, for --estimate-only")
    a = ap.parse_args()
    if a.estimate_only:
        estimate(a)
        return
    if a.oracle == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("--oracle anthropic needs ANTHROPIC_API_KEY")

    os.makedirs(a.out, exist_ok=True)
    knn_cfg = {"k": a.knn_k, "temperature": a.knn_temp, "mix": a.knn_mix} if a.knn else None
    seeds = [int(x) for x in a.seeds.split(",")]
    alphas = [float(x) for x in a.alphas.split(",")]
    oname = a.oracle.replace(":", "")
    results = {"meta": {"oracle": a.oracle, "model": a.model if a.oracle == "anthropic" else None,
                        "reflex": a.reflex + ("+knn" if a.knn else ""), "emb_weight": a.emb_weight, "knn": knn_cfg,
                        "audit_rate": a.audit_rate, "budget": a.budget, "seeds": seeds, "n": a.n,
                        "dataset_sha256": datasets.digests(a.datasets.split(",")),
                        "python": sys.version.split()[0], "oracle_meta": {}},
               "runs": []}
    for ds in a.datasets.split(","):
        data = datasets.load(ds)
        labels = sorted({y for _, y in data})
        olab, ometa = oracle_labels(a.oracle, ds, data, labels, a.model, a.consistency_k, a.consistency_n)
        ometa["oracle_vs_gold"] = sum(olab[t] == y for t, y in data) / len(data)
        results["meta"]["oracle_meta"][ds] = ometa
        triples = [(t, olab[t], y) for t, y in data]
        if a.reflex != "hashed":
            import embeddings
            embeddings.ensure(ds, a.reflex)  # compute once, before the workers start
        common = dict(ds=ds, reflex=a.reflex, emb_weight=a.emb_weight, knn=knn_cfg)
        cells = []
        with ProcessPoolExecutor(max_workers=a.jobs) as pool:
            for tau in ([float(t) for t in a.taus.split(",")] if a.taus else []):
                cells.append((f"threshold@{tau}", None, [pool.submit(run_baseline, stream(triples, sd, a.n), labels,
                                                                      "threshold", tau, **common) for sd in seeds]))
            for base in [b for b in a.baselines.split(",") if b]:
                for alpha in alphas:
                    cells.append((base, alpha, [pool.submit(run_baseline, stream(triples, sd, a.n), labels, base,
                                                            alpha, budget=a.budget, **common) for sd in seeds]))
            variants = [((), "")] + [((ab,), "-" + ab) for ab in a.ablate.split(",") if ab]
            if a.ablate:
                variants = variants[1:]          # ablation runs replace the full system
            for policy in [p for p in a.policies.split(",") if p]:
                for ab, suffix in variants:
                    for alpha in alphas:
                        cells.append((policy + suffix, alpha, [pool.submit(
                            run_kadi, stream(triples, sd, a.n), labels, policy, alpha, sd, a.audit_rate,
                            ablate=ab, **common) for sd in seeds]))
            for policy, alpha, futs in cells:
                runs = [f.result() for f in futs]
                results["runs"].append({"dataset": ds, "policy": policy, "alpha": alpha, "seeds": runs})
                lm, _ = agg(runs, "local")
                em, _ = agg(runs, "error")
                viol = "" if alpha is None else f"  viol {sum(r['error'] > alpha for r in runs)}/{len(runs)}"
                print(f"{ds:13} {policy:28} α={alpha if alpha is not None else '—':<5} local {lm:.1%}  "
                      f"err_oracle {em:.2%}  err_gold {agg(runs, 'err_gold')[0]:.2%}  "
                      f"calls/dec {agg(runs, 'calls_per_decision')[0]:.2f}{viol}  ({runs[0]['seconds']:.0f}s/run)",
                      flush=True)
        with open(os.path.join(a.out, f"results-{oname}{a.tag}.json"), "w") as f:
            json.dump(results, f, indent=1)
    write_markdown(results, os.path.join(a.out, f"RESULTS-{oname}{a.tag}.md"))


def estimate(a):
    """Rough cost of the one-off oracle pass (chars/4 tokens; prompt as built by kadi.oracles)."""
    from kadi.oracles import SYSTEM, _prompt
    total_in = total_out = total_calls = 0
    for ds in a.datasets.split(","):
        data = datasets.load(ds)
        labels = sorted({y for _, y in data})
        q = Choice("intent", labels, INSTRUCTIONS.get(ds, ""))
        texts = list(dict.fromkeys(t for t, _ in (stream(data, 0, a.n) if a.n else data)))
        calls = len(texts) + (min(a.consistency_n, len(texts)) * (a.consistency_k - 1) if a.consistency_k > 1 else 0)
        tok_in = sum(len(SYSTEM) + len(_prompt(q, t, None)) for t in texts) / 4 * calls / max(1, len(texts))
        tok_in += 60 * calls          # tool schema overhead (approximate)
        tok_out = 30 * calls
        total_in, total_out, total_calls = total_in + tok_in, total_out + tok_out, total_calls + calls
        print(f"{ds:14} {len(texts):>6} items  {calls:>6} oracle calls  ~{tok_in / 1e6:.2f}M input tokens  "
              f"~{tok_out / 1e6:.3f}M output tokens")
    usd = total_in / 1e6 * a.usd_per_mtok_in + total_out / 1e6 * a.usd_per_mtok_out
    print(f"{'total':14} {'':>6}        {total_calls:>6} oracle calls  ~{total_in / 1e6:.2f}M in / "
          f"~{total_out / 1e6:.3f}M out" + (f"  ≈ ${usd:,.2f} at your prices" if usd else
                                             "  (pass --usd-per-mtok-in/out for a dollar figure)"))
    print("Every configuration and seed afterwards replays the cached verdicts for free.")


def write_markdown(results, path):
    m = results["meta"]
    lines = [f"# Kadı benchmark — oracle: `{m['oracle']}`" + (f" ({m['model']})" if m["model"] else ""), "",
             f"Reflex `{m['reflex']}` · seeds {m['seeds']} · audit rate {m['audit_rate']} · baseline prefix budget "
             f"{m.get('budget')} · stream length {'full dataset' if not m['n'] else m['n']} · Python {m['python']}", "",
             "Mean over seeds with a 95% bootstrap CI. *err (oracle)* is disagreement with the oracle, the quantity "
             "α bounds. *err (gold)* is against the dataset label. *Violations* counts runs with err (oracle) > α; "
             "*CP95* is the Clopper–Pearson 95% upper bound on the per-run violation probability. "
             "*Calls/dec* includes audits; oracle-only = 1.00.", ""]
    for ds in dict.fromkeys(r["dataset"] for r in results["runs"]):
        om = m.get("oracle_meta", {}).get(ds, {})
        lines += [f"## {ds}", ""]
        if om:
            extra = ", ".join(f"{k} = {v:.4g}" if isinstance(v, float) else f"{k} = {v}" for k, v in om.items())
            lines += [f"Oracle: {extra}", ""]
        lines += ["| method | α | local (95% CI) | steady local | err (oracle) | err (gold) | calls/dec | violations | CP95 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in results["runs"]:
            if r["dataset"] != ds:
                continue
            S = r["seeds"]
            lo, hi = boot_ci([s["local"] for s in S])
            alpha = r["alpha"]
            v = None if alpha is None else sum(s["error"] > alpha for s in S)
            lines.append(
                f"| {r['policy']} | {'—' if alpha is None else f'{alpha:.0%}'} | "
                f"{agg(S, 'local')[0]:.1%} ({lo:.1%}–{hi:.1%}) | {agg(S, 'steady_local')[0]:.1%} | "
                f"{agg(S, 'error')[0]:.2%} | {agg(S, 'err_gold')[0]:.2%} | {agg(S, 'calls_per_decision')[0]:.2f} | "
                f"{'—' if v is None else f'{v}/{len(S)}'} | {'—' if v is None else f'{cp_upper(v, len(S)):.0%}'} |")
        lines.append("")
    lines += ["Dataset files (SHA-256):", ""] + [f"- `{k}` `{v}`" for k, v in m["dataset_sha256"].items()]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
