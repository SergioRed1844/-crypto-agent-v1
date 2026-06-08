"""
store.py — Durable state for CryptoAgent (SQLite, stdlib only).

Replaces the in-memory globals that were lost on every Railway redeploy/cold-start.
The DB path is configurable via DATA_DIR so it can point to a mounted Railway volume
for persistence across redeploys. Without a volume it still survives process restarts
within the same deployment.

Design: the server keeps its in-memory globals as a cache for speed, but every
mutation is mirrored here so state can be rebuilt on startup.
"""
import os
import json
import sqlite3
import threading
from datetime import datetime, timezone

DATA_DIR = os.environ.get("DATA_DIR", ".")
DB_PATH = os.path.join(DATA_DIR, "cryptoagent_state.db")

_lock = threading.Lock()
_conn = None


def _connect():
    global _conn
    if _conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def init():
    """Create tables if they don't exist. Idempotent."""
    with _lock:
        c = _connect()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS trades (
                trade_id   TEXT PRIMARY KEY,
                data       TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS positions (
                trade_id TEXT PRIMARY KEY,
                data     TEXT
            );
            CREATE TABLE IF NOT EXISTS seen (
                hash TEXT PRIMARY KEY,
                ts   TEXT
            );
            """
        )
        c.commit()


# ── key/value (counters, pnl, satellite_pct, pnl window markers) ──────────────
def set_kv(key, value):
    with _lock:
        c = _connect()
        c.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        c.commit()


def get_kv(key, default=None):
    with _lock:
        c = _connect()
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return default


# ── trades (append-only log; updated on close) ────────────────────────────────
def upsert_trade(record):
    tid = record.get("trade_id")
    if not tid:
        return
    with _lock:
        c = _connect()
        c.execute(
            "INSERT INTO trades(trade_id, data, created_at) VALUES(?, ?, ?) "
            "ON CONFLICT(trade_id) DO UPDATE SET data=excluded.data",
            (tid, json.dumps(record), record.get("timestamp", datetime.now(timezone.utc).isoformat())),
        )
        c.commit()


def all_trades():
    with _lock:
        c = _connect()
        rows = c.execute("SELECT data FROM trades ORDER BY created_at ASC").fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["data"]))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


# ── open positions ────────────────────────────────────────────────────────────
def upsert_position(pos):
    tid = pos.get("trade_id")
    if not tid:
        return
    with _lock:
        c = _connect()
        c.execute(
            "INSERT INTO positions(trade_id, data) VALUES(?, ?) "
            "ON CONFLICT(trade_id) DO UPDATE SET data=excluded.data",
            (tid, json.dumps(pos)),
        )
        c.commit()


def delete_position(trade_id):
    with _lock:
        c = _connect()
        c.execute("DELETE FROM positions WHERE trade_id=?", (trade_id,))
        c.commit()


def all_positions():
    with _lock:
        c = _connect()
        rows = c.execute("SELECT data FROM positions").fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r["data"]))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


# ── seen signal hashes (dedup) ────────────────────────────────────────────────
def add_seen(sig_hash):
    with _lock:
        c = _connect()
        c.execute(
            "INSERT OR IGNORE INTO seen(hash, ts) VALUES(?, ?)",
            (sig_hash, datetime.now(timezone.utc).isoformat()),
        )
        c.commit()


def has_seen(sig_hash):
    with _lock:
        c = _connect()
        row = c.execute("SELECT 1 FROM seen WHERE hash=?", (sig_hash,)).fetchone()
    return row is not None


def prune_seen(keep=500):
    """Keep only the most recent `keep` hashes to bound table growth."""
    with _lock:
        c = _connect()
        c.execute(
            "DELETE FROM seen WHERE hash NOT IN "
            "(SELECT hash FROM seen ORDER BY ts DESC LIMIT ?)",
            (keep,),
        )
        c.commit()
