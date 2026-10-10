# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
