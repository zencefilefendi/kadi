# Kadı — Threat Model

Kadı sits on the decision path of an application. A compromised decision service can approve what should be rejected, leak the data it sees, or burn the oracle budget. This document lists what Kadı defends against, how, and what it leaves to the operator.

## Assets

| Asset | Why it matters |
|---|---|
| Decision integrity | Wrong labels propagate into the application: routing, moderation, approvals. |
| Input data | Tickets, messages and documents may contain personal data (KVKK / GDPR). |
| Oracle credentials and budget | API keys; every escalation costs money. |
| Model and calibration state | Poisoning them silently degrades future decisions. |

## Trust boundaries

```
 untrusted text ──► [ HTTP API ] ──► engine ──► oracle (third-party LLM)
                        ▲                │
 operator ─ token ──────┘                └──► SQLite ledger (local disk)
 browser ─ dashboard (token in sessionStorage)
```

## Threats and controls

| # | Threat | Control | Test |
|---|---|---|---|
| T1 | Unauthenticated use of the API | Bearer token, constant-time compare; refuses to bind a non-loopback address without a token | `TestServer.test_auth_and_health`, `test_refuses_public_bind_without_token` |
| T2 | CSRF from a web page against a tokenless loopback instance | Exact `application/json` content type (no CORS "simple request"); `Origin` must match `Host` | `TestSecurityRegressions.test_csrf_simple_request_refused` |
| T3 | DNS rebinding | Without a token, only loopback `Host` headers are accepted | `test_dns_rebinding_host_refused_without_token` |
| T4 | Resource exhaustion | 256 KB body cap (negative lengths rejected), deep-nesting JSON rejected as a parse error, failed authentications rate-limited in a separate bucket, 32k-character input cap, 4k-character / 2,048-feature featurizer cap, per-client token bucket with bounded pruning, socket timeouts | `test_negative_content_length`, `test_huge_random_input_is_bounded`, `test_rate_limiter_prune_is_bounded`, `TestServer.test_rate_limit` |
| T5 | Personal data in storage | Redaction before preview storage and featurization: TCKN (checksum), IBAN (mod-97), cards (Luhn + IIN), phones, e-mail, IPs, API keys, JWTs, URL credentials. Optional `store_inputs = false`. Retention pruning | `tests/test_redact.py`, `TestPrivacy` |
| T6 | Personal data sent to a third-party oracle | `redact_oracle = true` redacts both text and context before the oracle call | `test_context_redacted_for_oracle` |
| T7 | Guessing inputs from stored hashes | Keyed HMAC-SHA256. Set `KADI_SECRET`; otherwise a per-database key is used and a warning is emitted | `test_pii_redacted_in_ledger_and_hash_is_keyed` |
| T8 | Cache collision through redaction | Memory keys are computed on the *raw* input, so redaction never merges distinct inputs | `test_redaction_does_not_merge_memory_keys` |
| T9 | Prompt injection steering the oracle | Untrusted text and context are HTML-escaped (so no delimiter can be forged or closed) inside `<input>` / `<context>` blocks marked as data, a system rule tells the model to ignore instructions there, and the output is schema-locked to the declared options | review; see Greshake et al. 2023 |
| T10 | Adversarial or out-of-distribution inputs aimed at the local model | Novelty guard escalates inputs mostly made of unseen features; the conformal set must be a singleton that agrees with argmax | `TestModes.test_novel_input_escalates` |
| T11 | Silent degradation (drift, poisoning, oracle change) | Random audits, ACI, a drift e-detector with ARL control (alarm → re-certification, probation, alert), realised miscoverage on the dashboard | `TestResilience.test_drift_alarm_recertifies_and_alerts`, `test_drift_detector_false_alarms_and_detection`, `TestGuarantee` |
| T12 | Oracle outage | `on_oracle_error = "best_guess"` returns flagged local answers; `"raise"` returns HTTP 502 | `TestResilience.test_fallback_when_oracle_down` |
| T13 | Information leakage in errors | Generic `internal error` responses; no stack traces; no server version banner | `TestServer.test_bad_inputs` |
| T14 | Dashboard XSS | All database strings are escaped before `innerHTML`; the dashboard CSP allows only a fresh per-response script nonce (no `'unsafe-inline'`); API responses allow no scripts at all | review |
| T16 | Rewriting history: editing, deleting or inserting past decisions in the ledger | Every row carries `prev_hash` and `row_hash = HMAC(K, prev_hash ‖ canonical row)`, with K derived from `KADI_SECRET`. `kadi verify` re-derives the chain and names the first bad row; rows without a hash after the chain start count as tampering. Pruning deletes a contiguous id-prefix and records an anchor, so it stays verifiable even with a non-monotonic clock. `kadi anchor` exports the chain head for external safekeeping, which also defends against a key holder | `TestLedger` |
| T17 | MCP: untrusted text re-entering the agent's context (prompt injection via `kadi_recent_decisions` previews or ticket fields) | Stdio only, so there is no network listener. Previews are redacted and truncated to 160 characters, and the tool description labels them as untrusted data. Questions and options come only from the agent's own `kadi_define_question` calls. Errors never include stack traces, and caller text echoed into them is truncated and made single-line. The ledger lives in `~/.kadi` with mode 0700 | `tests/test_mcp.py` |
| T18 | MCP: a buggy or adversarial agent poisoning Kadı with wrong verdicts | By design the guarantee is relative to the agent's judgement. Blind audits measure agreement with the agent; the drift e-detector reacts to sustained changes; `kadi_teach` labels never calibrate | `TestAgentAsOracle` |
| T19 | Tampering with or swapping persisted model state, so that a poisoned model is served after a restart | Model snapshots are written atomically (mode 0600, directory 0700) and their SHA-256 is recorded in SQLite; a mismatch is refused and the court starts fresh instead of loading it. Certificates are tied to the frozen version they were earned by, and every local decision records that version inside the HMAC chain | `TestVersions.test_tampered_snapshot_is_refused`, `test_model_version_is_recorded_and_chained` |
| T15 | Container escape and privilege | Non-root UID, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, port published on loopback only | `docker-compose.yml` |

## Residual risks (operator responsibility)

- **TLS.** Kadı serves plain HTTP. Put it behind a TLS-terminating reverse proxy for any non-loopback traffic.
- **Ledger key.** Without `KADI_SECRET`, the chain key is derived from a secret stored in the same database, so someone who can write the database can also re-forge the chain. Set `KADI_SECRET`, and anchor the head externally (`kadi anchor`) on a schedule.
- **Disk encryption.** The SQLite ledger is not encrypted at rest. Use full-disk or volume encryption, or SQLCipher.
- **Single shared token.** There is no per-user identity or RBAC. Rotate `KADI_TOKEN`, and front the service with your identity proxy if you need per-user access.
- **Label poisoning through `/api/teach`.** Anyone holding the token can train the reflex. Teach labels never calibrate, so they cannot weaken the error bound, but they can lower the local rate. Restrict who holds the token.
- **Oracle trust.** The guarantee is relative to the oracle. A compromised or changed oracle model is detected only as drift.

## Reporting

See [SECURITY.md](../SECURITY.md).
