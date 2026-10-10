# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.4.x | ✅ |
| < 0.4 | ❌ |

## Reporting a vulnerability

**Please do not open a public issue.** Use GitHub's private vulnerability reporting: *Security → Report a vulnerability* on this repository.

Include:

- the affected version or commit;
- a description of the issue and its impact;
- reproduction steps or a proof of concept.

We aim to acknowledge reports within 72 hours and to publish a fix, with a regression test and a credited advisory, as soon as one is ready.

## Scope

The threat model, controls and residual risks are documented in [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md). Things that are out of scope by design: running without TLS on a public network, sharing `KADI_TOKEN` with untrusted parties, and an oracle that is itself malicious (that shows up as drift, not as a vulnerability).
