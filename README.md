# Kadı ⚖︎

**A calibrated judge that sits in front of your frontier model.**

Agents and apps make thousands of small, schema-shaped decisions: which team gets the ticket, spam or not, which tool runs next, whether a diff is safe to merge. Sending every one of them to a frontier model is slow and expensive. Sending them to a small model is cheap, but then you can't tell how often it is wrong.

Kadı is named after the Ottoman judge who settled everyday disputes so the Sultan didn't have to. It answers routine cases locally, escalates the rest, and attaches a **statistical guarantee** to the split. It runs on the Python standard library only, has zero dependencies, is licensed Apache-2.0, and works offline.

```
input ─► MEMORY   exact replay of an earlier oracle verdict                    µs   $0
     └─► REFLEX   local model; answers only if its conformal prediction set
                  holds exactly one label, the input isn't novel, and the
                  court isn't on probation                                      ms   $0
     └─► ORACLE   frontier model; its verdict trains the reflex and
                  recalibrates the guarantee                                     s    $$
     └─► FALLBACK oracle down + on_oracle_error="best_guess": best local
                  guess, flagged for review                                     ms   $0
```

## What makes it trustworthy

| Layer | What it does |
|---|---|
| **Schema lock** | Every answer, including the oracle's, is one of the declared options. Claude is forced through an enum tool; OpenAI-compatible models get a JSON re-ask. |
| **Conformal guarantee** | Kadı answers locally only when the [conformal](https://arxiv.org/abs/2107.07511) prediction set has exactly one label. Under exchangeability, the share of decisions that disagree with the oracle stays at or below α. |
| **Per-label guarantee** | `conditional=True` switches to Mondrian conformal, so the bound holds for *each* label. A rare, important label such as "fraud" or "urgent" can't hide behind a good average. |
| **Drift adaptation** | [Adaptive Conformal Inference](https://arxiv.org/abs/2106.00170) retunes α<sub>t</sub> online as traffic shifts. |
| **Novelty guard** | Inputs whose features are mostly unseen are escalated, never guessed. This covers both out-of-distribution and adversarial inputs. |
| **Audits** | A random `audit_rate` slice of local answers is re-asked to the oracle. Agreement on the dashboard is *measured*, not assumed. |
| **Drift breaker** | If audited disagreement is significantly above target (95% lower bound), the question goes on **probation**: everything is escalated for N decisions, an alert fires (Slack/Discord/Teams webhook), and the event is logged. |
| **Shadow mode** | `mode="shadow"`: the oracle always answers and Kadı only records what it *would* have said. You prove the value with zero risk before switching to `live`. |
| **Privacy** | PII redaction runs before storage and featurization, and optionally before the oracle. It covers e-mail, TR/intl phone, TCKN (checksum), IBAN (mod-97), cards (Luhn + IIN), IP, API keys/JWTs and URL credentials. Input hashes are keyed HMACs. `store_inputs=false` keeps text out of the ledger. Retention pruning is built in. |
| **Prompt-injection hygiene** | Text and context reach the oracle inside `<input>`/`<context>` delimiters, labelled as untrusted data, with a system rule to ignore instructions inside them. The answer is still schema-locked. |
| **Hardened service** | Bearer auth with constant-time compare. The service won't bind publicly without a token. It enforces exact `application/json` (no CSRF "simple requests") and an Origin check. Without a token it accepts only loopback Host headers, which blocks DNS rebinding. Features are bounded (≤ 2,048 per input) so model memory stays bounded. It applies per-client rate limiting, a 256 KB body cap, strict JSON validation, socket timeouts, CSP and anti-framing headers, and never returns internal error details. The Docker image runs as non-root with a read-only filesystem and drops all capabilities. |

### How calibration stays honest

- **Held-out calibration.** Calibration uses a random `audit_rate` sample of the stream (plus a random 25% of warm-up), and those examples are never trained on. An earlier version calibrated on escalated examples. Those are a biased sample: their label is inside the set by construction, so the threshold ratcheted looser and looser, and per-label agreement fell to 42%. A regression test now pins this.
- **Fresh scores.** Calibration inputs are re-scored with the current model, so stale scores from an early model don't linger.
- **Escalation is always safe.** A singleton set that disagrees with the model's own argmax is escalated ("inconsistent").

### Pick α above your oracle's noise floor

If the oracle disagrees with *itself* x% of the time, no system can promise less than about x% disagreement. With α near x, Kadı will (correctly) escalate almost everything. In the demo the oracle is 2% noisy: α = 3% kept only about 46% of decisions local, while α = 5% keeps about 93% local with 97% audited agreement.

**The guarantee is relative to your oracle.** Kadı promises to agree with the oracle; if the oracle is wrong, Kadı copies its mistakes. The bound is marginal, not per input, and holds exactly only under exchangeability. ACI, audits and the drift breaker are there because real traffic isn't exchangeable.

## Demo numbers (simulated, reproducible)

The demo runs 6,000 tickets through 2 questions, with a simulated oracle that is 98% accurate and costs $0.012 per call. The script includes an oracle outage and a language drift halfway through.

| | route_ticket (α 5%, marginal) | is_urgent (α 5%, per-label) |
|---|---|---|
| Decided locally | 93.4% | 42.6% |
| Audited agreement with oracle | 97.3% (216/222) | 95.3% (81/85) |
| Fallbacks during the outage | 14 (flagged) | 67 (flagged) |
| Spend vs. frontier-only | $7.26 vs. $72 | $41.56 vs. $72 |

Per-label guarantees cost coverage: every label needs its own evidence. Use them where a rare label matters.

## Security review

An independent adversarial review found 11 issues. All 11 are fixed, each with a regression test in `tests/test_production.py::TestSecurityRegressions`:

- CSRF and DNS rebinding on tokenless loopback
- shadow mode never leaving probation
- unbounded features from random 100k-character inputs
- negative `Content-Length` bypassing the body cap
- unredacted context sent to the oracle
- redaction merging different inputs into one memory key
- rate-limiter rebuilds under many source addresses
- audits returning a label the oracle had just contradicted
- prompt-injection delimiting
- the HMAC key co-located with the hashes (now a warning; set `KADI_SECRET`)
- memory hits using up probation

## Getting it into a real project, risk-free

**1. Replay your history (5 minutes, no traffic touched).** Export past decisions as JSONL `{"text": ..., "label": ...}` (for example, past LLM outputs or human labels):

```bash
kadi replay history.jsonl --cost 0.012 --alphas 0.01,0.03,0.05,0.1
```
```
 target α   local   error local err  steady local  steady err       cost  vs frontier
     1.0%   92.0%   0.00%     0.00%         97.6%       0.00% $     4.81         -92%
     3.0%   95.1%   0.00%     0.00%         98.6%       0.00% $     2.94         -95%
```
<sub>Example output on the bundled synthetic ticket generator. Synthetic data is far easier than yours, so expect real error to be higher and local rates lower.</sub>

**2. Shadow mode (1–2 weeks).** Deploy with `mode = "shadow"`. Your app keeps getting oracle answers, and the dashboard shows "would decide X% locally, Y% agreement".

**3. Go live, question by question.** Flip low-risk questions to `live` with α 3–5%. For high-stakes ones (money, legal, health), keep α ≤ 1%, use `conditional = true`, or let Kadı only pre-screen.

## Quick start

```bash
pip install .                    # Python ≥ 3.11, no dependencies
python examples/demo.py          # simulated support desk with an oracle outage and a language drift
python -m unittest discover -s tests   # 65 tests: guarantee, privacy, security regressions, API
open http://127.0.0.1:8765
```

### As a service (any language)

```bash
kadi init                        # writes kadi.toml
export KADI_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
export ANTHROPIC_API_KEY=...
kadi serve --config kadi.toml    # or: docker compose up -d
```

```bash
curl -s localhost:8765/api/decide -H "authorization: Bearer $KADI_TOKEN" \
  -H "content-type: application/json" \
  -d '{"question":"route_ticket","text":"I was charged twice this month"}'
# {"label":"billing","tier":"reflex","reason":"confident","prediction_set":["billing"],"cost_usd":0.0,...}
```

TypeScript / Next.js ([`clients/typescript`](clients/typescript)):

```ts
import { KadiClient, defineQuestion } from "@kadi/client";
const kadi = new KadiClient({ baseUrl: process.env.KADI_URL!, token: process.env.KADI_TOKEN });
const route = defineQuestion("route_ticket", ["billing", "bug", "feature_request", "account", "spam"] as const);
const d = await kadi.decide(route, ticketText);   // d.label is typed as the union of options
```

### In-process (Python)

```python
from kadi import Kadi, Choice, Binary, AnthropicOracle

kadi = Kadi(AnthropicOracle(model="claude-opus-5-5", input_usd_per_mtok=..., output_usd_per_mtok=...),
            db="kadi.db", audit_rate=0.05, on_oracle_error="best_guess")

route  = Choice("route_ticket", ["billing", "bug", "feature_request", "account", "spam"],
                "Which team should handle this ticket?", target_error=0.03)
urgent = Binary("is_urgent", "Does this need a human within the hour?", target_error=0.02, conditional=True)

d = kadi.decide(route, ticket_text)
d.label, d.tier, d.reason, d.prediction_set, d.flagged

kadi.teach(route, text, "billing")           # human-reviewed gold labels
```

Oracles: `AnthropicOracle`, `OpenAICompatibleOracle` (OpenAI, vLLM, Ollama, llama.cpp, LM Studio), and `FunctionOracle` (rules, a human review queue, an existing classifier).

## HTTP API

| Route | |
|---|---|
| `POST /api/decide` | `{question, text, context?}` → decision |
| `POST /api/decide/batch` | `{items: [...]}` (≤ 100) → `{results}` |
| `POST /api/teach` | `{question, text, label, context?}` → gold label |
| `GET /api/questions` | registered questions |
| `GET /api/summary` · `/api/timeline` · `/api/feed` | dashboard data (`?window=seconds`) |
| `GET /metrics` | Prometheus |
| `GET /healthz` | unauthenticated liveness |

## Divan: the dashboard

The dashboard shows:

- money saved compared with sending everything to the frontier model
- the share of decisions made locally
- **verified** agreement from random audits
- latency for local and oracle decisions
- who decided over time, including fallbacks
- cumulative spend
- one row per question ("court"), with its mode, the reasons for escalation, target vs. live α, realized miscoverage, audit agreement, and probation status
- shadow projections
- drift alerts
- a live docket of decisions with their reasons

The page holds no data. On a protected instance it asks for the token, which is kept only in session storage.

## Layout

```
kadi/engine.py     cascade, audits, shadow mode, drift breaker, fallback, persistence
kadi/conformal.py  adaptive (ACI) and Mondrian conformal prediction
kadi/learner.py    online softmax regression (AdaGrad, sparse) + novelty score
kadi/features.py   deterministic hashing featurizer (word + char n-grams)
kadi/redact.py     PII / secret redaction with checksum validation
kadi/oracles.py    Anthropic / OpenAI-compatible / function oracles
kadi/server.py     hardened HTTP API + Divan + Prometheus
kadi/config.py     kadi.toml loader (secrets only via env vars)
kadi/cli.py        init · serve · replay · dashboard · stats · prune
kadi/store.py      SQLite ledger (WAL), schema migrations
clients/typescript typed client with retries/backoff
```

## Roadmap

- Pluggable reflex models: multilingual sentence embeddings (ONNX), k-NN, small fine-tuned LMs
- Postgres ledger and shared state for multi-instance deployments
- Multi-oracle juries (escalate to a second model on disagreement)
- Budget-aware α (spend cap per question per day)
- OpenTelemetry traces

License: Apache-2.0.
