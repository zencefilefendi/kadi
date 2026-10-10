# Contributing to Kadı

Thank you for helping. Kadı makes a *statistical promise*, so contributions are held to two standards: the code must be correct, and every claim must be measurable.

## Ground rules

1. **Zero runtime dependencies.** The core stays standard-library Python (≥ 3.11). Optional integrations, such as embedding reflexes, belong behind extras and must never be imported by the core.
2. **Never weaken the guarantee silently.** A change to `conformal.py`, the sampling rule in `engine.py`, or anything that decides *when Kadı answers locally* must:
   - explain the effect on the bound in the PR, with reference to [docs/THEORY.md](docs/THEORY.md);
   - keep `tests/test_production.py::TestGuarantee` green, and add a test if it introduces a new regime.
   Rules that only *remove* local answers are always safe; rules that *add* them need an argument.
3. **Security fixes come with a regression test.** Look at `TestSecurityRegressions` for the pattern.
4. **No unverified numbers in docs.** Every figure in README or THEORY must be reproducible from `examples/` or `tests/`.

## Development

```bash
git clone https://github.com/zencefilefendi/kadi && cd kadi
python -m unittest discover -s tests -v
python examples/demo.py                  # live dashboard at http://127.0.0.1:8765
npx -p typescript@5.6.3 tsc --noEmit -p clients/typescript

# optional semantic reflex + benchmarks (Python 3.12 venv; models ~300 MB, cached in ~/.cache/kadi-models)
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -e ".[embed]"
.venv/bin/python -m unittest discover -s tests
.venv/bin/python benchmarks/run.py --reflex bge --knn --tag=-bge-knn
```

Benchmark numbers in the docs must come from `benchmarks/results/` files committed in the same PR. Tune hyper-parameters only on orderings that are not used for evaluation (seeds ≥ 100); the evaluation seeds are 0, 1 and 2.

## Pull requests

- Keep each PR to one concern, and describe *what* changed, *why*, and *how you verified it*.
- Match the surrounding style: small functions, comments that explain *why*, type hints.
- Update `CHANGELOG.md` under "Unreleased".

## Reporting bugs

Open an issue with a minimal reproduction. Include the question definition, α, the mode, and the relevant `kadi stats` output. Report security issues privately; see [SECURITY.md](SECURITY.md).
