from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .errors import PermissionFailure, ValidationFailure


SECRET_KEYS = re.compile(r"(api[_-]?key|token|authorization|cookie|password|secret|credential)", re.I)
EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
PHONE = re.compile(r"(?<!\d)(1\d{2})\d{4}(\d{4})(?!\d)")
UNSAFE_MARKUP = re.compile(r"[<>＜＞]")


def contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        return any(SECRET_KEYS.search(str(k)) or contains_secret(v) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_secret(v) for v in value)
    return False


def reject_secrets(value: Any) -> None:
    if contains_secret(value):
        raise ValidationFailure("SECRET_WRITE_BLOCKED", "Secret-like fields cannot enter Store or Log")


def reject_unsafe_markup(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            reject_unsafe_markup(key)
            reject_unsafe_markup(item)
    elif isinstance(value, list):
        for item in value: reject_unsafe_markup(item)
    elif isinstance(value, str) and UNSAFE_MARKUP.search(value):
        raise ValidationFailure("UNSAFE_MARKUP_DETECTED", "Angle brackets are forbidden in module output")



def redact(value: Any, sensitive_fields: tuple[str, ...] = ()) -> Any:
    fields = {x.lower() for x in sensitive_fields}
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if SECRET_KEYS.search(key) or key.lower() in fields:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact(item, sensitive_fields)
        return result
    if isinstance(value, list):
        return [redact(v, sensitive_fields) for v in value]
    if isinstance(value, str):
        value = EMAIL.sub(lambda m: m.group(1)[:2] + "***@" + m.group(2), value)
        return PHONE.sub(r"\1****\2", value)
    return value


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass
class ExecutionGrant:
    grant_id: str
    task_id: str
    attempt_no: int
    stage: str
    module_id: str
    active: bool = True

    @classmethod
    def issue(cls, task_id: str, attempt_no: int, stage: str, module_id: str):
        return cls(f"grant_{uuid4().hex}", task_id, attempt_no, stage, module_id)

    def require_active(self) -> None:
        if not self.active:
            raise PermissionFailure("EXECUTION_EXPIRED", "Execution grant expired")

    def revoke(self) -> None:
        self.active = False
