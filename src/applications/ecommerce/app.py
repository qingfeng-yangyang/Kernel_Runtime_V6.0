from __future__ import annotations

from kernel_runtime.models import Application, StageSpec
from kernel_runtime.persistence import SQLiteRepository

from .modules import Customer, Dispatcher, Quality, Worker, Writer
from .schemas import VALIDATORS
from kernel_runtime.errors import ValidationFailure
from kernel_runtime.models import TaskRequest


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("business field must be an object")


def _identity(request: TaskRequest) -> None:
    identity = request.trusted_identity
    environment = request.trusted_environment
    if not identity.get("user_id") or not identity.get("shop_id"):
        raise ValidationFailure("IDENTITY_FAILED", "user_id and shop_id are required")
    if environment.get("application") != "ecommerce_customer_service":
        raise ValidationFailure("ENVIRONMENT_MISMATCH", "Trusted environment does not match application")


def build_application() -> Application:
    stages = {
        "DISPATCHING": StageSpec("DISPATCHING", "dispatcher", "CUSTOMER_PLANNING", "DISPATCH_FAILED", (), ("dispatch_result",), 15, 1),
        "CUSTOMER_PLANNING": StageSpec("CUSTOMER_PLANNING", "customer", "WORKER_EXECUTING", "CUSTOMER_FAILED", ("dispatch_result",), ("goal", "plan", "sop_reference"), 30),
        "WORKER_EXECUTING": StageSpec("WORKER_EXECUTING", "worker", "WRITER_GENERATING", "WORKER_FAILED", ("plan",), ("information",), 30),
        "WRITER_GENERATING": StageSpec("WRITER_GENERATING", "writer", "QUALITY_CHECKING", "WRITER_FAILED", ("goal", "information"), ("result", "message"), 30),
        "QUALITY_CHECKING": StageSpec("QUALITY_CHECKING", "quality", "TASK_COMPLETED", "QUALITY_FAILED", ("goal", "plan", "information", "result", "message"), ("quality_result",), 30),
    }
    return Application(
        application_id="ecommerce_customer_service",
        initial_stage="DISPATCHING",
        completed_stage="TASK_COMPLETED",
        stages=stages,
        modules={"dispatcher": Dispatcher(), "customer": Customer(), "worker": Worker(), "writer": Writer(), "quality": Quality()},
        field_validators=VALIDATORS,
        resource_permissions={
            "CUSTOMER_PLANNING": ("refund_sop",),
            "WORKER_EXECUTING": ("order_status", "logistics_status"),
        },
        identity_validator=_identity,
        sensitive_fields=("phone", "address", "email"),
    )


def seed_resources(repo: SQLiteRepository) -> None:
    app = "ecommerce_customer_service"
    repo.seed_resource(app, "order_status", {"order_id": "ORDER-DEMO-001", "status": "运输中"})
    repo.seed_resource(app, "logistics_status", {"status": "运输中", "last_event": "包裹已到达转运中心"})
    repo.seed_resource(app, "refund_sop", {"version": "mock-v1", "summary": "支持七天无理由退货"})
