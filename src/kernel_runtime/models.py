from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


class Module(Protocol):
    def execute(self, context: "ModuleContext") -> "ModuleResult": ...


@dataclass(frozen=True)
class TaskRequest:
    application_id: str
    input: str
    trusted_identity: dict[str, str]
    trusted_environment: dict[str, str]
    application_scope: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageSpec:
    stage_id: str
    module_id: str
    success_stage: str
    failure_stage: str
    read_fields: tuple[str, ...] = ()
    write_fields: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    max_retries: int = 0


@dataclass(frozen=True)
class ModuleContext:
    task_id: str
    application_id: str
    stage_id: str
    task_input: str
    business_store: dict[str, Any]
    resources: "ResourceAccess"
    attempt_no: int = 1
    dynamic_context: dict[str, Any] = field(default_factory=dict)
    cancellation_event: Any = None


class ResourceAccess(Protocol):
    def get(self, resource_id: str, payload: dict[str, Any] | None = None) -> Any: ...


@dataclass(frozen=True)
class ModuleResult:
    output: dict[str, Any]
    business_event: str
    status: str = "success"
    error_code: str | None = None
    error_message: str | None = None


Validator = Callable[[dict[str, Any]], None]


@dataclass
class Application:
    application_id: str
    initial_stage: str
    completed_stage: str
    stages: dict[str, StageSpec]
    modules: dict[str, Module]
    field_validators: dict[str, Validator] = field(default_factory=dict)
    resource_permissions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    identity_validator: Callable[[TaskRequest], None] | None = None
    sensitive_fields: tuple[str, ...] = ()
    task_initializer: Callable[[Any, str, TaskRequest], None] | None = None
    dynamic_context_builder: Callable[[Any, str, str], dict[str, Any]] | None = None
    normative_validator: Callable[[str, dict[str, Any]], None] | None = None

    def validate(self) -> None:
        if self.initial_stage not in self.stages:
            raise ValueError("initial_stage must exist in stages")
        for spec in self.stages.values():
            if spec.module_id not in self.modules:
                raise ValueError(f"missing module: {spec.module_id}")
            if spec.success_stage != self.completed_stage and spec.success_stage not in self.stages:
                raise ValueError(f"unknown success stage: {spec.success_stage}")
