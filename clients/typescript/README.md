# @kadi/client

A small TypeScript client for the [Kadı](../../README.md) HTTP API, with no dependencies. It runs anywhere that has a global `fetch`: Node 18+, Deno, Bun, and browsers.

```ts
import { KadiClient, defineQuestion, KadiError } from "@kadi/client";

const kadi = new KadiClient({ baseUrl: "http://127.0.0.1:8765", token: process.env.KADI_TOKEN });

const route = defineQuestion("route_ticket", ["billing", "bug", "feature_request", "account", "spam"]);

const d = await kadi.decide(route, ticketText);
d.label;          // typed as "billing" | "bug" | "feature_request" | "account" | "spam"
d.tier;           // "memory" | "reflex" | "oracle" | "fallback"

await kadi.teach(route, ticketText, "billing");   // label is type-checked against the options

const results = await kadi.decideBatch([{ question: "route_ticket", text: "..." }]); // max 100
await kadi.questions();   // [{ name, options, mode, target_error, conditional }]
await kadi.health();      // true | false
```

`defineQuestion` only declares types on the client. The question itself must also be registered in the server's `kadi.toml`.

## Options

| option      | default         | notes                                                   |
|-------------|-----------------|---------------------------------------------------------|
| `baseUrl`   | (required)      | e.g. `http://127.0.0.1:8765`                            |
| `token`     | none            | sent as `Authorization: Bearer <token>`                 |
| `timeoutMs` | `10000`         | per attempt, enforced with `AbortController`            |
| `retries`   | `2`             | extra attempts on 429/502/503 and network errors        |
| `fetch`     | global `fetch`  | inject a custom implementation (tests, proxies)         |

Retries use exponential backoff with jitter. When the server sends `Retry-After`, the client waits that long instead. Other errors are not retried.

## Errors

Any failure throws `KadiError`, which has `status` (the HTTP status, or `0` for a network error or timeout) and `message` (the server's `error` field when it has one).

```ts
try { await kadi.decide("nope", "x"); }
catch (e) { if (e instanceof KadiError && e.status === 404) { /* unknown question */ } }
```

## Build

```bash
npm install && npm run build   # emits dist/ (ESM + .d.ts)
```
