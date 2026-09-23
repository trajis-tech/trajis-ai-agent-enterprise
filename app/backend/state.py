from __future__ import annotations

import json
import threading
from functools import wraps
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS session_preferences (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    mode TEXT NOT NULL DEFAULT 'general' CHECK(mode IN ('general','plan','ask')),
    epoch INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
    content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_history (
    session_id TEXT PRIMARY KEY,
    history_json TEXT NOT NULL,
    pending_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS approval_outcomes (
    approval_id TEXT PRIMARY KEY,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    role TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id)
);
CREATE TABLE IF NOT EXISTS pending_approvals (
    approval_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    project_id TEXT,
    tool_call_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    args_json TEXT NOT NULL,
    display TEXT,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publish_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    workflow_file TEXT NOT NULL,
    workflow_hash TEXT NOT NULL,
    n8n_workflow_id TEXT,
    publish_call_id TEXT UNIQUE,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_locks (
    project_id TEXT PRIMARY KEY,
    holder TEXT NOT NULL,
    acquired_at TEXT NOT NULL
);
"""


def locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._mutex:
            return method(self, *args, **kwargs)
    return wrapped


class StateDB:
    def __init__(self, path: Path) -> None:
        self._mutex = threading.RLock()
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    @locked
    def mode_state(self, session_id: str) -> dict:
        row = self._conn.execute("SELECT mode,epoch FROM session_preferences WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else {"mode": "general", "epoch": 0}

    @locked
    def set_mode(self, session_id: str, mode: str) -> dict:
        if mode not in {"general", "plan", "ask"}:
            raise ValueError("不支援的對話模式")
        old = self.mode_state(session_id)
        if old["mode"] == mode:
            return old
        self._conn.execute("INSERT INTO session_preferences(session_id,mode,epoch) VALUES (?,?,?) ON CONFLICT(session_id) DO UPDATE SET mode=excluded.mode,epoch=excluded.epoch", (session_id, mode, old["epoch"] + 1))
        self._conn.execute("UPDATE pending_approvals SET status='denied' WHERE session_id=? AND status='pending'", (session_id,))
        self._conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id))
        self._conn.commit()
        return self.mode_state(session_id)

    @locked
    def plans(self, session_id: str) -> list[dict]:
        rows = self._conn.execute("SELECT id,content,created_at FROM plans WHERE session_id=? ORDER BY created_at DESC LIMIT 20", (session_id,)).fetchall()
        return [dict(row) for row in rows]

    @locked
    def save_plan(self, session_id: str, content: str) -> str:
        if not content.strip() or len(content) > 50000:
            raise ValueError("計畫內容需為 1–50000 字元")
        plan_id = str(uuid4())
        self._conn.execute("INSERT INTO plans VALUES (?,?,?,?)", (plan_id, session_id, content, _now()))
        self._conn.commit()
        return plan_id

    @locked
    def close(self) -> None:
        self._conn.close()

    @locked
    def ensure_session(self, session_id: str, project_id: str | None = None) -> str:
        now = _now()
        row = self._conn.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO sessions(id, project_id, created_at, updated_at) VALUES (?,?,?,?)",
                (session_id, project_id, now, now),
            )
        elif project_id:
            self._conn.execute(
                "UPDATE sessions SET project_id=?, updated_at=? WHERE id=?",
                (project_id, now, session_id),
            )
        self._conn.commit()
        return session_id

    @locked
    def append_message(self, session_id: str, role: str, payload: Any, turn_id: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO messages(session_id, turn_id, role, payload, created_at) VALUES (?,?,?,?,?)",
            (session_id, turn_id, role, json.dumps(payload, ensure_ascii=False), _now()),
        )
        self._conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id))
        self._conn.commit()
        return int(cur.lastrowid)

    @locked
    def messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, turn_id, role, payload, created_at FROM messages WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "id": row["id"],
                    "turn_id": row["turn_id"],
                    "role": row["role"],
                    "payload": json.loads(row["payload"]),
                    "created_at": row["created_at"],
                }
            )
        return out

    @locked
    def session(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    @locked
    def latest_session(self, project_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT id FROM sessions WHERE project_id=? ORDER BY updated_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        return row["id"] if row else None

    @locked
    def pending_for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT approval_id FROM pending_approvals WHERE session_id=? AND status='pending' ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self.get_pending(row["approval_id"]) for row in rows]

    @locked
    def save_agent_history(self, session_id: str, history: bytes, pending: list[str]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO agent_history VALUES (?,?,?)",
            (session_id, history.decode("utf-8"), json.dumps(pending)),
        )
        self._conn.commit()

    @locked
    def agent_history(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM agent_history WHERE session_id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    @locked
    def save_approval_outcome(self, approval_id: str, result: Any) -> None:
        self._conn.execute("INSERT OR REPLACE INTO approval_outcomes VALUES (?,?)",
                           (approval_id, json.dumps(result, ensure_ascii=False)))
        self._conn.commit()

    @locked
    def approval_outcome(self, approval_id: str) -> Any:
        row = self._conn.execute("SELECT result_json FROM approval_outcomes WHERE approval_id=?", (approval_id,)).fetchone()
        return json.loads(row["result_json"]) if row else None

    @locked
    def put_pending(self, record: dict[str, Any]) -> str:
        approval_id = record.get("approval_id") or str(uuid4())
        self._conn.execute(
            """INSERT INTO pending_approvals(
                approval_id, session_id, project_id, tool_call_id, tool_name,
                args_hash, args_json, display, expires_at, status, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                approval_id,
                record["session_id"],
                record.get("project_id"),
                record["tool_call_id"],
                record["tool_name"],
                record["args_hash"],
                json.dumps(record.get("args") or {}, ensure_ascii=False),
                record.get("display") or "",
                record["expires_at"],
                "pending",
                _now(),
            ),
        )
        self._conn.commit()
        return approval_id

    @locked
    def get_pending(self, approval_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM pending_approvals WHERE approval_id=?", (approval_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["args"] = json.loads(data.pop("args_json"))
        return data

    @locked
    def resolve_pending(self, approval_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE pending_approvals SET status=? WHERE approval_id=?",
            (status, approval_id),
        )
        self._conn.commit()

    @locked
    def add_publish(
        self,
        project_id: str,
        workflow_file: str,
        workflow_hash: str,
        action: str,
        n8n_workflow_id: str | None = None,
        publish_call_id: str | None = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO publish_records(
                project_id, workflow_file, workflow_hash, n8n_workflow_id,
                publish_call_id, action, created_at
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                project_id,
                workflow_file,
                workflow_hash,
                n8n_workflow_id,
                publish_call_id or str(uuid4()),
                action,
                _now(),
            ),
        )
        self._conn.commit()

    @locked
    def has_pending(self, session_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM pending_approvals WHERE session_id=? AND status='pending' LIMIT 1",
            (session_id,),
        ).fetchone()
        return row is not None

    @locked
    def last_publish(self, project_id: str, workflow_file: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """SELECT * FROM publish_records WHERE project_id=? AND workflow_file=?
               ORDER BY id DESC LIMIT 1""",
            (project_id, workflow_file),
        ).fetchone()
        return dict(row) if row else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
