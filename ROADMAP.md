# Kadı Roadmap

This roadmap comes out of a five-engineer review: statistics, ML, systems, security, and research/ecosystem. Each reviewer read the code and documentation independently, and some ran measurements. Items are ordered by priority, and **validity fixes come first**.

## P0: correctness and validity (before any new features)

| # | Item | Why | Done when |
|---|---|---|---|
| 1 | **Anytime-valid certification and monitoring** (confidence sequences / betting bounds; Howard et al. 2021, Waudby-Smith & Ramdas 2024) | LTT is re-certified on every sample, so "w.p. ≥ 1−δ" holds only pointwise in time. The drift breaker tests Pr(wrong \| local) with a Wald interval on overlapping windows | False-probation rate ≤ δ′ over 10⁶ simulated decisions; a pinned regression test |
| 2 | **Certify frozen model snapshots** | Held-out samples shape which escalations train the reflex, so "p̂ independent of calibration" holds only approximately | Simulated violations ≤ δ under adversarial feedback; certificate ↔ model version recorded per decision |
| 3 | **Checkpointing off the hot path, binary snapshots** | Measured: a 365 MB JSON checkpoint at 150 labels; `json.dumps` takes 6 s **while holding the question lock** | Reflex p99 unchanged during a checkpoint; snapshot ≤ 70 MB |
| 4 | ~~Remaining security findings V5–V7~~ | Second security review | ✅ **Done in v0.5.1**: contiguous-prefix pruning, per-response CSP script nonce, truncated single-line error echoes |
| 5 | **Package name** | `kadi` is taken on PyPI (Kadi4Mat); `import kadi` would collide | Publish as `kadi-cascade` with Trusted Publishing; decide on the import name |

All seven findings of the second security review (V1–V7) are fixed in v0.5.1, each with a test in `TestSecurityRegressionsV2`.

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
