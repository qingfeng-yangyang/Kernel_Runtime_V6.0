from __future__ import annotations

from kernel_runtime.errors import ValidationFailure
from kernel_runtime.models import Application, StageSpec, TaskRequest
from kernel_runtime.security import reject_secrets, reject_unsafe_markup

from .providers import BusinessResourceProvider
from .schemas import VALIDATORS
from .v5_modules import CustomerAgent, DispatcherAgent, QualityAgent, WorkerModule, WriterAgent
from .v5_support import load_package


APP_ID = "ecommerce_customer_service_v5"


# 保留旧的公开入口，避免测试和外部代码断开。
def _package(name: str, module_id: str):
    return load_package(name, module_id)


def _initializer(repo, task_id: str, request: TaskRequest) -> None:
    repo.create_history_snapshot(
        task_id,
        request.application_id,
        request.trusted_identity["user_id"],
        limit=10,
    )


def _identity_v5(request: TaskRequest) -> None:
    if not request.trusted_identity.get("user_id") or not request.trusted_identity.get("shop_id"):
        raise ValidationFailure("IDENTITY_FAILED", "user_id and shop_id are required")
    if request.trusted_environment.get("application") != request.application_id:
        raise ValidationFailure("ENVIRONMENT_MISMATCH", "Trusted environment does not match application")


def _dynamic(repo, task_id: str, stage: str):
    if stage in {"CUSTOMER_PLANNING", "WRITER_GENERATING"}:
        return {"recent_conversation_context": repo.history_snapshot(task_id)}
    if stage == "DISPATCHING":
        return {"domain_enum": ["ecommerce"]}
    return {}


def _normative(stage: str, store: dict) -> None:
    if stage != "QUALITY_CHECKING":
        return
    plan = store.get("plan") or {}
    information = store.get("information") or {}
    result = store.get("result") or {}
    message = store.get("message") or {}
    items = information.get("items", [])
    by_id = {item.get("resource_id"): item for item in items}
    group = plan.get("plan_request_group") or {"requests": []}

    for request in group.get("requests", []):
        required = request.get("required", group.get("default_required", True))
        item = by_id.get(request.get("resource_id"))
        if required and (not item or item.get("status") != "success"):
            raise ValidationFailure("REQUIRED_RESOURCE_FAILED", request.get("resource_id", "unknown"))

    refs = result.get("evidence_refs", [])
    if any(ref not in by_id or by_id[ref].get("status") != "success" for ref in refs):
        raise ValidationFailure("EVIDENCE_FORGERY", "Result references unavailable evidence")
    reject_secrets({"result": result, "message": message})
    reject_unsafe_markup({"result": result, "message": message})


def _stage_specs() -> dict[str, StageSpec]:
    return {
        "DISPATCHING": StageSpec(
            "DISPATCHING", "Dispatcher", "CUSTOMER_PLANNING", "DISPATCH_FAILED",
            (), ("dispatch_result",), 3, 1,
        ),
        "CUSTOMER_PLANNING": StageSpec(
            "CUSTOMER_PLANNING", "Customer Agent", "WORKER_EXECUTING", "CUSTOMER_FAILED",
            ("dispatch_result",),
            ("goal", "resource_request", "sop_reference", "sop_constraints", "plan"),
            5, 1,
        ),
        "WORKER_EXECUTING": StageSpec(
            "WORKER_EXECUTING", "Worker", "WRITER_GENERATING", "WORKER_FAILED",
            ("plan",), ("information",), 5, 1,
        ),
        "WRITER_GENERATING": StageSpec(
            "WRITER_GENERATING", "Writer", "QUALITY_CHECKING", "WRITER_FAILED",
            ("goal", "information"), ("result", "message"), 5, 1,
        ),
        "QUALITY_CHECKING": StageSpec(
            "QUALITY_CHECKING", "Quality", "TASK_COMPLETED", "QUALITY_FAILED",
            ("goal", "plan", "information", "result", "message", "sop_reference", "sop_constraints"),
            ("quality_result",), 5, 0,
        ),
    }


def build_v5_fake_llm_application(
    resource_provider: BusinessResourceProvider | None = None,
) -> Application:
    """装配电商应用；Runtime 内核无需知道各模块内部实现。"""

    return Application(
        APP_ID,
        "DISPATCHING",
        "TASK_COMPLETED",
        _stage_specs(),
        {
            "Dispatcher": DispatcherAgent(),
            "Customer Agent": CustomerAgent(),
            "Worker": WorkerModule(resource_provider),
            "Writer": WriterAgent(),
            "Quality": QualityAgent(),
        },
        field_validators=VALIDATORS,
        resource_permissions={
            "CUSTOMER_PLANNING": ("refund_sop",),
            "WORKER_EXECUTING": ("order_status", "logistics_status"),
        },
        identity_validator=_identity_v5,
        sensitive_fields=("phone", "address", "email"),
        task_initializer=_initializer,
        dynamic_context_builder=_dynamic,
        normative_validator=_normative,
    )


def seed_v5_resources(repo) -> None:
    repo.seed_resource(APP_ID, "order_status", {"order_id": "ORDER-DEMO-001", "status": "运输中"})
    repo.seed_resource(
        APP_ID,
        "logistics_status",
        {"status": "运输中", "last_event": "包裹已到达转运中心"},
    )
    repo.seed_resource(
        APP_ID,
        "refund_sop",
        {"version": "mock-v1", "constraints": ["退款前必须核验订单状态"]},
    )
