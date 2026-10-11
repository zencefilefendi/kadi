# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.6.0] — 2026-10-11

Roadmap **P0**: the guarantee becomes exact and holds at every point in time. Existing databases upgrade in place. Learned models are kept, but certificates are re-issued, because v0.5 calibration samples predate the frozen versions.

### Changed (statistics)
- **Frozen model versions.**
  - A live model learns from every oracle label; only frozen snapshots answer.
  - Each version is calibrated only on samples drawn *after* its freeze, and nothing is re-scored. Model–calibration independence now holds exactly.
  - A certified candidate replaces the served version when it answers at least as often on the same samples.
- **Anytime-valid Learn then Test.** Thresholds are certified by betting e-processes with Ville's inequality, so the certificate holds uniformly over time, not pointwise.
- **δ spending across versions.** δ_v = δ·6/(π²v²), so all certificates ever issued hold simultaneously with probability ≥ 1 − δ.
- **Drift e-detector.** A Shiryaev–Roberts e-detector on the deployed joint loss Pr(local ∧ wrong) controls the expected time to a false alarm (`drift_arl`, default 1,000). On alarm the served version is re-certified, the court goes on probation and an alert is sent. It replaces the Wald test on Pr(wrong | local).
- **Empty-set rule.** An empty conformal set answers the argmax. This is free against α and keeps the local share monotone in α; a replay test had shown the old behaviour falling as α loosened.
- **Calibration sampling.** The rate depends only on the past: everything is sampled while uncertified or in shadow mode, otherwise `sample_budget / recent local share`. Calibration labels also train the live model afterwards. `candidate_rate` is replaced by `sample_budget`; `WARMUP_HOLDOUT` and `SHADOW_HOLDOUT` are removed.

### Changed (systems)
- **Off-lock binary checkpoints.** State is captured under the lock in ~10 ms, then packed (float32, with rows deduplicated against the live model) and written in the background. Files sit next to the database, are written atomically and have their SHA-256 recorded in SQLite; a tampered file is refused.
- **Measured at CLINC150 scale:** the lock is held for 11 ms (was 5.82 s), and a snapshot is 43 MB (was a 411 MB JSON file).
- **Ledger.** Every local decision records its model version inside the HMAC chain (`chain_fmt` 2). Older rows keep verifying with their original column set.
- **Distribution renamed `kadi-cascade`.** `kadi` on PyPI belongs to Kadi4Mat; the import name stays `kadi`.
- **Dashboard and MCP** show the served and candidate versions and the drift monitor.

### Results
- **Validity.** On Banking77 and CLINC150 (3 seeds, full datasets) the bound held in **126/126** runs.
- **Savings at α = 5%.** bge + k-NN with conformal removes 65% / 79% of oracle calls; with the time-uniform LTT certificate, 61% / 73%.
- **Cost of strict validity.** Compared with v0.5, the local share falls by a median of 9.3 points (range −1.5 to +19.7) across 36 configurations. ENGINEERING §5.5 shows how this was engineered down from an initial ~30-point loss.

### Correction
- The v0.5.1 release notes said the dashboard had been checked in a browser under the new CSP. That check most likely ran against an older copy of the code: the preview tool started the server from a stale working directory. The nonce behaviour itself was verified over HTTP by `test_v6_dashboard_uses_a_script_nonce_not_unsafe_inline`. In v0.6.0 the dashboard was rendered in a browser from this repository: the page served a per-response nonce, the scripts ran and no CSP violations were reported.

### Tests
- 102 tests. New:
  - time-uniform LTT validity by simulation;
  - exact certification time;
  - δ-spending sum;
  - e-detector ARL and detection;
  - frozen versions, promotions and restart;
  - tampered snapshots;
  - checkpoint lock time;
  - end-to-end drift alarm and recovery;
  - model version inside the chain.

## [0.5.1] — 2026-10-11

Security and documentation release. Calibration and decisions are unchanged, and existing databases upgrade in place.

### Security
Seven findings from the second independent security review are fixed, each with a regression test (`TestSecurityRegressionsV2`):
- **V1:** rows without a hash after the chain start are now reported as tampering. The chain start is recorded once, so v0.1/v0.2 rows stay valid.
- **V2:** prompt delimiters can't be forged any more; untrusted text and context are HTML-escaped instead of having their tags stripped.
- **V3:** deeply nested JSON returns a parse error instead of crashing the MCP server, and a 400 from the HTTP API.
- **V4:** failed authentications are rate-limited in a separate bucket, so bad tokens can't exhaust legitimate callers' quota.
- **V5:** pruning deletes a contiguous id-prefix, so the chain stays verifiable with a non-monotonic clock.
- **V6:** the dashboard CSP uses a fresh script nonce per response instead of `'unsafe-inline'`, and API responses allow no scripts.
- **V7:** caller-supplied text echoed into errors is truncated and made single-line, since those errors reach LLM agents.

### Documentation
- `ROADMAP.md` (EN) and `ROADMAP.tr.md` (TR), produced by a five-engineer review covering statistics, ML, systems, security and research/ecosystem.
- THEORY §7c, "Known statistical caveats": the certificate is pointwise in time, independence holds only approximately, the drift breaker tests a different quantity, ACI on a thinned stream, mixed sampling rates, and memory answers.
- Engineering report: the second security review; test counts updated to 95.
- Threat model: T4, T9, T14, T16 and T17 updated for the new controls.

## [0.5.0] — 2026-10-10

### Added
- **MCP server** (`kadi mcp`): stdio, zero dependencies, dual-era (legacy `initialize` 2024-11-05 … 2025-11-25 and modern 2026-07-28 with `server/discover` and per-request `_meta`). Eight tools: `kadi_define_question`, `kadi_list_questions`, `kadi_decide`, `kadi_resolve`, `kadi_teach`, `kadi_stats`, `kadi_recent_decisions`, `kadi_verify_ledger`.
- **Agent-as-oracle**: when Kadı may not decide alone, it returns a ticket. The calling model judges the case and answers with `kadi_resolve`, and that verdict trains and calibrates Kadı. Audit tickets are blind (all options, no hint). No API key is required.
- Engine: `Kadi.decide_or_defer()` / `Kadi.resolve()` two-phase API and the `Pending` type. `decide()` is refactored onto the same route → complete path with no behaviour change.
- `docs/MCP.md`; threat-model entries T17–T18; `tests/test_mcp.py` (protocol negotiation, errors, learning loop, persistence, stdio end-to-end).

## [0.4.1] — 2026-10-10

Patch release: documentation and API metadata only. No change to calibration, decisions or stored data.

### Documentation
- README / README.tr: "Status and known limitations" section, refreshed roadmap, `kadi[embed]` install line; the synthetic demo table was re-measured with the current engine.
- CONTRIBUTING: semantic-reflex development setup and benchmark rules (evaluation seeds 0–2, tuning only on seeds ≥ 100).
- SECURITY: supported versions updated to 0.4.x.

### Changed
- `GET /api/questions` (and the TypeScript `QuestionInfo` type) now include `policy`, `delta` and `instructions`.

## [0.4.0] — 2026-10-10

### Added
- **Semantic reflex** (optional extra `kadi[embed]`): `FastEmbedder` (fastembed/ONNX, multilingual MiniLM by default), `HybridFeaturizer` (hashed n-grams + dense embedding block) and `KNNHybridReflex` (k-NN vote over oracle-labelled examples mixed with the online logistic model). Pluggable via `Kadi(featurizer=..., reflex=...)` or `reflex = "embed"` in `kadi.toml`.
- Benchmark support for embedding reflexes (`--reflex bge|minilm --knn`), with embeddings pre-computed and cached once per dataset.
- CI job that tests the semantic reflex with numpy and a toy embedder, without downloading a model.

### Results
- At α = 5% with LTT, the share of decisions answered locally rose from 63.9% to 79.6% on Banking77 and from 79.5% to 89.8% on CLINC150, cutting oracle calls by 36–40%. The bound held in 126 of 126 benchmark runs.

### Changed
- The novelty guard measures unseen mass only over the sparse n-gram block (`novelty_limit`), so dense features don't mask out-of-distribution inputs.

## [0.3.0] — 2026-10-10

### Added
- **Learn then Test policy** (`policy = "ltt"`): selective classification with a high-probability guarantee, meaning decision risk ≤ α with probability ≥ 1 − δ over the calibration sample. It uses exact binomial p-values with fixed-sequence testing on a pre-registered grid, and its validity is checked by simulation.
- **Tamper-evident ledger**: each decision row is HMAC-chained to the previous one. `kadi verify` detects edited, deleted or inserted rows, and `kadi anchor` exports the chain head. Pruning stays verifiable through an anchor.
- **Public benchmark** (`benchmarks/`): Banking77 and CLINC150, with dataset files pinned by SHA-256, multi-seed runs in parallel, confidence-threshold baselines, and an optional real Claude oracle.
- `kadi replay --policy ltt --audit-rate`; the dashboard shows the LTT threshold λ and a policy badge.

### Changed
- The reflex learner's inner loops are about 3–5× faster. Calibration scores are kept incrementally, and full re-scoring is time-budgeted (≤ ~10% of wall time), which matters with 100+ labels.

## [0.2.0] — 2026-10-10

### Added
- Service mode: `kadi serve` with `kadi.toml`; secrets only via environment variables.
- `kadi replay`: α sweep on labelled history before going live.
- Shadow mode, Mondrian (per-label) conformal, novelty guard, drift breaker with probation and webhook alerts, oracle-outage fallback.
- PII and secret redaction (TCKN, IBAN, cards, phones, e-mail, IPs, keys, JWTs); keyed HMAC input hashes; retention pruning.
- Hardened HTTP API: bearer auth, rate limiting, CSRF and DNS-rebinding guards, CSP; Prometheus `/metrics`; batch and teach endpoints.
- TypeScript client, Docker image and compose file, CI.
- `docs/THEORY.md`, `docs/THREAT_MODEL.md`.

### Fixed
- **Calibration selection bias.** v0.1 calibrated on escalated examples, which are inside the prediction set by construction, so the threshold ratcheted loose; local per-label agreement could fall to 42%. Calibration now uses a random, held-out, re-scored sample.
- Eleven issues from an adversarial security review, each with a regression test (see `TestSecurityRegressions`).

## [0.1.0] — 2026-10-10

### Added
- Initial prototype: memory, reflex and oracle cascade; adaptive conformal prediction; Divan dashboard; demo.
