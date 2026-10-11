# Running the benchmark against a real LLM oracle

So far every published Kadı result uses **gold labels as the oracle**. That makes "disagreement with the oracle" equal to error against ground truth, but it says nothing about a real model's noise, cost or latency. This runbook closes that gap, and you need your own API key to follow it.

## Design: pay once, replay everything

`benchmarks/run.py --oracle anthropic` makes **one pass** in which the model labels every item. Verdicts go to a persistent JSONL cache (`~/.cache/kadi-bench/verdicts-<dataset>.jsonl`), keyed by `sha256(model | question | options | text | sample)`. Every configuration, seed, baseline and ablation then replays those cached verdicts, so a 10-seed × 3-α × 4-method matrix costs the same as one pass. Interrupting and rerunning never pays twice.

The run reports three disagreement rates separately:

| Metric | Meaning |
|---|---|
| `err (oracle)` | Kadı vs. the oracle's verdict. This is the quantity α bounds. |
| `oracle_vs_gold` | How often the oracle agrees with the dataset label. |
| `err (gold)` | Kadı vs. the dataset label. |

It also reports the oracle's **self-consistency**: `--consistency-k` independent verdicts on `--consistency-n` random items, at the API's default temperature. That estimates the noise floor ε. Choose α comfortably above ε; THEORY §8 explains why.

## Steps

```bash
# 1. Estimate calls and tokens first. Nothing is sent to the API.
.venv/bin/python benchmarks/run.py --estimate-only --datasets banking77,clinc150,massive_tr --n 2000 \
    --usd-per-mtok-in <your input price> --usd-per-mtok-out <your output price>

# 2. Run. The key is read from the environment and never written to disk.
export ANTHROPIC_API_KEY=...
.venv/bin/python benchmarks/run.py --oracle anthropic --model claude-opus-5-5 \
    --datasets banking77,clinc150,massive_tr --n 2000 --policies conformal,ltt --alphas 0.02,0.05,0.1 \
    --taus 0.9 --baselines tuned,deferral --seeds 0,1,2,3,4 --tag=-real

# 3. Aggregate.
.venv/bin/python benchmarks/report.py benchmarks/results
```

For scale: with `--n 2000` on three datasets and self-consistency on 200 items × 5 samples, the estimator gives about 8,400 calls, about 4.8M input tokens and about 0.25M output tokens. Prompt caching of the fixed instructions-and-options prefix (roadmap P2) would cut the input cost substantially. It is not enabled in `AnthropicOracle` yet.

## Reporting rules

- Publish `oracle_vs_gold` and the self-agreement next to every Kadı number. A Kadı error rate is only meaningful relative to the oracle's own noise.
- Keep the verdict cache. Its SHA-256 should be listed in the results so that others can replay the exact run without paying.
- Do not tune Kadı's settings on the evaluation seeds: tune on seeds ≥ 100, as CONTRIBUTING requires.
