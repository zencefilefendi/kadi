# Kadı Roadmap

This roadmap comes out of a five-engineer review: statistics, ML, systems, security, and research/ecosystem. Each reviewer read the code and documentation independently, and some ran measurements. Items are ordered by priority, and **validity fixes come first**.

## P0: correctness and validity — ✅ done in v0.6

| # | Item | Status in v0.6 | Evidence |
|---|---|---|---|
| 1 | **Anytime-valid certification and monitoring** | ✅ LTT certified by betting e-processes with Ville's inequality (time-uniform); the Wald drift breaker is replaced by a Shiryaev–Roberts e-detector on the deployed joint loss, with ARL control. *Criterion adjusted*: the detector guarantees an expected time to false alarm ≥ ARL, not a per-run probability | `test_ltt_certificate_is_anytime_valid` (200 streams × 1,000), `test_drift_detector_false_alarms_and_detection`, `test_drift_alarm_recertifies_and_alerts` |
| 2 | **Certify frozen model snapshots** | ✅ live / served / candidate versions; each calibrated only on samples drawn after its freeze; δ spent across versions (all certificates hold simultaneously); the model version is recorded per decision **inside the hash chain**. The adversarial-feedback simulation from the original criterion was not run separately: independence now holds by construction, and the engine-level bound tests pass | `TestVersions`, `test_model_version_is_recorded_and_chained`, `TestGuarantee`; 126/126 benchmark runs |
| 3 | **Checkpointing off the hot path, binary snapshots** | ✅ the lock is held for 11 ms (was 5.82 s); snapshot 43 MB (was 411 MB JSON), written in the background, atomically, SHA-256-verified on load | `test_checkpoint_holds_the_lock_only_briefly`, `test_tampered_snapshot_is_refused`; ENGINEERING §5.5 |
| 4 | Remaining security findings V5–V7 | ✅ done in v0.5.1 | `TestSecurityRegressionsV2` |
| 5 | **Package name** | ◐ the distribution is now `kadi-cascade`, and the import name stays `kadi`. **Still open**: publishing to PyPI (needs the maintainer's account and Trusted Publishing setup) and a final decision on the import-name clash with Kadi4Mat | `pyproject.toml` |

**The price, measured.** Strict validity costs a median of 9.3 points of local share across 36 benchmark configurations (range −1.5 to +19.7). P3 targets this gap.

## P1: evidence (make the claims credible)

- **Real LLM oracle runs.** Cache verdicts so one paid pass can replay every configuration. Account cost per 1k decisions. Measure oracle self-consistency ε (k = 5 samples, second model). Report Kadı vs. oracle, oracle vs. gold and Kadı vs. gold separately.
- **Baselines, ablations and statistics.** Baselines: a threshold tuned on a prefix of the same budget, FrugalGPT- and RouteLLM-style routers. Ablations: calibrating on escalated examples (the §5.1 bug), no re-scoring, no ACI, no novelty guard. Statistics: ≥ 10 seeds, bootstrap CIs, risk–coverage curves.
- **New task types:** moderation, code-review gating, agent tool selection.
- **Turkish benchmark:** MASSIVE tr-TR (intent) and OffensEval-2020 Turkish (moderation, license to be checked); optionally a responsibly built Turkish support-ticket set (datasheet, two annotators, κ).

## P2: performance and scale

- **`kadi[fast]`:** a numpy fast path (Rust later), equivalence-tested against the pure-Python reference. Target: CLINC150 runs ~10× faster.
- **Oracle pipeline:** async, single-flight on identical inputs, audits made asynchronous (the local path never waits), prompt caching, Batch API for shadow mode, replay and audits. Target: ≥ 40% cheaper per escalation.
- **Observability:** OpenTelemetry traces, per-tier latency histograms, and a **guarantee SLO** (95% upper bound on audited disagreement ≤ α) with burn-rate alerts.
- **MCP:** Streamable HTTP transport, durable tickets that survive restarts, and a listing on the MCP Registry.
- **Multi-instance:** a Postgres backend with a hash chain per question and a single writer per question elected by lease.

## P3: a better reflex (more decisions answered locally at the same α)

Realised error is 2–3% against a 5% budget, so part of the budget goes unused.

1. **A learned selection score instead of max-p.** Inputs: margin, k-NN/logistic agreement, nearest-neighbour similarity, novelty. Trained prequentially, never on calibration data. Target: Banking77 local ≥ 84% at α = 5%.
2. **Cold start:** LLM-generated seed paraphrases fed through `teach()`, plus a higher warm-up holdout. Target: ≥ 50% fewer labels before the first local answer.
3. **Class prototypes and label-name priors** in the k-NN reflex, for labels with few examples.
4. **Multi-tier cascade:** reflex → small LLM → frontier, certified jointly.
5. **Embedding fine-tuning** (SetFit-style) behind `kadi[train]`.
6. **Ordinal / bounded-loss risk** for Score questions, and **conformal risk control** for asymmetric costs and selective risk.
7. **Clustered conformal** (Ding et al. 2023) for per-group guarantees, replacing Mondrian, which does not scale.
8. **Active, importance-weighted audits** (Zrnic & Candès 2024) to cut audit cost.

## P4: security and privacy hardening

- **Ledger:** a Merkle log with inclusion proofs, signed tree heads anchored externally (Sigstore Rekor / RFC 3161), and checkpoint hashes in the log. Refuse to run without `KADI_SECRET`.
- **Supply chain:** pin actions and images by SHA or digest, `--require-hashes`, Sigstore-signed releases, SLSA provenance, a CycloneDX SBOM and OSSF Scorecard ≥ 8.
- **Fuzzing:** Atheris / ClusterFuzzLite for the redactor, prompt builder, MCP parser and HTTP handlers.
- **Identity:** OIDC/JWT with roles (`decide`, `teach`, `read`, `admin`), the caller's identity recorded in each ledger row, rate limits after authentication.
- **Poisoning resistance:** per-source quotas, clipped updates, quarantined teach labels, and a canary set with rollback.
- **Encryption at rest and KVKK/GDPR erasure:** envelope encryption, crypto-shredding per subject (the chain stores only commitments, so it still verifies after erasure), and minimising what the k-NN embedding memory keeps.

## P5: research and adoption

- **Paper:** *Certified Cascades: Online Learn-then-Test Routing of LLM Decisions with Held-out, Re-scored Calibration.*
  - C1: calibration bias and its fix.
  - C2: an anytime-valid guarantee (P0 #1).
  - C3: oracle calls cut 60–85% with a real oracle.
  - C4: agent-as-oracle.
  - Plan: a workshop paper first, then TMLR or ICML.
- **Integrations:** LangGraph node, LlamaIndex router, OpenAI Agents SDK guard; a `kadi replay` notebook; an EN/TR docs site.
- **90-day targets:** `pip install` works; real-oracle and Turkish tables published; ≥ 3 shadow deployments; ≥ 10 external issues.

## Moonshot: proof-carrying decisions

Make the engine deterministic, so that model state is a pure function of the ledger. Each decision would then carry a signed receipt: a Merkle inclusion proof, the model snapshot hash, the certificate state, and possibly a zk proof for the small linear/conformal step. Anyone could replay the log and check that every local answer was covered by a valid certificate when it was made, without seeing raw data. That is the standard regulated adopters (EU AI Act, KVKK, BDDK) would need.
