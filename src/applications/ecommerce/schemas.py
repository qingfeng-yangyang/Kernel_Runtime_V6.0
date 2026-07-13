from __future__ import annotations

from typing import Any


class SchemaError(ValueError):
    pass


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict): raise SchemaError(f"{name} must be object")
    return value


def _required(value: dict[str, Any], fields: set[str], name: str) -> None:
    missing = fields - set(value)
    if missing: raise SchemaError(f"{name} missing {sorted(missing)}")


def dispatch_result(value: Any) -> None:
    value = _dict(value, "dispatch_result"); _required(value, {"domain"}, "dispatch_result")
    if value["domain"] != "ecommerce": raise SchemaError("domain must be ecommerce")


def goal(value: Any) -> None:
    value = _dict(value, "goal"); _required(value, {"description"}, "goal")


def plan(value: Any) -> None:
    value = _dict(value, "plan"); _required(value, {"summary"}, "plan")
    if "resources" in value:
        if not isinstance(value["resources"], list): raise SchemaError("plan.resources must be list")
    else:
        _required(value, {"steps", "plan_request_group"}, "plan")
        if not isinstance(value["steps"], list): raise SchemaError("plan.steps must be list")


def sop_reference(value: Any) -> None:
    if value is None: return
    value = _dict(value, "sop_reference"); _required(value, {"resource_id", "version"}, "sop_reference")


def information(value: Any) -> None:
    value = _dict(value, "information")
    key = "items" if "items" in value else "facts"
    _required(value, {key}, "information")
    if not isinstance(value[key], list): raise SchemaError(f"information.{key} must be list")


def result(value: Any) -> None:
    value = _dict(value, "result")
    _required(value, {"content"}, "result")
    if "facts" not in value and "evidence_refs" not in value:
        raise SchemaError("result requires facts or evidence_refs")


def message(value: Any) -> None:
    value = _dict(value, "message"); _required(value, {"content"}, "message")
    if not isinstance(value["content"], str) or not value["content"].strip(): raise SchemaError("message content empty")


def quality_result(value: Any) -> None:
    value = _dict(value, "quality_result"); _required(value, {"status", "score", "issues"}, "quality_result")
    if value["status"] not in {"pass", "fail"}: raise SchemaError("invalid quality status")
    if not isinstance(value["score"], int) or not 0 <= value["score"] <= 100: raise SchemaError("invalid score")


VALIDATORS = {
    "dispatch_result": dispatch_result,
    "goal": goal,
    "plan": plan,
    "sop_reference": sop_reference,
    "information": information,
    "result": result,
    "message": message,
    "quality_result": quality_result,
    "resource_request": lambda value: None if value is None else _dict(value, "resource_request"),
    "sop_constraints": lambda value: None if value is None else (
        None if isinstance(value, list) else (_ for _ in ()).throw(SchemaError("sop_constraints must be list"))),
}
