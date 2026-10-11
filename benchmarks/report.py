"""Aggregate benchmark result files into one report with risk-coverage plots.

    python benchmarks/report.py benchmarks/results/p1      # writes REPORT.md + risk_coverage_<dataset>.svg

Everything is computed from the JSON result files; nothing is typed by hand.
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run import boot_ci, cp_upper  # noqa: E402

KADI = ("conformal", "ltt", "mondrian")
# Validated categorical palette (light surface), fixed order; never cycled.
COLORS = {"conformal": "#2a78d6", "ltt": "#eb6834", "tuned": "#1baf7a", "deferral": "#eda100",
          "threshold": "#4a3aa7"}
NAMES = {"conformal": "Kadı conformal", "ltt": "Kadı LTT (time-uniform)", "tuned": "tuned threshold (no guarantee)",
         "deferral": "learned deferral (no guarantee)", "threshold": "fixed threshold τ (no guarantee)"}


def load(folder):
    out = []
    for path in sorted(glob.glob(os.path.join(folder, "results-*.json"))):
        with open(path) as f:
            r = json.load(f)
        tag = os.path.basename(path)[len("results-"):-len(".json")]
        for run in r["runs"]:
            out.append({**run, "tag": tag, "reflex": r["meta"]["reflex"], "oracle": r["meta"]["oracle"],
                        "oracle_meta": r["meta"].get("oracle_meta", {}).get(run["dataset"], {})})
    return out


def mean(cell, key):
    return statistics.mean(s[key] for s in cell["seeds"])


def family(policy):
    base = policy.split("-")[0].split("@")[0]
    return base


def is_kadi(cell):
    return family(cell["policy"]) in KADI and "-" not in cell["policy"]


def row(cell):
    S = cell["seeds"]
    lo, hi = boot_ci([s["local"] for s in S])
    a = cell["alpha"]
    v = None if a is None else sum(s["error"] > a for s in S)
    return (f"| {cell['policy']} | {cell['reflex']} | {'—' if a is None else f'{a:.0%}'} | "
            f"{mean(cell, 'local'):.1%} ({lo:.1%}–{hi:.1%}) | {mean(cell, 'error'):.2%} | {mean(cell, 'err_gold'):.2%} | "
            f"{mean(cell, 'calls_per_decision'):.2f} | {'—' if v is None else f'{v}/{len(S)}'} |")


HEADER = ["| method | reflex | α | local (95% CI) | err (oracle) | err (gold) | calls/dec | violations |",
          "|---|---|---|---|---|---|---|---|"]


def svg_risk_coverage(cells, ds, path):
    """Local share (y) against realised disagreement with the oracle (x)."""
    W, H, L, R, T, B = 640, 400, 56, 180, 24, 44
    pts = {}
    for c in cells:
        if c["dataset"] != ds or c["oracle"] != "labels" or "-" in c["policy"]:
            continue
        fam = family(c["policy"])
        if fam not in COLORS:
            continue
        key = (fam, c["reflex"])
        pts.setdefault(key, []).append((mean(c, "error"), mean(c, "local"), c["alpha"]))
    if not pts:
        return False
    xmax = max(0.06, max(x for v in pts.values() for x, _, _ in v) * 1.1)
    X = lambda x: L + (W - L - R) * x / xmax  # noqa: E731
    Y = lambda y: T + (H - T - B) * (1 - y)   # noqa: E731
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="system-ui, sans-serif" '
         f'font-size="11">', f'<rect width="{W}" height="{H}" fill="#fcfcfb"/>']
    for i in range(6):   # recessive grid
        y = i / 5
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(y):.1f}" y2="{Y(y):.1f}" stroke="#e2e0da"/>')
        o.append(f'<text x="{L - 6}" y="{Y(y) + 4:.1f}" text-anchor="end" fill="#52514e">{y:.0%}</text>')
    for i in range(5):
        x = xmax * i / 4
        o.append(f'<text x="{X(x):.1f}" y="{H - B + 16}" text-anchor="middle" fill="#52514e">{x:.1%}</text>')
    for a in (0.02, 0.05, 0.10):
        if a <= xmax:
            o.append(f'<line x1="{X(a):.1f}" x2="{X(a):.1f}" y1="{T}" y2="{H - B}" stroke="#8a8880" '
                     f'stroke-dasharray="3 4"/><text x="{X(a) + 3:.1f}" y="{T + 10}" fill="#8a8880">α={a:.0%}</text>')
    o.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 8}" text-anchor="middle" fill="#0b0b0b">'
             f'realised disagreement with the oracle</text>')
    o.append(f'<text x="14" y="{(T + H - B) / 2:.0f}" transform="rotate(-90 14 {(T + H - B) / 2:.0f})" '
             f'text-anchor="middle" fill="#0b0b0b">share answered locally</text>')
    ly = T + 6
    for (fam, reflex), v in sorted(pts.items(), key=lambda kv: list(COLORS).index(kv[0][0])):
        v.sort()
        col = COLORS[fam]
        dash = "" if reflex == "hashed" else ' stroke-dasharray="6 3"'
        if len(v) > 1 and fam != "threshold":
            o.append(f'<path d="' + " ".join(("M" if i == 0 else "L") + f"{X(x):.1f},{Y(y):.1f}"
                                             for i, (x, y, _) in enumerate(v)) +
                     f'" fill="none" stroke="{col}" stroke-width="2"{dash}/>')
        for x, y, a in v:
            o.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="4.5" fill="{col}" stroke="#fcfcfb" '
                     f'stroke-width="2"><title>{NAMES[fam]} · {reflex} · α={a} · local {y:.1%} · err {x:.2%}</title>'
                     f'</circle>')
        o.append(f'<line x1="{W - R + 12}" x2="{W - R + 30}" y1="{ly}" y2="{ly}" stroke="{col}" stroke-width="2"{dash}/>'
                 f'<text x="{W - R + 36}" y="{ly + 4}" fill="#0b0b0b">{NAMES[fam].split(" (")[0]}'
                 f'{"" if reflex == "hashed" else " · " + reflex}</text>')
        ly += 18
    o.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(o))
    return True


def main(folder):
    cells = load(folder)
    kadi = [c for c in cells if is_kadi(c) and c["oracle"] == "labels" and c["alpha"] is not None]

    def viol(cs):
        return (sum(sum(s["error"] > c["alpha"] for s in c["seeds"]) for c in cs), sum(len(c["seeds"]) for c in cs))

    def cells_over(cs):   # cells whose MEAN error exceeds alpha (what an in-expectation bound forbids)
        return sum(mean(c, "error") > c["alpha"] for c in cs), len(cs)
    lines = ["# Kadı — P1 evidence report", "",
             "Generated by `benchmarks/report.py` from the result files in this folder (`run_all.sh` reproduces "
             "them). The oracle is the gold label unless noted.", "",
             "## 1. Validity", "",
             "The two policies make different promises, so they are checked differently:", "",
             "- **LTT** promises, with probability ≥ 1 − δ (δ = 5%), that the risk is ≤ α at every point in time. "
             "Check: the share of individual runs whose realised disagreement exceeds α.",
             "- **Conformal** promises E[disagreement] ≤ α (in expectation; ACI steers it *towards* α). Check: whether the "
             "mean over seeds stays ≤ α. Individual runs above α are expected.",
             "- **Baselines** promise nothing; the same counts are shown for comparison.", "",
             "| method | runs above α | CP95 upper bound on per-run violation | cells (α × dataset × reflex) with mean above α |",
             "|---|---|---|---|"]
    groups = [("Kadı LTT", [c for c in kadi if family(c["policy"]) == "ltt"]),
              ("Kadı conformal", [c for c in kadi if family(c["policy"]) == "conformal"]),
              ("Kadı Mondrian", [c for c in kadi if family(c["policy"]) == "mondrian"])]
    base = [c for c in cells if family(c["policy"]) in ("tuned", "deferral") and c["oracle"] == "labels"]
    groups += [("tuned threshold (no guarantee)", [c for c in base if family(c["policy"]) == "tuned"]),
               ("learned deferral (no guarantee)", [c for c in base if family(c["policy"]) == "deferral"])]
    for name, cs in groups:
        if not cs:
            continue
        v, n = viol(cs)
        co, cn = cells_over(cs)
        lines.append(f"| {name} | {v}/{n} | {cp_upper(v, n):.1%} | {co}/{cn} |")
    lines.append("")
    lines += ["## 2. Results by dataset (gold-label oracle)", ""]
    for ds in dict.fromkeys(c["dataset"] for c in cells):
        sel = [c for c in cells if c["dataset"] == ds and c["oracle"] == "labels" and "-" not in c["policy"]]
        if not sel:
            continue
        lines += [f"### {ds}", ""]
        if svg_risk_coverage(cells, ds, os.path.join(folder, f"risk_coverage_{ds}.svg")):
            lines += [f"![risk–coverage {ds}](risk_coverage_{ds}.svg)", ""]
        lines += HEADER + [row(c) for c in sorted(sel, key=lambda c: (c["alpha"] or 0, c["policy"], c["reflex"]))]
        lines.append("")
    abl = [c for c in cells if "-" in c["policy"] and family(c["policy"]) in KADI]
    if abl:
        lines += ["## 3. Ablations (α = 5%, hashed reflex, 5 seeds; each row disables one mechanism)", ""]
        for ds in dict.fromkeys(c["dataset"] for c in abl):
            full = [c for c in cells if c["dataset"] == ds and is_kadi(c) and c["alpha"] == 0.05
                    and c["reflex"] == "hashed" and c["oracle"] == "labels"]
            lines += [f"**{ds}** (full system for reference: " + ", ".join(
                f"{c['policy']} {mean(c, 'local'):.1%} local / {mean(c, 'error'):.2%} err" for c in full) + ")", "",
                *HEADER]
            lines += [row(c) for c in sorted((c for c in abl if c["dataset"] == ds), key=lambda c: c["policy"])]
            lines.append("")
    noisy = [c for c in cells if c["oracle"] != "labels"]
    if noisy:
        lines += ["## 4. Noisy oracle (three-way metrics)", ""]
        for ds in dict.fromkeys(c["dataset"] for c in noisy):
            om = next(c["oracle_meta"] for c in noisy if c["dataset"] == ds)
            lines += [f"**{ds}** · oracle `{noisy[0]['oracle']}` · oracle vs gold agreement "
                      f"{om.get('oracle_vs_gold', float('nan')):.2%}", "", *HEADER]
            lines += [row(c) for c in noisy if c["dataset"] == ds]
            lines.append("")
    with open(os.path.join(folder, "REPORT.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {os.path.join(folder, 'REPORT.md')}: {len(kadi)} Kadı cells")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results", "p1"))
