"""Reproducible benchmark: how much does Kadı keep local, and is the error bound honoured?

    python benchmarks/run.py                                   # gold labels as oracle (free)
    python benchmarks/run.py --oracle anthropic --n 2000       # real Claude oracle (needs ANTHROPIC_API_KEY)

Protocol
--------
Each run streams a dataset once, in a seeded random order, through a fresh
Kadı instance. With ``--oracle labels`` the oracle is the gold label, so
"disagreement with the oracle" equals error against ground truth. We report:

  local       share of decisions answered without an oracle call (memory + reflex)
  steady      the same over the second half of the stream (after warm-up)
  error       share of returned decisions that disagree with the oracle
  calls/dec   oracle calls per decision, including audits (cost proxy; 1.0 = oracle-only)

Baselines
---------
  oracle-only        every decision goes to the oracle (error 0, calls/dec 1.0)
  threshold@τ        same online reflex, answers whenever max p >= τ: the usual
                     "confidence router". No calibration, so no error control.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import datasets  # noqa: E402
from kadi import AnthropicOracle, Choice, FunctionOracle, Kadi  # noqa: E402
from kadi.features import HashingFeaturizer  # noqa: E402
from kadi.learner import OnlineSoftmax  # noqa: E402


def stream(rows, seed, n):
    rows = list(rows)
    random.Random(seed).shuffle(rows)
    return rows[:n] if n else rows


def summarize(flags_local, flags_err, calls, t0):
    n = len(flags_local)
    h = n // 2
    return {"n": n, "local": sum(flags_local) / n, "steady_local": sum(flags_local[h:]) / (n - h),
            "error": sum(flags_err) / n, "steady_error": sum(flags_err[h:]) / (n - h),
            "calls_per_decision": calls / n, "seconds": time.time() - t0}


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


def run_kadi(rows, labels, policy, alpha, seed, audit_rate, oracle_kind, model,
             ds="", reflex="hashed", emb_weight=1.0, knn=False):
    current = {"y": None}
    calls = {"n": 0}
    if oracle_kind == "labels":
        def fn(q, t, c):
            calls["n"] += 1
            return current["y"]
        oracle = FunctionOracle(fn)
    else:
        real = AnthropicOracle(model=model)

        class Counting:
            name = real.name

            def judge(self, q, t, c):
                calls["n"] += 1
                return real.judge(q, t, c)
        oracle = Counting()
    conditional = policy == "mondrian"
    q = Choice("intent", labels, "Which intent does this customer message express?", target_error=alpha,
               policy="ltt" if policy == "ltt" else "conformal", conditional=conditional)
    k = Kadi(oracle, db=":memory:", audit_rate=audit_rate, seed=seed, secret=b"bench", store_inputs=False,
             featurizer=make_featurizer(ds, reflex, emb_weight), reflex=make_reflex(reflex, knn))
    loc, err = [], []
    t0 = time.time()
    for text, y in rows:
        current["y"] = y
        d = k.decide(q, text)
        loc.append(d.tier in ("memory", "reflex"))
        err.append(d.label != y)
    st = k.stats()[0]
    k.close()
    out = summarize(loc, err, calls["n"], t0)
    out["calibrator"] = st["calibrator"]
    return out


def run_threshold(rows, labels, tau, warmup=100):
    feat, m = HashingFeaturizer(), OnlineSoftmax(len(labels))
    idx = {lab: i for i, lab in enumerate(labels)}
    loc, err, calls = [], [], 0
    t0 = time.time()
    for text, y in rows:
        x = feat(text)
        p = m.predict_proba(x)
        top = max(range(len(p)), key=p.__getitem__)
        if m.seen >= warmup and p[top] >= tau:
            loc.append(True)
            err.append(labels[top] != y)
        else:
            calls += 1
            m.update(x, idx[y])
            loc.append(False)
            err.append(False)
    return summarize(loc, err, calls, t0)


def agg(runs, key):
    vals = [r[key] for r in runs]
    return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datasets", default="banking77,clinc150")
    ap.add_argument("--policies", default="conformal,ltt,mondrian")
    ap.add_argument("--alphas", default="0.02,0.05,0.1")
    ap.add_argument("--taus", default="0.5,0.9", help="baseline confidence thresholds")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--n", type=int, default=0, help="limit stream length (0 = whole dataset)")
    ap.add_argument("--audit-rate", type=float, default=0.05)
    ap.add_argument("--oracle", choices=("labels", "anthropic"), default="labels")
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--reflex", default="hashed", help="hashed | bge | minilm (embeddings need the [embed] extra)")
    ap.add_argument("--emb-weight", type=float, default=1.0)
    ap.add_argument("--knn", action="store_true", help="mix a k-NN vote over embeddings into the reflex")
    ap.add_argument("--knn-k", type=int, default=10)
    ap.add_argument("--knn-temp", type=float, default=0.02)
    ap.add_argument("--knn-mix", type=float, default=0.8)
    ap.add_argument("--tag", default="", help="suffix for result files")
    a = ap.parse_args()
    if a.oracle == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("--oracle anthropic needs ANTHROPIC_API_KEY")

    os.makedirs(a.out, exist_ok=True)
    knn_cfg = {"k": a.knn_k, "temperature": a.knn_temp, "mix": a.knn_mix} if a.knn else None
    seeds = [int(x) for x in a.seeds.split(",")]
    results = {"meta": {"oracle": a.oracle, "model": a.model if a.oracle == "anthropic" else None,
                        "reflex": a.reflex + ("+knn" if a.knn else ""), "emb_weight": a.emb_weight, "knn": knn_cfg,
                        "audit_rate": a.audit_rate, "seeds": seeds, "n": a.n,
                        "dataset_sha256": datasets.digests(), "python": sys.version.split()[0]},
               "runs": []}
    for ds in a.datasets.split(","):
        data = datasets.load(ds)
        labels = sorted({y for _, y in data})
        if a.reflex != "hashed":
            import embeddings
            embeddings.ensure(ds, a.reflex)  # compute once, before the workers start
        cells = []  # (policy, alpha, [futures])
        with ProcessPoolExecutor(max_workers=a.jobs) as pool:
            if a.oracle == "labels" and a.taus:
                for tau in (float(t) for t in a.taus.split(",")):
                    cells.append((f"threshold@{tau}", None,
                                  [pool.submit(run_threshold, stream(data, sd, a.n), labels, tau) for sd in seeds]))
            for policy in a.policies.split(","):
                for alpha in (float(x) for x in a.alphas.split(",")):
                    cells.append((policy, alpha, [pool.submit(run_kadi, stream(data, sd, a.n), labels, policy, alpha,
                                                              sd, a.audit_rate, a.oracle, a.model, ds, a.reflex,
                                                              a.emb_weight, knn_cfg) for sd in seeds]))
            for policy, alpha, futs in cells:
                runs = [f.result() for f in futs]
                results["runs"].append({"dataset": ds, "policy": policy, "alpha": alpha, "seeds": runs})
                lm, ls = agg(runs, "local")
                em, es = agg(runs, "error")
                print(f"{ds:10} {policy:14} α={alpha if alpha is not None else '—':<5} local {lm:.1%}±{ls:.1%}  "
                      f"steady {agg(runs, 'steady_local')[0]:.1%}  error {em:.2%}±{es:.2%}  "
                      f"calls/dec {agg(runs, 'calls_per_decision')[0]:.2f}  ({runs[0]['seconds']:.0f}s/run)",
                      flush=True)
        with open(os.path.join(a.out, f"results-{a.oracle}{a.tag}.json"), "w") as f:
            json.dump(results, f, indent=1)
    write_markdown(results, os.path.join(a.out, f"RESULTS-{a.oracle}{a.tag}.md"))


def write_markdown(results, path):
    m = results["meta"]
    lines = [f"# Kadı benchmark — oracle: `{m['oracle']}`" + (f" ({m['model']})" if m["model"] else ""), "",
             f"Seeds {m['seeds']} · audit rate {m['audit_rate']} · stream length "
             f"{'full dataset' if not m['n'] else m['n']} · Python {m['python']}", "",
             "Mean ± sd over seeds. *error* = share of returned decisions that disagree with the oracle "
             "(here: gold labels). *calls/dec* includes audits; oracle-only = 1.00.", ""]
    for ds in dict.fromkeys(r["dataset"] for r in results["runs"]):
        lines += [f"## {ds}", "", "| policy | target α | local | steady local | error | steady error | "
                  "calls/dec | bound met |", "|---|---|---|---|---|---|---|---|",
                  "| oracle-only | — | 0.0% | 0.0% | 0.00% | 0.00% | 1.00 | — |"]
        for r in results["runs"]:
            if r["dataset"] != ds:
                continue
            f = lambda k, pct=True, d=1: "{:.{d}%} ± {:.{d}%}".format(*agg(r["seeds"], k), d=d)  # noqa: E731
            alpha = r["alpha"]
            met = "—" if alpha is None else ("✅" if agg(r["seeds"], "error")[0] <= alpha else "❌")
            lines.append(f"| {r['policy']} | {'—' if alpha is None else f'{alpha:.0%}'} | {f('local')} | "
                         f"{f('steady_local')} | {f('error', d=2)} | {f('steady_error', d=2)} | "
                         f"{agg(r['seeds'], 'calls_per_decision')[0]:.2f} | {met} |")
        lines.append("")
    lines += ["Dataset files (SHA-256):", ""] + [f"- `{k}` `{v}`" for k, v in m["dataset_sha256"].items()]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
