"""Bitácora del agente FX en SQLite: solo anexar (F15-017 D). Tablas: journal (todo lo que pasa, con timestamps
UTC), intents (webhooks de TradingView, idempotentes por id) y kv (estado del gobernador para sobrevivir reinicios).
Nunca guarda tokens ni URLs con credenciales."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL,
  sym TEXT, ref TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS intents (id TEXT PRIMARY KEY, ts REAL NOT NULL, ip TEXT, body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new', result TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, ts REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


class Store:
    def __init__(self, path: str):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def log(self, kind: str, data: dict, sym: str | None = None, ref: str | None = None) -> None:
        with self._lock:
            self.db.execute("INSERT INTO journal (ts, kind, sym, ref, data) VALUES (?,?,?,?,?)",
                            (time.time(), kind, sym, ref, json.dumps(data, default=str, ensure_ascii=False)))

    def journal(self, kind: str | None = None, limit: int = 200) -> list[dict]:
        q = "SELECT ts, kind, sym, ref, data FROM journal"
        args: tuple = ()
        if kind:
            q += " WHERE kind = ?"
            args = (kind,)
        q += " ORDER BY id DESC LIMIT ?"
        rows = self.db.execute(q, args + (limit,)).fetchall()
        return [{"ts": r[0], "kind": r[1], "sym": r[2], "ref": r[3], **json.loads(r[4])} for r in rows]

    def put_intent(self, iid: str, body: dict, ip: str | None) -> bool:
        """True si es nuevo; False si ya existía (idempotencia: TradingView puede reintentar)."""
        with self._lock:
            try:
                self.db.execute("INSERT INTO intents (id, ts, ip, body) VALUES (?,?,?,?)",
                                (iid, time.time(), ip, json.dumps(body, ensure_ascii=False)))
                return True
            except sqlite3.IntegrityError:
                return False

    def pending_intents(self) -> list[dict]:
        rows = self.db.execute("SELECT id, ts, body FROM intents WHERE status = 'new' ORDER BY ts").fetchall()
        return [{"id": r[0], "ts": r[1], **json.loads(r[2])} for r in rows]

    def done_intent(self, iid: str, result: str) -> None:
        with self._lock:
            self.db.execute("UPDATE intents SET status = 'done', result = ? WHERE id = ?", (result, iid))

    def set(self, k: str, v) -> None:
        with self._lock:
            self.db.execute("INSERT INTO kv (k, v, ts) VALUES (?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, "
                            "ts=excluded.ts", (k, json.dumps(v, default=str), time.time()))

    def get(self, k: str, default=None):
        r = self.db.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
        return json.loads(r[0]) if r else default
