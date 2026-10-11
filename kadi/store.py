"""SQLite ledger: every decision is auditable, every model state is durable."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  question TEXT NOT NULL,
  input_hash TEXT NOT NULL,     -- keyed HMAC, not a plain hash: inputs can't be dictionary-guessed
  preview TEXT,                 -- redacted, truncated; NULL when store_inputs is off
  label TEXT NOT NULL,
  tier TEXT NOT NULL,           -- memory | reflex | oracle | fallback
  reason TEXT,                  -- why this tier answered
  confidence REAL,
  set_size INTEGER,
  oracle_label TEXT,
  shadow_label TEXT,            -- shadow mode: what Kadı would have answered locally
  audited INTEGER NOT NULL DEFAULT 0,
  agreed INTEGER,
  flagged INTEGER NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0,
  latency_ms REAL NOT NULL DEFAULT 0,
  model_version INTEGER,        -- frozen model version that made a local decision (v0.6)
  chain_fmt INTEGER,            -- column set covered by row_hash (NULL/1: v0.3-v0.5, 2: + model_version)
  prev_hash TEXT,               -- tamper-evident chain: HMAC of the previous row
  row_hash TEXT                 -- HMAC(key, prev_hash | canonical row)
);
CREATE INDEX IF NOT EXISTS ix_dec_q ON decisions(question, id);
CREATE INDEX IF NOT EXISTS ix_dec_ts ON decisions(ts);
CREATE TABLE IF NOT EXISTS models (
  question TEXT PRIMARY KEY, spec TEXT NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS qstats (
  question TEXT PRIMARY KEY, stats TEXT NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, question TEXT NOT NULL,
  kind TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_ADDED_COLUMNS = {"reason": "TEXT", "shadow_label": "TEXT", "flagged": "INTEGER NOT NULL DEFAULT 0",
                  "prev_hash": "TEXT", "row_hash": "TEXT", "model_version": "INTEGER", "chain_fmt": "INTEGER"}

# Columns covered by the hash chain, in canonical order.
CHAINED = ("ts", "question", "input_hash", "preview", "label", "tier", "reason", "confidence", "set_size",
           "oracle_label", "shadow_label", "audited", "agreed", "flagged", "cost", "latency_ms")
CHAINED_V2 = CHAINED + ("model_version",)
CHAIN_FMT = 2
GENESIS = "0" * 64
_REAL = ("ts", "confidence", "cost", "latency_ms")
_INT = ("set_size", "audited", "agreed", "flagged", "model_version")


def derive_chain_key(secret: bytes) -> bytes:
    return hashlib.sha256(b"kadi-ledger-chain|" + secret).digest()


def _row_hash(key: bytes, prev: str, row: dict) -> str:
    """HMAC over the previous hash and the row's canonical columns. Rows written
    since v0.6 (chain_fmt 2) also cover model_version; older rows keep their
    original column set, so upgrading never invalidates an existing chain.
    Rewriting chain_fmt cannot hide an edit: the hash would no longer match."""
    if row.get("chain_fmt") == 2:
        canon = "v2|" + json.dumps([row[c] for c in CHAINED_V2], ensure_ascii=False, separators=(",", ":"))
    else:
        canon = json.dumps([row[c] for c in CHAINED], ensure_ascii=False, separators=(",", ":"))
    return hmac.new(key, (prev + "|" + canon).encode(), hashlib.sha256).hexdigest()


class Store:
    def __init__(self, path: str = "kadi.db"):
        self.path = path
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self._migrate()
        self.chain_key: bytes | None = None   # set by the engine; enables the hash chain
        self._head: str | None = None
        self._mem_snapshots: dict[str, bytes] = {}   # used when path == ":memory:"

    def _migrate(self) -> None:
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(decisions)")}
        if cols:  # databases created by v0.1
            for c, typ in _ADDED_COLUMNS.items():
                if c not in cols:
                    self.db.execute(f"ALTER TABLE decisions ADD COLUMN {c} {typ}")
        self.db.executescript(SCHEMA)
        # Rows with id <= chain_start predate the hash chain (v0.1/v0.2 databases).
        # Any later row without a hash is treated as tampering by verify().
        if not self.db.execute("SELECT 1 FROM meta WHERE key='chain_start_id'").fetchone():
            first = self.db.execute("SELECT MIN(id) m FROM decisions WHERE row_hash IS NOT NULL").fetchone()["m"]
            start = first - 1 if first is not None else \
                self.db.execute("SELECT COALESCE(MAX(id), 0) m FROM decisions").fetchone()["m"]
            self.db.execute("INSERT INTO meta VALUES ('chain_start_id', ?)", (str(start),))

    # ------------------------------------------------------------- meta
    def secret(self) -> bytes:
        """Per-database HMAC key, generated once. Override with KADI_SECRET."""
        with self.lock:
            r = self.db.execute("SELECT value FROM meta WHERE key='hmac_secret'").fetchone()
            if r:
                return bytes.fromhex(r["value"])
            key = secrets.token_bytes(32)
            self.db.execute("INSERT INTO meta VALUES ('hmac_secret', ?)", (key.hex(),))
            return key

    # -------------------------------------------------------- decisions
    def record(self, **row) -> int:
        missing = [c for c in CHAINED if c not in row]
        if missing:
            raise ValueError(f"record() missing columns {missing}")
        row.setdefault("model_version", None)
        row["chain_fmt"] = CHAIN_FMT
        for c in _REAL:  # canonical types: what SQLite hands back on read
            row[c] = None if row[c] is None else float(row[c])
        for c in _INT:
            row[c] = None if row[c] is None else int(row[c])
        with self.lock:
            if self.chain_key is not None:
                prev = self._chain_head()
                row["prev_hash"] = prev
                row["row_hash"] = self._head = _row_hash(self.chain_key, prev, row)
            cols = ",".join(row)
            qs = ",".join("?" * len(row))
            cur = self.db.execute(f"INSERT INTO decisions ({cols}) VALUES ({qs})", tuple(row.values()))
            return cur.lastrowid

    def _chain_head(self) -> str:
        if self._head is None:
            r = self.db.execute("SELECT row_hash FROM decisions WHERE row_hash IS NOT NULL "
                                "ORDER BY id DESC LIMIT 1").fetchone()
            a = self.db.execute("SELECT value FROM meta WHERE key='chain_anchor'").fetchone()
            self._head = r["row_hash"] if r else (a["value"] if a else GENESIS)
        return self._head

    def prune(self, older_than_days: float) -> int:
        """Delete old rows. The hash of the last deleted chained row becomes the
        anchor the first surviving row must link to, so pruning stays verifiable."""
        cutoff = time.time() - older_than_days * 86400
        with self.lock:
            # Delete a contiguous id-prefix (every row before the first one that is
            # still young), never an id-gap: with a non-monotonic clock, deleting by
            # ts alone would cut the chain in the middle. Retention errs on keeping.
            first_keep = self.db.execute("SELECT MIN(id) m FROM decisions WHERE ts >= ?", (cutoff,)).fetchone()["m"]
            cut = (first_keep - 1) if first_keep is not None else \
                self.db.execute("SELECT COALESCE(MAX(id), 0) m FROM decisions").fetchone()["m"]
            if cut <= 0:
                return 0
            last = self.db.execute("SELECT row_hash FROM decisions WHERE id <= ? AND row_hash IS NOT NULL "
                                   "ORDER BY id DESC LIMIT 1", (cut,)).fetchone()
            if last:
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('chain_anchor', ?)", (last["row_hash"],))
            return self.db.execute("DELETE FROM decisions WHERE id <= ?", (cut,)).rowcount

    def verify(self, key: bytes) -> dict:
        """Re-derive the whole chain. Detects edited, deleted, inserted or
        re-ordered rows, as long as the attacker does not hold the key."""
        with self.lock:
            a = self.db.execute("SELECT value FROM meta WHERE key='chain_anchor'").fetchone()
            prev = a["value"] if a else GENESIS
            start = int(self.db.execute("SELECT value FROM meta WHERE key='chain_start_id'").fetchone()["value"])
            cols = ", ".join(("id", "prev_hash", "row_hash", "chain_fmt") + CHAINED_V2)
            n = 0
            for r in self.db.execute(f"SELECT {cols} FROM decisions WHERE id > ? ORDER BY id", (start,)):
                r = dict(r)
                if r["row_hash"] is None:
                    return {"ok": False, "rows": n, "first_bad_id": r["id"],
                            "reason": "unchained row: inserted or stripped of its hash after the chain began"}
                if r["prev_hash"] != prev:
                    return {"ok": False, "rows": n, "first_bad_id": r["id"],
                            "reason": "broken link: a row before this one was deleted, inserted or altered"}
                if not hmac.compare_digest(_row_hash(key, prev, r), r["row_hash"]):
                    return {"ok": False, "rows": n, "first_bad_id": r["id"], "reason": "row content was altered"}
                prev = r["row_hash"]
                n += 1
            return {"ok": True, "rows": n, "head": prev}

    # ----------------------------------------------------------- models
    def save_model(self, question: str, spec: dict, state: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO models VALUES (?,?,?,?)",
                            (question, json.dumps(spec), json.dumps(state), time.time()))

    # ---------------------------------------------------- model snapshots
    # Large binary model state lives in side files next to the database (one
    # per court, written atomically) so that a checkpoint never holds the
    # SQLite write lock for long. Its SHA-256 is stored in `models`, so a
    # swapped or corrupted file is refused on load.
    def _snapshot_path(self, question: str) -> str:
        d = self.path + ".snapshots"
        os.makedirs(d, mode=0o700, exist_ok=True)
        return os.path.join(d, hashlib.sha256(question.encode()).hexdigest()[:32] + ".kadisnap")

    def save_snapshot(self, question: str, blob: bytes) -> str:
        sha = hashlib.sha256(blob).hexdigest()
        if self.path == ":memory:":
            self._mem_snapshots[question] = blob
            return sha
        path = self._snapshot_path(question)
        tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return sha

    def load_snapshot(self, question: str, sha256: str) -> bytes:
        if self.path == ":memory:":
            blob = self._mem_snapshots[question]
        else:
            with open(self._snapshot_path(question), "rb") as f:
                blob = f.read()
        if not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), sha256):
            raise ValueError("snapshot integrity check failed (file does not match the recorded SHA-256)")
        return blob

    def load_model(self, question: str) -> tuple[dict, dict] | None:
        with self.lock:
            r = self.db.execute("SELECT spec, state FROM models WHERE question=?", (question,)).fetchone()
        return (json.loads(r["spec"]), json.loads(r["state"])) if r else None

    def save_qstats(self, question: str, stats: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO qstats VALUES (?,?,?)",
                            (question, json.dumps(stats), time.time()))

    def record_alert(self, question: str, kind: str, detail: dict) -> None:
        with self.lock:
            self.db.execute("INSERT INTO alerts (ts, question, kind, detail) VALUES (?,?,?,?)",
                            (time.time(), question, kind, json.dumps(detail)))

    def query(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def close(self) -> None:
        with self.lock:
            self.db.close()
