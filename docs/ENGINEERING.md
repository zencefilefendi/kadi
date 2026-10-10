# Kadı: Engineering Report

This report covers what was built, which techniques were used and why, what was measured, what went wrong and how it was fixed, and what is still unverified. Every number here can be reproduced from files in this repository. The formal statements are in [THEORY.md](THEORY.md), and security is covered in [THREAT_MODEL.md](THREAT_MODEL.md).

---

## 1. The problem and the answer in one paragraph

LLM agents make many small, multiple-choice decisions. A frontier model gets them right but is slow and expensive; a small model is cheap but its error rate is unknown. Kadı is a cascade: exact memory, then a local reflex, then the oracle. The reflex answers **only when a statistical test certifies** that answering locally keeps the disagreement with the oracle at or below a user-chosen α. Everything else is escalated, and every escalation teaches the reflex. On two public intent benchmarks, Kadı removed **75–85% of oracle calls at α = 5%**, and the error bound held in **126 of 126** runs.

## 2. Version history

| Version | What it added |
|---|---|
| 0.1 | Prototype: memory, reflex and oracle cascade; adaptive conformal prediction; dashboard |
| 0.2 | Production layer: shadow mode, replay, Mondrian conformal, drift breaker, fallback, PII redaction, hardened HTTP API, TypeScript client, Docker, CI. Fixed the **calibration selection-bias bug** (§5.1) and the **11 findings of an adversarial security review** (§5.3) |
| 0.3 | Learn then Test (high-probability guarantee), tamper-evident ledger, public benchmark |
| 0.4 | Semantic reflex: sentence embeddings + k-NN (optional extra) |
| 0.4.1 | Documentation patch: status and limitations, re-measured demo |
| 0.5 | MCP server with **agent-as-oracle** (no API key) |

## 3. Techniques

### 3.1 Statistics: when Kadı may answer alone

| Technique | Where | Why | Reference |
|---|---|---|---|
| Split conformal prediction | `kadi/conformal.py` `AdaptiveConformal` | Turns any scorer into prediction sets with coverage ≥ 1 − α; answering only on singletons bounds the disagreement | Vovk et al. 2005; Papadopoulos et al. 2002; Lei et al. 2018 |
| Adaptive Conformal Inference | same, `alpha_t` update | Keeps long-run miscoverage near α when traffic drifts | Gibbs & Candès 2021 |
| Mondrian (per-label) conformal | `MondrianConformal` | A rare but critical label gets its own bound | Vovk 2012 |
| **Learn then Test** | `LearnThenTest` | A PAC-style guarantee: risk ≤ α *with probability ≥ 1 − δ*. Tests the decision risk directly, so it answers more locally | Angelopoulos, Bates, Candès, Jordan & Lei 2021 |
| Exact binomial p-values, fixed-sequence testing | `binom_cdf`, `LTT_GRID` | A valid test with no normal approximation. The grid is fixed in advance, as LTT requires | — |
| **Held-out random calibration** | `engine.py` `_route` sampling | Calibration data must be a random sample that is never trained on (§5.1) | — |
| Fresh, time-budgeted re-scoring | `_Brain.refresh` | Re-scores stored calibration inputs with the current model, using at most ~10% of wall time | — |
| Consistency rule | `_route` (`inconsistent`) | A singleton set must equal the argmax; otherwise Kadı escalates. Escalating never adds error | — |

### 3.2 The reflex (local model)

| Technique | Where | Why |
|---|---|---|
| Feature hashing of word uni/bi-grams and char 3–5-grams | `features.py` | Zero-dependency, deterministic (crc32), bounded (≤ 2,048 features) |
| Online multinomial logistic regression with AdaGrad | `learner.py` | Learns from every oracle verdict (online distillation) |
| Novelty (OOD) guard | `learner.novelty` | Escalates inputs whose features are mostly unseen; also blocks gibberish attacks |
| Sentence embeddings (fastembed/ONNX) | `embed.py` (optional) | Captures meaning ("card hasn't come" ≈ "where is my card") |
| k-NN vote mixed with the logistic model | `KNNHybridReflex` | Strong with few examples per label. Settings were tuned only on separate orderings (seeds 100–102) |

### 3.3 Operations and safety

| Technique | Where | Why |
|---|---|---|
| Random audits | `engine.py` | Measure real agreement on live traffic; the dashboard shows it measured, not assumed |
| Drift breaker | `_check_drift` | 95% lower bound on audited disagreement > α → probation (everything escalated) plus a webhook alert |
| Shadow mode, replay | `questions.py`, `cli.py replay` | Prove the value risk-free before going live |
| Fallback | `on_oracle_error="best_guess"` | When the oracle is down, return flagged local answers |
| Tamper-evident ledger | `store.py` | HMAC hash chain over every decision; `kadi verify` and `kadi anchor` |
| PII redaction with checksums | `redact.py` | TCKN (checksum), IBAN (mod-97), cards (Luhn + IIN), phones, e-mail, keys, JWTs |
| Hardened HTTP | `server.py` | Constant-time bearer auth, CSRF and DNS-rebinding guards, token-bucket rate limiting, body caps, CSP |
| Prompt-injection delimiting | `oracles.py` | User text is marked as untrusted data; output is schema-locked to the options |
| **Agent-as-oracle** two-phase API | `decide_or_defer` / `resolve`, `mcp.py` | Over MCP the calling model *is* the oracle. Blind audits keep agreement honest |
| Supply chain | `benchmarks/datasets.py`, `pyproject.toml` | Zero core dependencies; benchmark data pinned by SHA-256 |

## 4. Results

### 4.1 Public benchmarks

**Setup.** Banking77 has 13,083 queries over 77 intents; CLINC150 has 22,500 queries over 150 intents. Each dataset is streamed once, in a seeded random order. The gold label acts as the oracle, so *error* = disagreement with the oracle = error against ground truth. Results are the mean of seeds 0–2, with audit rate 5%. *Calls/dec* is the number of oracle calls per decision, including audits; oracle-only = 1.00.

**α = 5%:**

| Reflex | Policy | Banking77 local / error / calls | CLINC150 local / error / calls |
|---|---|---|---|
| — | naive threshold τ = 0.5 (no guarantee) | 85.9% / **18.80%** / 0.14 | 87.2% / **10.41%** / 0.13 |
| — | hand-tuned threshold τ = 0.9 (no guarantee) | 65.4% / 2.89% / 0.35 | 73.5% / 1.47% / 0.27 |
| hashed n-grams | conformal | 54.7% / 1.28% / 0.48 | 74.7% / 2.16% / 0.29 |
| hashed n-grams | LTT | 63.9% / 2.47% / 0.39 | 79.5% / 3.19% / 0.25 |
| MiniLM + k-NN | LTT | 70.7% / 1.82% / 0.33 | 81.9% / 2.58% / 0.22 |
| **bge-small + k-NN** | **LTT** | **79.6% / 2.14% / 0.25** | **89.8% / 3.18% / 0.15** |

**LTT across α, with the bge-small + k-NN reflex:**

| α | Banking77 local / error | CLINC150 local / error |
|---|---|---|
| 2% | 61.2% / 0.54% | 80.3% / 0.72% |
| 5% | 79.6% / 2.14% | 89.8% / 3.18% |
| 10% | 89.3% / 6.14% | 94.1% / 6.19% |

**Headline numbers:**

| Measure | Value |
|---|---|
| Runs in which the bound held | **126 / 126**, checked per seed (54 hashed, 36 MiniLM, 36 bge) |
| Oracle calls removed at α = 5% (best configuration) | **75%** (Banking77), **85%** (CLINC150) |
| Effect of the semantic reflex on oracle calls at α = 5% | −36% (Banking77), −40% (CLINC150) |
| LTT vs. conformal | LTT kept at least as many decisions local in 16 of 18 configurations; the 2 exceptions are within one standard deviation |
| Naive confidence router | 10–19% error with no warning |

Full tables: [benchmarks/results/](../benchmarks/results/).

### 4.2 Simulated support desk (`examples/demo.py`)

6,000 tickets through a 2%-noisy simulated oracle, with an oracle outage at 30–33% of the stream and a vocabulary drift at 50%:

| | Local | Audited agreement | Realised miscoverage | Spend vs. oracle-only |
|---|---|---|---|---|
| `route_ticket` (marginal, α = 5%) | 94.3% | 99.1% | 3.0% | $6.83 vs. $72 |
| `is_urgent` (per-label, α = 5%) | 62.6% | 97.8% | 3.7% | $28.09 vs. $72 |

### 4.3 Agent-as-oracle (MCP)

In `tests/test_mcp.py`, 1,200 simulated cases were sent through the MCP tools with the "agent" resolving every ticket. In the second half, **more than 60%** of decisions were made by Kadı alone, and overall error was ≤ 5%. Audit tickets never revealed Kadı's answer.

## 5. What went wrong, and how it was fixed

### 5.1 Calibration selection bias (found in v0.2, fixed and pinned)

- **Symptom.** In the live demo, the per-label `is_urgent` question showed **42% audited agreement**, far below the promised 95%.
- **Cause.** Calibration had used only escalated examples. An input is escalated *because* its prediction set holds several labels, so the true label sits inside the set by construction. Observed miscoverage was therefore biased toward zero, ACI loosened α<sub>t</sub>, the sets shrank, more wrong local answers went unobserved, and the loop fed itself.
- **Fix.** Calibration now uses a **random, held-out** sample of the stream that is never trained on. Stored inputs are re-scored with the current model.
- **Pinned by** `tests/test_production.py::TestGuarantee`. A detailed write-up is in THEORY §5.

### 5.2 The oracle's noise floor

- **What happened.** With a 2%-noisy oracle and α = 3%, only about 46% of decisions stayed local, and Kadı escalated almost everything.
- **Why that is correct.** No system can agree with an oracle more often than the oracle agrees with itself. Choosing α ≈ ε forces escalation in order to keep the bound.
- **What changed.** The rule "pick α above your oracle's noise floor" is now documented.

### 5.3 Adversarial security review (v0.2)

An independent review found **11 issues**; all were fixed, each with a regression test (`TestSecurityRegressions`). The most serious:

- CSRF and DNS rebinding against a tokenless loopback instance;
- shadow mode stuck permanently on probation;
- memory blow-up from random 100k-character inputs, which reached 841 MB;
- a negative `Content-Length` bypassing the body cap;
- redaction merging different inputs into one memory key;
- audits returning a label the oracle had just contradicted.

### 5.4 Smaller lessons

- **A drift test that never tripped.** When the oracle flipped its labels, Kadı relearned within about 40 decisions, so the breaker correctly stayed quiet. The test was rewritten to exercise the breaker directly.
- **Per-label guarantees don't scale to 77–150 labels.** Every label needs its own evidence, so local answers stay near zero. This is documented: use it for questions with few labels.
- **Stale numbers.** The synthetic demo table was re-measured after engine changes instead of being carried forward.
- **One unexplained test error.** It appeared once during v0.5 development and did not reproduce in the next 24 runs or in CI. It is recorded here rather than hidden.

## 6. Verification inventory

| Check | Result |
|---|---|
| Unit, integration, security-regression and MCP tests | **87 tests**; 2 numpy-only tests are skipped on the stdlib-only interpreter |
| LTT certificate validity | Simulation over 300 draws: certificate failure rate within δ (test tolerance +0.03) |
| CI (GitHub Actions) | Python 3.11, 3.12 and 3.13; semantic reflex; TypeScript type-check; Docker build. All green at v0.5.0 |
| Ledger integrity | Tests detect edited, deleted and inserted rows and a wrong key |
| MCP | Legacy and 2026-07-28 negotiation, JSON-RPC errors, learning loop, persistence, stdio end-to-end through a real subprocess |

## 7. What is not verified yet

| Gap | How to close it |
|---|---|
| Benchmarks used **gold labels**, not a real LLM, as the oracle | `python benchmarks/run.py --oracle anthropic --n 2000` with an API key |
| No **Turkish** benchmark | Run a Turkish intent dataset with the multilingual reflex |
| Not exercised against a **real MCP client** (Claude Code / Desktop) | `claude mcp add kadi -- kadi mcp` on a project with repetitive classification work |
| Single process + SQLite | Postgres backend (roadmap) |
| No production traffic yet | Replay → shadow → live on a real application |

## 8. Reproducing everything

```bash
python -m unittest discover -s tests                         # 87 tests
python examples/demo.py                                      # demo + dashboard on :8765
python benchmarks/run.py                                     # hashed reflex, all policies (~3.5 MB download, SHA-256 verified)
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -e ".[embed]"
.venv/bin/python benchmarks/run.py --reflex bge --knn --policies conformal,ltt --taus "" --tag=-bge-knn
```
