from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


class Store:
    """Small SQLite state/event store safe for local dashboard threads."""

    def __init__(self, path: str | Path = ".caos/caos.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
        )
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self.conn.commit()

    def set_json(self, key: str, value) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self.conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                (key, payload),
            )
            self.conn.commit()

    def get_json(self, key: str, default=None):
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM kv WHERE key=?",
                (key,),
            ).fetchone()
        return default if row is None else json.loads(row[0])

    def event(self, kind: str, payload) -> None:
        encoded = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            self.conn.execute(
                "INSERT INTO events(kind,payload) VALUES(?,?)",
                (kind, encoded),
            )
            self.conn.commit()

    def recent_events(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT id,kind,payload,created_at "
                "FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "kind": r[1],
                "payload": json.loads(r[2]),
                "created_at": r[3],
            }
            for r in rows
        ]

    def close(self) -> None:
        with self._lock:
            self.conn.close()
