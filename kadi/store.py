"""SQLite ledger: every decision is auditable, every model state is durable."""
from __future__ import annotations

import json
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
  latency_ms REAL NOT NULL DEFAULT 0
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

_ADDED_COLUMNS = {"reason": "TEXT", "shadow_label": "TEXT", "flagged": "INTEGER NOT NULL DEFAULT 0"}


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

    def _migrate(self) -> None:
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(decisions)")}
        if cols:  # databases created by v0.1
            for c, typ in _ADDED_COLUMNS.items():
                if c not in cols:
                    self.db.execute(f"ALTER TABLE decisions ADD COLUMN {c} {typ}")
        self.db.executescript(SCHEMA)

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
        cols = ",".join(row)
        qs = ",".join("?" * len(row))
        with self.lock:
            cur = self.db.execute(f"INSERT INTO decisions ({cols}) VALUES ({qs})", tuple(row.values()))
            return cur.lastrowid

    def prune(self, older_than_days: float) -> int:
        cutoff = time.time() - older_than_days * 86400
        with self.lock:
            return self.db.execute("DELETE FROM decisions WHERE ts < ?", (cutoff,)).rowcount

    # ----------------------------------------------------------- models
    def save_model(self, question: str, spec: dict, state: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO models VALUES (?,?,?,?)",
                            (question, json.dumps(spec), json.dumps(state), time.time()))

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
