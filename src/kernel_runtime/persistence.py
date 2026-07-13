from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from .errors import RuntimeFailure


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository:
    """Runtime state and business data are physically and logically separated."""

    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.resource_handlers: dict[tuple[str, str], Any] = {}
        self._schema()

    def _schema(self) -> None:
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runtime_tasks(
          task_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, input TEXT NOT NULL,
          lifecycle TEXT NOT NULL, current_stage TEXT NOT NULL,
          identity_json TEXT NOT NULL, environment_json TEXT NOT NULL,
          attempt_no INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS business_store(
          task_id TEXT NOT NULL, field_name TEXT NOT NULL, value_json TEXT NOT NULL,
          schema_version TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(task_id, field_name)
        );
        CREATE TABLE IF NOT EXISTS runtime_audit(
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, event TEXT NOT NULL,
          stage TEXT, details_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS business_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, application_id TEXT NOT NULL,
          stage TEXT NOT NULL, module_id TEXT NOT NULL, status TEXT NOT NULL,
          event TEXT NOT NULL, error_code TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS external_resources(
          application_id TEXT NOT NULL, resource_id TEXT NOT NULL, value_json TEXT NOT NULL,
          PRIMARY KEY(application_id, resource_id)
        );
        CREATE TABLE IF NOT EXISTS human_handoffs(
          handoff_id TEXT PRIMARY KEY, task_id TEXT, reason_code TEXT NOT NULL,
          details_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS security_audit(
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, event TEXT NOT NULL,
          details_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deliveries(
          delivery_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, recipient TEXT NOT NULL,
          content_digest TEXT NOT NULL, content TEXT NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
          status TEXT NOT NULL, approver TEXT, provider_message_id TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_messages(
          message_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, user_id TEXT NOT NULL,
          role TEXT NOT NULL, content TEXT NOT NULL, message_timestamp TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS history_snapshots(
          task_id TEXT NOT NULL, position INTEGER NOT NULL, message_id TEXT NOT NULL,
          role TEXT NOT NULL, content TEXT NOT NULL, message_timestamp TEXT NOT NULL,
          PRIMARY KEY(task_id, position)
        );
        """)
        self.db.commit()

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                yield
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def create_task(self, task_id: str, application_id: str, task_input: str,
                    identity: dict[str, str], environment: dict[str, str], stage: str) -> None:
        ts = now()
        with self.transaction():
            self.db.execute("INSERT INTO runtime_tasks VALUES(?,?,?,?,?,?,?,?,?,?)", (
                task_id, application_id, task_input, "RUNNING", stage,
                json.dumps(identity, ensure_ascii=False), json.dumps(environment, ensure_ascii=False),
                1, ts, ts))
            self._audit(task_id, "TASK_CREATED", stage, {"application_id": application_id})

    def state(self, task_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute("SELECT * FROM runtime_tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            raise RuntimeFailure("TASK_NOT_FOUND", "Task not found")
        return dict(row)

    def business(self, task_id: str) -> dict[str, Any]:
        with self.lock:
            rows = list(self.db.execute("SELECT field_name,value_json FROM business_store WHERE task_id=?", (task_id,)))
        return {r["field_name"]: json.loads(r["value_json"]) for r in rows}

    def commit_stage(self, *, task_id: str, application_id: str, expected_stage: str,
                     module_id: str, result: Any, allowed_fields: tuple[str, ...],
                     next_stage: str, completed_stage: str, increment_attempt: bool = False) -> None:
        invalid = set(result.output) - set(allowed_fields)
        if invalid:
            raise RuntimeFailure("WRITE_NOT_ALLOWED", f"Unauthorized fields: {sorted(invalid)}")
        with self.transaction():
            state = self.state(task_id)
            if state["lifecycle"] != "RUNNING" or state["current_stage"] != expected_stage:
                raise RuntimeFailure("STALE_RESULT", "Stage changed or task already closed")
            self.db.execute(
                "INSERT INTO business_log(task_id,application_id,stage,module_id,status,event,error_code,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (task_id, application_id, expected_stage, module_id, result.status,
                 result.business_event, result.error_code, now()))
            for key, value in result.output.items():
                self.db.execute(
                    "INSERT OR REPLACE INTO business_store VALUES(?,?,?,?,?)",
                    (task_id, key, json.dumps(value, ensure_ascii=False), "1", now()))
            lifecycle = "FINISHED" if next_stage == completed_stage else "RUNNING"
            attempt = state["attempt_no"] + (1 if increment_attempt else 0)
            self.db.execute("UPDATE runtime_tasks SET current_stage=?,lifecycle=?,attempt_no=?,updated_at=? WHERE task_id=?",
                            (next_stage, lifecycle, attempt, now(), task_id))
            self._audit(task_id, "STAGE_COMMITTED", expected_stage,
                        {"module_id": module_id, "next_stage": next_stage, "fields": sorted(result.output)})

    def quality_recovery_count(self, task_id: str) -> int:
        with self.lock:
            return self.db.execute(
                "SELECT COUNT(*) AS n FROM runtime_audit WHERE task_id=? AND event='QUALITY_RECOVERY'", (task_id,)
            ).fetchone()["n"]

    def record_quality_recovery(self, task_id: str, target_stage: str, issues: list[dict[str, Any]]) -> None:
        with self.transaction():
            self._audit(task_id, "QUALITY_RECOVERY", "QUALITY_CHECKING",
                        {"target_stage": target_stage, "issues": issues})

    def begin_attempt(self, task_id: str, stage: str) -> int:
        with self.transaction():
            state = self.state(task_id)
            attempt = state["attempt_no"] + 1
            self.db.execute("UPDATE runtime_tasks SET attempt_no=?,updated_at=? WHERE task_id=?", (attempt, now(), task_id))
            self._audit(task_id, "ATTEMPT_STARTED", stage, {"attempt_no": attempt})
            return attempt

    def fail(self, task_id: str, expected_stage: str, failure_stage: str, code: str) -> None:
        with self.transaction():
            state = self.state(task_id)
            if state["lifecycle"] != "RUNNING" or state["current_stage"] != expected_stage:
                return
            self.db.execute("UPDATE runtime_tasks SET current_stage=?,lifecycle='FAILED',updated_at=? WHERE task_id=?",
                            (failure_stage, now(), task_id))
            self._audit(task_id, "STAGE_FAILED", expected_stage,
                        {"failure_stage": failure_stage, "error_code": code})

    def cancel_task(self, task_id: str, reason: str = "external_cancel") -> bool:
        with self.transaction():
            state = self.state(task_id)
            if state["lifecycle"] != "RUNNING":
                return False
            self.db.execute(
                "UPDATE runtime_tasks SET lifecycle='CANCELLED',updated_at=? WHERE task_id=?",
                (now(), task_id),
            )
            self._audit(task_id, "TASK_CANCELLED", state["current_stage"], {"reason": reason})
            return True

    def handoff(self, task_id: str | None, reason_code: str, details: dict[str, Any]) -> str:
        from uuid import uuid4
        handoff_id = f"handoff_{uuid4().hex}"
        with self.transaction():
            self.db.execute("INSERT INTO human_handoffs VALUES(?,?,?,?,?)",
                            (handoff_id, task_id, reason_code, json.dumps(details, ensure_ascii=False), now()))
            self.db.execute("INSERT INTO security_audit(task_id,event,details_json,created_at) VALUES(?,?,?,?)",
                            (task_id, "HUMAN_HANDOFF", json.dumps({"reason_code": reason_code}), now()))
        return handoff_id

    def security_event(self, task_id: str | None, event: str, details: dict[str, Any]) -> None:
        with self.transaction():
            self.db.execute("INSERT INTO security_audit(task_id,event,details_json,created_at) VALUES(?,?,?,?)",
                            (task_id, event, json.dumps(details, ensure_ascii=False), now()))

    def _audit(self, task_id: str, event: str, stage: str | None, details: dict[str, Any]) -> None:
        self.db.execute("INSERT INTO runtime_audit(task_id,event,stage,details_json,created_at) VALUES(?,?,?,?,?)",
                        (task_id, event, stage, json.dumps(details, ensure_ascii=False), now()))

    def seed_resource(self, application_id: str, resource_id: str, value: Any) -> None:
        with self.transaction():
            self.db.execute("INSERT OR REPLACE INTO external_resources VALUES(?,?,?)",
                            (application_id, resource_id, json.dumps(value, ensure_ascii=False)))

    def register_resource_handler(self, application_id: str, resource_id: str, handler: Any) -> None:
        self.resource_handlers[(application_id, resource_id)] = handler

    def resource(self, application_id: str, resource_id: str, task_id: str | None = None) -> Any:
        handler = self.resource_handlers.get((application_id, resource_id))
        if handler is not None:
            if task_id is None: raise RuntimeFailure("TASK_CONTEXT_REQUIRED", resource_id)
            from .provider_adapters import ResourceCall
            state = self.state(task_id)
            return handler.fetch(ResourceCall(task_id, application_id, resource_id,
                json.loads(state["identity_json"]), json.loads(state["environment_json"])))
        with self.lock:
            row = self.db.execute("SELECT value_json FROM external_resources WHERE application_id=? AND resource_id=?",
                                  (application_id, resource_id)).fetchone()
        if not row:
            raise RuntimeFailure("RESOURCE_NOT_FOUND", resource_id)
        return json.loads(row["value_json"])

    def snapshot(self, task_id: str) -> dict[str, Any]:
        with self.lock:
            state = self.state(task_id)
            audit = [dict(r) for r in self.db.execute(
                "SELECT event,stage,details_json,created_at FROM runtime_audit WHERE task_id=? ORDER BY id", (task_id,))]
            logs = [dict(r) for r in self.db.execute(
                "SELECT stage,module_id,status,event,error_code,created_at FROM business_log WHERE task_id=? ORDER BY id", (task_id,))]
        return {"runtime_state": state, "business_store": self.business(task_id),
                "runtime_audit": audit, "business_log": logs}

    def create_delivery(self, task_id: str, recipient: str, content_digest: str, content: str) -> str:
        from uuid import uuid4
        delivery_id = f"delivery_{uuid4().hex}"
        key = f"{task_id}:{recipient}:{content_digest}"
        with self.transaction():
            existing = self.db.execute("SELECT delivery_id FROM deliveries WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                return existing["delivery_id"]
            self.db.execute("INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (delivery_id, task_id, recipient, content_digest, content, key,
                             "APPROVAL_REQUIRED", None, None, now()))
            self._audit(task_id, "DELIVERY_CREATED", None, {"delivery_id": delivery_id, "content_digest": content_digest})
        return delivery_id

    def delivery(self, delivery_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.execute("SELECT * FROM deliveries WHERE delivery_id=?", (delivery_id,)).fetchone()
        if not row:
            raise RuntimeFailure("DELIVERY_NOT_FOUND", delivery_id)
        return dict(row)

    def approve_delivery(self, delivery_id: str, approver: str) -> None:
        with self.transaction():
            record = self.delivery(delivery_id)
            if record["status"] != "APPROVAL_REQUIRED":
                raise RuntimeFailure("INVALID_DELIVERY_STATE", record["status"])
            self.db.execute("UPDATE deliveries SET status='APPROVED',approver=? WHERE delivery_id=?", (approver, delivery_id))
            self._audit(record["task_id"], "DELIVERY_APPROVED", None, {"delivery_id": delivery_id, "approver": approver})

    def mark_delivery(self, delivery_id: str, status: str, provider_message_id: str | None) -> None:
        with self.transaction():
            record = self.delivery(delivery_id)
            self.db.execute("UPDATE deliveries SET status=?,provider_message_id=? WHERE delivery_id=?",
                            (status, provider_message_id, delivery_id))
            self._audit(record["task_id"], "DELIVERY_STATUS", None,
                        {"delivery_id": delivery_id, "status": status, "provider_message_id": provider_message_id})

    def update_delivery_content(self, delivery_id: str, content: str, content_digest: str) -> None:
        with self.transaction():
            record = self.delivery(delivery_id)
            if record["status"] in {"DELIVERED", "SENDING", "UNCERTAIN"}:
                raise RuntimeFailure("INVALID_DELIVERY_STATE", record["status"])
            key = f"{record['task_id']}:{record['recipient']}:{content_digest}"
            self.db.execute("UPDATE deliveries SET content=?,content_digest=?,idempotency_key=?,status='APPROVAL_REQUIRED',approver=NULL WHERE delivery_id=?",
                            (content, content_digest, key, delivery_id))
            self._audit(record["task_id"], "DELIVERY_APPROVAL_INVALIDATED", None,
                        {"delivery_id": delivery_id, "reason": "content_changed"})

    def delivery_count(self, recipient: str) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) AS n FROM deliveries WHERE recipient=? AND status='DELIVERED'",
                                   (recipient,)).fetchone()["n"]

    def add_history_message(self, application_id: str, user_id: str, role: str,
                            content: str, timestamp: str, message_id: str) -> None:
        if role not in {"user", "assistant"}:
            raise RuntimeFailure("INVALID_HISTORY_ROLE", role)
        with self.transaction():
            self.db.execute("INSERT INTO conversation_messages VALUES(?,?,?,?,?,?)",
                            (message_id, application_id, user_id, role, content, timestamp))

    def create_history_snapshot(self, task_id: str, application_id: str, user_id: str,
                                limit: int = 10) -> None:
        with self.lock:
            rows = list(self.db.execute(
                "SELECT * FROM conversation_messages WHERE application_id=? AND user_id=? "
                "ORDER BY message_timestamp DESC,message_id DESC LIMIT ?",
                (application_id, user_id, limit)))
        rows.reverse()
        with self.transaction():
            for position, row in enumerate(rows):
                self.db.execute("INSERT INTO history_snapshots VALUES(?,?,?,?,?,?)", (
                    task_id, position, row["message_id"], row["role"], row["content"], row["message_timestamp"]))
            self._audit(task_id, "HISTORY_SNAPSHOT_CREATED", None, {"message_count": len(rows)})

    def history_snapshot(self, task_id: str) -> list[dict[str, str]]:
        with self.lock:
            rows = list(self.db.execute(
                "SELECT message_id,role,content,message_timestamp FROM history_snapshots "
                "WHERE task_id=? ORDER BY position", (task_id,)))
        return [{k: row[k] for k in ("message_id", "role", "content", "message_timestamp")} for row in rows]
