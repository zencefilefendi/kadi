# Kadı: Engineering Report

This report covers what was built, which techniques were used and why, what was measured, what went wrong and how it was fixed, and what is still unverified. Every number here can be reproduced from files in this repository. The formal statements are in [THEORY.md](THEORY.md), and security is covered in [THREAT_MODEL.md](THREAT_MODEL.md).

---

## 1. The problem and the answer in one paragraph

LLM agents make many small, multiple-choice decisions. A frontier model gets them right but is slow and expensive; a small model is cheap but its error rate is unknown. Kadı is a cascade: exact memory, then a local reflex, then the oracle. The reflex answers **only when a statistical test certifies** that answering locally keeps the disagreement with the oracle at or below a user-chosen α. Everything else is escalated, and every escalation teaches the reflex. Since v0.6 only *frozen* model versions answer, each certified on data drawn after its freeze, and the Learn-then-Test certificate holds at every point in time. On two public intent benchmarks, Kadı removed **65–79% of oracle calls at α = 5%** (61–73% with the time-uniform certificate). The error bound held in **126 of 126** runs.

## 2. Version history

| Version | What it added |
|---|---|
| 0.1 | Prototype: memory, reflex and oracle cascade; adaptive conformal prediction; dashboard |
| 0.2 | Production layer: shadow mode, replay, Mondrian conformal, drift breaker, fallback, PII redaction, hardened HTTP API, TypeScript client, Docker, CI. Fixed the **calibration selection-bias bug** (§5.1) and the **11 findings of an adversarial security review** (§5.3) |
| 0.3 | Learn then Test (high-probability guarantee), tamper-evident ledger, public benchmark |
| 0.4 | Semantic reflex: sentence embeddings + k-NN (optional extra) |
| 0.4.1 | Documentation patch: status and limitations, re-measured demo |
| 0.5 | MCP server with **agent-as-oracle** (no API key) |
| 0.5.1 | Second security review (V1–V7 fixed), five-engineer roadmap, statistical caveats documented |
| 0.6 | **Roadmap P0**: frozen model versions, anytime-valid LTT, e-detector, δ spending across versions, empty-set rule, adaptive free sampling, binary off-lock checkpoints, distribution renamed `kadi-cascade` |

## 3. Techniques

### 3.1 Statistics: when Kadı may answer alone

| Technique | Where | Why | Reference |
|---|---|---|---|
| Split conformal prediction | `kadi/conformal.py` `AdaptiveConformal` | Turns any scorer into prediction sets with coverage ≥ 1 − α; answering only when \|C(x)\| ≤ 1 bounds the disagreement | Vovk et al. 2005; Papadopoulos et al. 2002; Lei et al. 2018 |
| Empty-set rule (v0.6) | `engine._route` | An empty set is already a miscoverage event, so answering the argmax there costs nothing against α and keeps the local share monotone in α | — |
| Adaptive Conformal Inference | same, `alpha_t` update | Keeps long-run miscoverage near α when traffic drifts | Gibbs & Candès 2021 |
| Mondrian (per-label) conformal | `MondrianConformal` | A rare but critical label gets its own bound | Vovk 2012 |
| **Anytime-valid Learn then Test** (v0.6) | `LearnThenTest` | Betting e-processes per threshold plus Ville's inequality: risk ≤ α with probability ≥ 1 − δ, **uniformly over time** | Angelopoulos, Bates, Candès, Jordan & Lei 2021; Ramdas et al. 2023; Waudby-Smith & Ramdas 2024 |
| **Frozen model versions** (v0.6) | `engine._Brain` (`live`, `served`, `candidate`) | The scored model is independent of its calibration data: each version is calibrated only on samples drawn after its freeze, and nothing is re-scored | — |
| **δ spending across versions** (v0.6) | `version_delta` | δ_v = δ·6/(π²v²) sums to δ, so all certificates hold simultaneously and any promotion rule is safe | — |
| Random, input-independent sampling | `engine._route` | The calibration coin depends only on the past (§5.1); escalations are sampled for free, local answers within `sample_budget` | — |
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
| **Drift e-detector** (v0.6) | `conformal.DriftDetector`, `engine._monitor` | Shiryaev–Roberts e-detector on the deployed joint loss; expected time to a false alarm ≥ ARL. On alarm: re-certify the served version, probation, webhook alert (Shin, Ramdas & Rinaldo) |
| Shadow mode, replay | `questions.py`, `cli.py replay` | Prove the value risk-free before going live |
| Fallback | `on_oracle_error="best_guess"` | When the oracle is down, return flagged local answers |
| Tamper-evident ledger | `store.py` | HMAC hash chain over every decision; `kadi verify` and `kadi anchor` |
| PII redaction with checksums | `redact.py` | TCKN (checksum), IBAN (mod-97), cards (Luhn + IIN), phones, e-mail, keys, JWTs |
| Hardened HTTP | `server.py` | Constant-time bearer auth, CSRF and DNS-rebinding guards, token-bucket rate limiting, body caps, CSP |
| Prompt-injection delimiting | `oracles.py` | User text is marked as untrusted data; output is schema-locked to the options |
| **Agent-as-oracle** two-phase API | `decide_or_defer` / `resolve`, `mcp.py` | Over MCP the calling model *is* the oracle. Blind audits keep agreement honest |
| Supply chain | `benchmarks/datasets.py`, `pyproject.toml` | Zero core dependencies; benchmark data pinned by SHA-256 |
| **Off-lock binary checkpoints** (v0.6) | `snapshot.py`, `engine._CheckpointWriter`, `store.save_snapshot` | Capture under the lock in ~10 ms; pack (float32, rows deduplicated against the live model) and write atomically in the background; SHA-256 recorded in SQLite, and a tampered file is refused |

## 4. Results

### 4.1 Public benchmarks

**Setup.**
- **Datasets.** Banking77 has 13,083 queries over 77 intents; CLINC150 has 22,500 queries over 150 intents.
- **Protocol.** Each dataset is streamed once, in a seeded random order. The gold label acts as the oracle, so *error* = disagreement with the oracle = error against ground truth. Results are the mean of seeds 0–2 with the v0.6 engine.
- **Calls** = oracle calls per decision, including audits; oracle-only = 1.00.

**α = 5%:**

| Reflex | Policy | Banking77 local / error / calls | CLINC150 local / error / calls |
|---|---|---|---|
| — | naive threshold τ = 0.5 (no guarantee) | 85.9% / **18.80%** / 0.14 | 87.2% / **10.41%** / 0.13 |
| — | hand-tuned threshold τ = 0.9 (no guarantee) | 65.4% / 2.89% / 0.35 | 73.5% / 1.47% / 0.27 |
| hashed n-grams | conformal | 46.7% / 1.15% / 0.58 | 64.2% / 1.69% / 0.41 |
| hashed n-grams | LTT | 49.1% / 1.66% / 0.56 | 65.2% / 1.72% / 0.40 |
| MiniLM + k-NN | conformal | 63.8% / 2.46% / 0.42 | 77.4% / 3.27% / 0.28 |
| MiniLM + k-NN | LTT | 57.4% / 1.92% / 0.48 | 71.4% / 1.14% / 0.34 |
| **bge-small + k-NN** | **conformal** | **70.2% / 2.52% / 0.35** | **84.7% / 3.40% / 0.21** |
| **bge-small + k-NN** | **LTT** | **66.2% / 1.74% / 0.39** | **78.1% / 1.32% / 0.27** |

**Headline numbers:**

| Measure | Value |
|---|---|
| Runs in which the bound held | **126 / 126**, checked per seed (54 hashed, 36 MiniLM, 36 bge) |
| Oracle calls removed at α = 5% (best configuration) | **65%** (Banking77), **79%** (CLINC150), with bge + conformal; 61% / 73% with time-uniform LTT |
| Local-share cost of strict validity (v0.6 vs v0.5) | median 9.3 points over 36 configurations (range −1.5 to +19.7) |
| Conformal vs LTT | Conformal answered more often in 13 of 18 configurations (weaker guarantee) |
| Naive confidence router | 10–19% error with no warning |

Full tables: [benchmarks/results/](../benchmarks/results/). The v0.5 numbers are in the git history (tag `v0.5.1`).

### 4.2 Simulated support desk (`examples/demo.py`)

6,000 tickets through a 2%-noisy simulated oracle, with an oracle outage at 30–33% of the stream and a vocabulary drift at 50%:

| | Local | Audited agreement | Decision error (est.) | Realised set miscoverage | Spend vs. oracle-only |
|---|---|---|---|---|---|
| `route_ticket` (marginal, α = 5%) | 77.8% | 94.9% | 4.0% | 6.3% | $19.96 vs. $72 |
| `is_urgent` (per-label, α = 5%) | 52.2% | 95.5% | 2.3% | 5.5% | $36.73 vs. $72 |

Measured with v0.6. Decision error (local share × audited disagreement) stays below α. The set miscoverage is slightly above α, which an in-expectation guarantee allows: the run includes an outage, a drift and a noisy oracle (see THEORY §7c, §9). Compared with v0.4 (94.3% / 62.6% local), this is the same price of strict validity seen in §4.1.

### 4.3 Agent-as-oracle (MCP)

In `tests/test_mcp.py`, 1,200 simulated cases were sent through the MCP tools with the "agent" resolving every ticket. In the second half, **more than 60%** of decisions were made by Kadı alone, and overall error was ≤ 5%. Audit tickets never revealed Kadı's answer.

## 5. What went wrong, and how it was fixed

### 5.1 Calibration selection bias (found in v0.2, fixed and pinned)

- **Symptom.** In the live demo, the per-label `is_urgent` question showed **42% audited agreement**, far below the promised 95%.
- **Cause.** Calibration had used only escalated examples. An input is escalated *because* its prediction set holds several labels, so the true label sits inside the set by construction. Observed miscoverage was therefore biased toward zero, ACI loosened α<sub>t</sub>, the sets shrank, more wrong local answers went unobserved, and the loop fed itself.
- **Fix.** Calibration now uses a **random, held-out** sample of the stream that is never trained on. In v0.2–v0.5, stored inputs were re-scored with the current model. Since v0.6 each frozen model version is calibrated only on samples drawn after its freeze, and nothing is re-scored.
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

### 5.4 Second security review (v0.5)

A second independent review, done as part of the five-engineer roadmap, found **7 more issues**. All are fixed, each with a regression test (`TestSecurityRegressionsV2`):

- **V1:** rows without a hash could be inserted after the chain began and slip past `verify`.
- **V2:** prompt delimiters could be forged by nesting (`</in</input>put>`), because tags were deleted rather than escaped.
- **V3:** a single deeply nested JSON line crashed the MCP server.
- **V4:** with the rate limit applied before authentication, bad tokens could exhaust the quota of legitimate callers.
- **V5:** pruning with a non-monotonic clock could cut the chain in the middle.
- **V6:** the dashboard CSP allowed `'unsafe-inline'` scripts; it now uses a fresh nonce per response.
- **V7:** caller text was echoed into errors that flow back into LLM agents; it is now truncated and made single-line.

The same review led to the statistical caveats in THEORY §7c.

### 5.5 v0.6: the price of strict validity, and engineering it back

The roadmap's P0 items (frozen versions, anytime-valid certification, a detector with ARL control) make the guarantee exact. Their cost was measured on separate tuning orderings (seeds 100–101, Banking77, 4,000 decisions, LTT α = 5%) and engineered down in three steps:

| Step | Hashed local | bge + k-NN local |
|---|---|---|
| v0.5 (approximate validity) | 37.2%* | 56.0%* |
| v0.6 first attempt: fixed 5–10% sampling | 10.1%* | 22.2%* |
| + free sampling of escalations, `sample_budget`-adaptive rate | 21.0%* | 37.2%* |
| + share-based promotion (LTT), first freeze at 300 labels | ~24–25% | ~44–46% |

<sub>*Measured on seeds 0–1. The later rows use the tuning seeds 100–101; the final configuration was then evaluated once on seeds 0–2, giving the figures in §4.1.</sub>

What each step relies on:

1. **Free sampling.** Every calibration label can still train the live model *after* it has calibrated the versions frozen before it, so sampling an escalated case costs nothing. The rate may depend on the past (the recent local share), never on the current input.
2. **Share-based promotion.** Because δ spending makes all certificates hold at once, Kadı may promote whichever certified version answers more often on the candidate's own samples.
3. **Empty-set rule.** A replay test showed conformal's local share *falling* as α loosened: tighter thresholds produced empty sets, and those were escalated. An empty set is already a miscoverage, so answering the argmax there is free against α. The fix restored monotonicity.

The remaining gap is the honest price of a guarantee that holds exactly and at every time. P3 of the roadmap (a learned selection score, adaptive betting, cold-start seeds) targets it.

**Checkpoints.** Measured on a CLINC150-scale court: 75k features × 120 labels, 14 versions issued.

| | v0.5 (JSON, under the lock) | v0.6 (binary, in the background) |
|---|---|---|
| Time the lock is held | **5.82 s** | **0.011 s** |
| Size | 411 MB | **43 MB** |
| Write | inside the lock | 1.71 s, outside the lock |
| Load | — | 0.75 s |

### 5.6 Smaller lessons

- **A drift test that never tripped.** When the oracle flipped its labels, Kadı relearned within about 40 decisions, so the breaker correctly stayed quiet. The test was rewritten to exercise the breaker directly.
- **Per-label guarantees don't scale to 77–150 labels.** Every label needs its own evidence, so local answers stay near zero. This is documented: use it for questions with few labels.
- **Stale numbers.** The synthetic demo table was re-measured after engine changes instead of being carried forward.
- **One unexplained test error.** It appeared once during v0.5 development and did not reproduce in the next 24 runs or in CI. It is recorded here rather than hidden.

## 6. Verification inventory

| Check | Result |
|---|---|
| Unit, integration, security-regression and MCP tests | **101 tests**; 2 numpy-only tests are skipped on the stdlib-only interpreter |
| Time-uniform LTT validity | Simulation: 200 streams × 1,000 samples. The fraction of streams in which the certified threshold *ever* had risk > α stays within δ (+0.03 tolerance) |
| Exact certification time | Certifies after exactly `min_samples` clean samples (74 at α = δ = 5%), never earlier |
| δ spending | Σ_v δ_v < δ, checked numerically |
| E-detector | Mean time to a false alarm ≥ ARL under H0; detection in < 150 samples under a 4× shift |
| Frozen versions | Hammering the live model leaves served predictions unchanged; versions and certificates survive a restart; a tampered snapshot is refused; the checkpoint lock is held < 0.25 s at 60k features × 150 labels |
| Drift end-to-end | The oracle flips under a certified model: alarm, re-certification, alert, and recovery to < 5% error under the new regime |
| CI (GitHub Actions) | Python 3.11, 3.12 and 3.13; semantic reflex; TypeScript type-check; Docker build |
| Ledger integrity | Tests detect edited, deleted, inserted and unchained rows and a wrong key |
| MCP | Legacy and 2026-07-28 negotiation, JSON-RPC errors, learning loop, persistence, stdio end-to-end through a real subprocess |

## 7. What is not verified yet

| Gap | How to close it |
|---|---|
| Benchmarks used **gold labels**, not a real LLM, as the oracle | `python benchmarks/run.py --oracle anthropic --n 2000` with an API key |
| No **Turkish** benchmark | Run a Turkish intent dataset with the multilingual reflex |
| Not exercised against a **real MCP client** (Claude Code / Desktop) | `claude mcp add kadi -- kadi mcp` on a project with repetitive classification work |
| Single process; SQLite + snapshot side files | Postgres backend (roadmap) |
| No production traffic yet | Replay → shadow → live on a real application |

## 8. Reproducing everything

```bash
python -m unittest discover -s tests                         # 101 tests
python examples/demo.py                                      # demo + dashboard on :8765
python benchmarks/run.py                                     # hashed reflex, all policies (~3.5 MB download, SHA-256 verified)
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -e ".[embed]"
.venv/bin/python benchmarks/run.py --reflex bge --knn --policies conformal,ltt --taus "" --tag=-bge-knn
```
