/**
 * @kadi/client: a tiny, dependency-free client for the Kadı HTTP API.
 */

export type Tier = "memory" | "reflex" | "oracle" | "fallback";
export type Context = Record<string, unknown>;

export interface Decision<L extends string = string> {
  id: number;
  question: string;
  label: L;
  tier: Tier;
  confidence: number;
  prediction_set: L[];
  cost_usd: number;
  latency_ms: number;
  reason: string;
  flagged: boolean;
}

export interface DecideItem {
  question: string;
  text: string;
  context?: Context;
}

export type BatchResult = Decision | { error: string };

export interface QuestionInfo {
  name: string;
  options: string[];
  mode: "live" | "shadow";
  target_error: number;
  conditional: boolean;
}

/** A question handle whose labels are known at compile time. */
export interface QuestionDef<O extends readonly string[]> {
  readonly name: string;
  readonly options: O;
}

export function defineQuestion<const O extends readonly string[]>(
  name: string,
  options: O,
): QuestionDef<O> {
  return { name, options };
}

export interface KadiClientOptions {
  baseUrl: string;
  token?: string;
  timeoutMs?: number;
  retries?: number;
  fetch?: typeof fetch;
}

export class KadiError extends Error {
  override readonly name = "KadiError";
  constructor(
    /** HTTP status, or 0 for network errors and timeouts. */
    readonly status: number,
    message: string,
    readonly retryAfterMs?: number,
  ) {
    super(message);
  }
}

const RETRYABLE = new Set([429, 502, 503]);
const BATCH_LIMIT = 100;

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function parseRetryAfter(h: string | null): number | undefined {
  if (!h) return undefined;
  const secs = Number(h);
  if (Number.isFinite(secs)) return Math.max(0, secs * 1000);
  const at = Date.parse(h);
  return Number.isNaN(at) ? undefined : Math.max(0, at - Date.now());
}

type Q = string | QuestionDef<readonly string[]>;
const qname = (q: Q) => (typeof q === "string" ? q : q.name);

export class KadiClient {
  readonly #base: string;
  readonly #token?: string;
  readonly #timeoutMs: number;
  readonly #retries: number;
  readonly #fetch: typeof fetch;

  constructor({ baseUrl, token, timeoutMs = 10_000, retries = 2, fetch: f }: KadiClientOptions) {
    this.#base = baseUrl.replace(/\/+$/, "");
    this.#token = token;
    this.#timeoutMs = timeoutMs;
    this.#retries = retries;
    const impl = f ?? globalThis.fetch;
    if (!impl) throw new Error("No fetch implementation available; pass options.fetch");
    this.#fetch = impl.bind(globalThis);
  }

  decide<const O extends readonly string[]>(
    question: QuestionDef<O>,
    text: string,
    context?: Context,
  ): Promise<Decision<O[number]>>;
  decide(question: string, text: string, context?: Context): Promise<Decision>;
  decide(question: Q, text: string, context?: Context): Promise<Decision> {
    return this.#request("POST", "/api/decide", { question: qname(question), text, context });
  }

  async decideBatch(items: DecideItem[]): Promise<BatchResult[]> {
    if (items.length > BATCH_LIMIT) {
      throw new KadiError(400, `batch too large: ${items.length} > ${BATCH_LIMIT}`);
    }
    const res = await this.#request<{ results: BatchResult[] }>("POST", "/api/decide/batch", { items });
    return res.results;
  }

  async teach<const O extends readonly string[]>(
    question: QuestionDef<O> | string,
    text: string,
    label: O[number],
    context?: Context,
  ): Promise<void> {
    await this.#request("POST", "/api/teach", { question: qname(question), text, label, context });
  }

  questions(): Promise<QuestionInfo[]> {
    return this.#request("GET", "/api/questions");
  }

  async health(): Promise<boolean> {
    try {
      return (await this.#request<{ ok: boolean }>("GET", "/healthz")).ok === true;
    } catch {
      return false;
    }
  }

  async #request<T>(method: string, path: string, body?: unknown): Promise<T> {
    let attempt = 0;
    for (;;) {
      try {
        return await this.#once<T>(method, path, body);
      } catch (err) {
        const e = err instanceof KadiError ? err : new KadiError(0, String(err));
        const retryable = e.status === 0 || RETRYABLE.has(e.status);
        if (!retryable || attempt >= this.#retries) throw e;
        const backoff = 250 * 2 ** attempt;
        await sleep(e.retryAfterMs ?? backoff + Math.random() * backoff);
        attempt++;
      }
    }
  }

  async #once<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (this.#token) headers.Authorization = `Bearer ${this.#token}`;

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.#timeoutMs);
    let res: Response;
    try {
      res = await this.#fetch(this.#base + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: ctrl.signal,
      });
    } catch (err) {
      const msg = ctrl.signal.aborted ? `timeout after ${this.#timeoutMs} ms` : String(err);
      throw new KadiError(0, msg);
    } finally {
      clearTimeout(timer);
    }

    const raw = await res.text();
    let data: unknown;
    try {
      data = raw ? JSON.parse(raw) : undefined;
    } catch {
      data = undefined;
    }
    if (!res.ok) {
      const msg =
        data && typeof data === "object" && "error" in data ? String(data.error) : raw || res.statusText;
      throw new KadiError(res.status, msg, parseRetryAfter(res.headers.get("Retry-After")));
    }
    return data as T;
  }
}
