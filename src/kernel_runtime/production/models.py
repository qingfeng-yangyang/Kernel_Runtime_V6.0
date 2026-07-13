from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kernel_runtime.models import TaskRequest


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class JobRecord:
    job_id: str
    application_id: str
    session_id: str
    idempotency_key: str
    request: dict[str, Any]
    status: str = "QUEUED"
    task_id: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    attempt_no: int = 0
    lease_owner: str | None = None
    lease_until: float = 0.0
    cancelled: bool = False
    max_attempts: int = 3
    last_error_code: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def create(cls, request: TaskRequest, session_id: str, idempotency_key: str, max_attempts: int = 3) -> "JobRecord":
        return cls(
            job_id=f"job_{uuid4().hex}",
            application_id=request.application_id,
            session_id=session_id,
            idempotency_key=idempotency_key,
            max_attempts=max(1, max_attempts),
            request={
                "application_id": request.application_id,
                "input": request.input,
                "trusted_identity": request.trusted_identity,
                "trusted_environment": request.trusted_environment,
                "application_scope": list(request.application_scope),
            },
        )

    def task_request(self) -> TaskRequest:
        value = self.request
        return TaskRequest(
            value["application_id"],
            value["input"],
            dict(value["trusted_identity"]),
            dict(value["trusted_environment"]),
            tuple(value.get("application_scope", [])),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "JobRecord":
        return cls(**value)
