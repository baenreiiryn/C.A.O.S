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
                CREATE TABLE IF NOT EXISTS execution_intents (
                    intent_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    broker_order_id TEXT,
                    broker_order_link_id TEXT,
                    reconciliation_status TEXT,
                    reconciliation_payload TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(venue, environment, plan_id)
                );
                CREATE INDEX IF NOT EXISTS idx_execution_intents_status
                    ON execution_intents(status);
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

    @staticmethod
    def _execution_intent_row(row) -> dict | None:
        if row is None:
            return None
        return {
            "intent_id": row[0],
            "plan_id": row[1],
            "venue": row[2],
            "environment": row[3],
            "symbol": row[4],
            "payload": json.loads(row[5]),
            "payload_hash": row[6],
            "status": row[7],
            "broker_order_id": row[8],
            "broker_order_link_id": row[9],
            "reconciliation_status": row[10],
            "reconciliation_payload": (
                json.loads(row[11])
                if row[11] is not None
                else None
            ),
            "last_error": row[12],
            "created_at": row[13],
            "updated_at": row[14],
        }

    def prepare_execution_intent(
        self,
        *,
        intent_id: str,
        plan_id: str,
        venue: str,
        environment: str,
        symbol: str,
        payload: dict,
        payload_hash: str,
    ) -> dict:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO execution_intents("
                "intent_id,plan_id,venue,environment,symbol,"
                "payload,payload_hash,status"
                ") VALUES(?,?,?,?,?,?,?,'prepared')",
                (
                    intent_id,
                    plan_id,
                    venue,
                    environment,
                    symbol.upper(),
                    encoded,
                    payload_hash,
                ),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT intent_id,plan_id,venue,environment,symbol,"
                "payload,payload_hash,status,broker_order_id,"
                "broker_order_link_id,reconciliation_status,"
                "reconciliation_payload,last_error,created_at,updated_at "
                "FROM execution_intents "
                "WHERE venue=? AND environment=? AND plan_id=?",
                (venue, environment, plan_id),
            ).fetchone()
        result = self._execution_intent_row(row)
        assert result is not None
        return result

    def get_execution_intent(
        self,
        intent_id: str,
    ) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT intent_id,plan_id,venue,environment,symbol,"
                "payload,payload_hash,status,broker_order_id,"
                "broker_order_link_id,reconciliation_status,"
                "reconciliation_payload,last_error,created_at,updated_at "
                "FROM execution_intents WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
        return self._execution_intent_row(row)

    def list_execution_intents(
        self,
        *,
        limit: int = 100,
        statuses: tuple[str, ...] | None = None,
        venue: str | None = None,
        environment: str | None = None,
    ) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        query = (
            "SELECT intent_id,plan_id,venue,environment,symbol,"
            "payload,payload_hash,status,broker_order_id,"
            "broker_order_link_id,reconciliation_status,"
            "reconciliation_payload,last_error,created_at,updated_at "
            "FROM execution_intents"
        )
        clauses: list[str] = []
        params: list = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)
        if venue is not None:
            clauses.append("venue=?")
            params.append(str(venue))
        if environment is not None:
            clauses.append("environment=?")
            params.append(str(environment))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, intent_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(
                query,
                tuple(params),
            ).fetchall()
        return [
            self._execution_intent_row(row)
            for row in rows
        ]

    def transition_execution_intent(
        self,
        intent_id: str,
        *,
        from_statuses: tuple[str, ...],
        to_status: str,
        broker_order_id: str | None = None,
        broker_order_link_id: str | None = None,
        reconciliation_status: str | None = None,
        reconciliation_payload: dict | None = None,
        last_error: str | None = None,
    ) -> bool:
        if not from_statuses:
            raise ValueError("from_statuses_required")
        placeholders = ",".join("?" for _ in from_statuses)
        encoded_reconciliation = (
            json.dumps(
                reconciliation_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if reconciliation_payload is not None
            else None
        )
        params = [
            to_status,
            broker_order_id,
            broker_order_link_id,
            reconciliation_status,
            encoded_reconciliation,
            last_error,
            intent_id,
            *from_statuses,
        ]
        with self._lock:
            cur = self.conn.execute(
                "UPDATE execution_intents SET "
                "status=?,"
                "broker_order_id=COALESCE(?,broker_order_id),"
                "broker_order_link_id=COALESCE(?,broker_order_link_id),"
                "reconciliation_status=?,"
                "reconciliation_payload=?,"
                "last_error=?,"
                "updated_at=CURRENT_TIMESTAMP "
                f"WHERE intent_id=? AND status IN ({placeholders})",
                tuple(params),
            )
            self.conn.commit()
            return cur.rowcount == 1

    def execution_intent_counts(
        self,
        *,
        venue: str | None = None,
        environment: str | None = None,
    ) -> dict[str, int]:
        query = (
            "SELECT status,COUNT(*) FROM execution_intents"
        )
        clauses: list[str] = []
        params: list[str] = []
        if venue is not None:
            clauses.append("venue=?")
            params.append(str(venue))
        if environment is not None:
            clauses.append("environment=?")
            params.append(str(environment))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " GROUP BY status"
        with self._lock:
            rows = self.conn.execute(
                query,
                tuple(params),
            ).fetchall()
        return {
            str(status): int(count)
            for status, count in rows
        }

    def close(self) -> None:
        with self._lock:
            self.conn.close()
