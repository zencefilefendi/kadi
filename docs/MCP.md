# Kadı over MCP

Kadı ships an [MCP](https://modelcontextprotocol.io) server, so agents in Claude Code, Claude Desktop or any other MCP client can use it as a tool. It runs on stdio and has zero dependencies.

## Agent-as-oracle: no API key needed

The MCP client is already driven by a frontier model, so Kadı doesn't need its own:

```
agent ── kadi_decide(question, text) ──► Kadı
                                          ├─ confident & calibrated ──► {"status": "decided", "label": ...}
                                          └─ otherwise ──────────────► {"status": "needs_verdict", "ticket": ...}
agent judges the case itself ── kadi_resolve(ticket, label) ──► Kadı learns + calibrates
```

- **Learning.** Every verdict you resolve trains the local reflex. A random share is held out for calibration and is never trained on.
- **The guarantee.** It is relative to the agent's own judgement: Pr(Kadı's label ≠ the agent's verdict) ≤ `target_error`. With the default `ltt` policy this holds with probability ≥ 95%.
- **Audits are blind.** Random audit tickets list *all* options and don't reveal Kadı's answer, so the agent's verdict isn't anchored and the measured agreement stays honest.
- **Warm-up.** Kadı answers alone only once it can *certify* the error target. Under LTT at α = 5%, that takes at least 59 calibration samples. About 25% of warm-up verdicts are held out for calibration, so expect roughly 240 resolved tickets before the first local answers. A lower α needs more samples (α = 1% needs 299). This is the price of a real guarantee.
- **What it's for.** Decisions you make repeatedly in the same shape: triage, routing, intent, spam/abuse, "does this diff need review". It isn't meant for one-off questions.

To use an API oracle instead, configure `[oracle]` in `kadi.toml` and run `kadi mcp --config kadi.toml --oracle config`. Kadı then calls the oracle itself and always answers in one step.

## Install

```bash
pip install git+https://github.com/zencefilefendi/kadi
```

**Claude Code**

```bash
claude mcp add kadi -- kadi mcp                                   # this project only (local scope)
claude mcp add --scope user kadi -- kadi mcp                      # all your projects
claude mcp add --env KADI_SECRET=change-me --transport stdio kadi -- kadi mcp   # with a ledger key
```

`--` separates Claude Code's options from the server command. When you use `--env`, put another option such as `--transport stdio` before the server name, or the name is read as another `KEY=value`.

**Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "kadi": { "command": "kadi", "args": ["mcp"] }
  }
}
```

If `kadi` isn't on the client's `PATH`, use the interpreter directly: `"command": "/path/to/python3", "args": ["-m", "kadi.cli", "mcp"]`.

State lives in `~/.kadi/mcp.db` (directory mode 0700). Use `--db` to change it, and set `KADI_SECRET` in the server environment for real tamper evidence.

## Tools

| Tool | Read-only | Purpose |
|---|---|---|
| `kadi_define_question` | no (idempotent) | Register a decision type: `name`, `options`, optional `instructions`, `target_error` (default 0.05), `policy` (`ltt` default, or `conformal`), `mode` (`live` or `shadow`). Definitions persist across restarts. |
| `kadi_list_questions` | yes | Registered questions, how often Kadı decides each alone, and measured agreement. |
| `kadi_decide` | no | Decide a case: returns `decided` with a label, or `needs_verdict` with a ticket. |
| `kadi_resolve` | no | Answer a ticket with your verdict. An invalid label leaves the ticket open for retry. Tickets expire after 1 hour. |
| `kadi_teach` | no (idempotent) | Add a known-correct label. It trains the model but never calibrates, so it cannot loosen the bound. |
| `kadi_stats` | yes | Decisions, local share, audited agreement, calibration and probation state, escalation reasons, alerts. |
| `kadi_recent_decisions` | yes | The decision history with filters and `before_id` pagination. Previews are redacted, untrusted text. |
| `kadi_verify_ledger` | yes | Re-derives the HMAC hash chain over every stored decision. |

All tools return `structuredContent` alongside a JSON text block. Validation problems come back as tool errors (`isError: true`) whose message tells the agent what to fix.

## Example session

```
→ kadi_define_question {"name": "ticket_route", "options": ["billing", "bug", "account", "spam"],
                        "instructions": "Which team should handle this support ticket?"}
→ kadi_decide {"question": "ticket_route", "text": "I was charged twice this month"}
← {"status": "needs_verdict", "ticket": "Qm9...", "reason": "uncalibrated", "candidates": [...]}
→ kadi_resolve {"ticket": "Qm9...", "label": "billing"}
   … a few hundred cases later …
→ kadi_decide {"question": "ticket_route", "text": "refund my double charge please"}
← {"status": "decided", "label": "billing", "tier": "reflex", "reason": "confident", "confidence": 0.97}
```

## Protocol support

The server is dual-era, as the MCP specification describes:

- **Legacy clients** open with `initialize`. Supported versions are 2025-11-25, 2025-06-18, 2025-03-26 and 2024-11-05; the server echoes the client's version when it supports it.
- **Modern clients (2026-07-28)** may call `server/discover` and carry `io.modelcontextprotocol/protocolVersion` and `io.modelcontextprotocol/clientCapabilities` in each request's `_meta`. Results include `resultType: "complete"` and `serverInfo` in `_meta`.
- An unsupported modern version returns `-32022` with the list of supported versions. A missing required `_meta` field returns `-32602`.
- Messages are newline-delimited JSON-RPC 2.0 on stdout, and logs go to stderr only. Lines are capped at 1 MiB, and batches are accepted for 2025-03-26 clients.
