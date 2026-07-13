from __future__ import annotations

import queue
import threading
from typing import Any
from uuid import uuid4

from .errors import CancelledFailure, PermissionFailure, RuntimeFailure, TimeoutFailure, ValidationFailure
from .models import Application, ModuleContext, TaskRequest
from .persistence import SQLiteRepository
from .security import ExecutionGrant, redact, reject_secrets, reject_unsafe_markup


class _Resources:
    def __init__(self, repo: SQLiteRepository, application_id: str, allowed: tuple[str, ...], grant: ExecutionGrant):
        self.repo, self.application_id, self.allowed, self.grant = repo, application_id, allowed, grant

    def get(self, resource_id: str, payload: dict[str, Any] | None = None) -> Any:
        self.grant.require_active()
        if resource_id not in self.allowed:
            raise PermissionFailure("RESOURCE_NOT_ALLOWED", resource_id)
        return self.repo.resource(self.application_id, resource_id, self.grant.task_id)


class Runtime:
    def __init__(self, repository: SQLiteRepository) -> None:
        self.repo = repository
        self.apps: dict[str, Application] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancel_lock = threading.RLock()

    def register(self, app: Application) -> None:
        app.validate()
        if app.application_id in self.apps:
            raise ValueError("application already registered")
        self.apps[app.application_id] = app

    def submit(self, request: TaskRequest) -> dict[str, Any]:
        created = self.create(request)
        if isinstance(created, dict):
            return created
        task_id = created
        self.run(task_id)
        return self.repo.snapshot(task_id)

    def create(self, request: TaskRequest) -> str | dict[str, Any]:
        if request.application_id not in self.apps:
            raise RuntimeFailure("APPLICATION_NOT_FOUND", request.application_id)
        if not request.input.strip():
            raise ValidationFailure("INVALID_INPUT", "Input cannot be empty")
        app = self.apps[request.application_id]
        try:
            if app.identity_validator:
                app.identity_validator(request)
        except Exception as exc:
            code = getattr(exc, "code", "IDENTITY_FAILED")
            handoff_id = self.repo.handoff(None, code, {"application_id": request.application_id})
            return {"status": "HUMAN_HANDOFF", "task_id": None, "handoff_id": handoff_id,
                    "error": {"error_code": code}}
        task_id = f"task_{uuid4().hex}"
        with self._cancel_lock:
            self._cancel_events[task_id] = threading.Event()
        self.repo.create_task(task_id, app.application_id, request.input,
                              request.trusted_identity, request.trusted_environment, app.initial_stage)
        if app.task_initializer:
            app.task_initializer(self.repo, task_id, request)
        return task_id

    def cancel(self, task_id: str, reason: str = "external_cancel") -> bool:
        with self._cancel_lock:
            event = self._cancel_events.setdefault(task_id, threading.Event())
            event.set()
        return self.repo.cancel_task(task_id, reason)

    def run(self, task_id: str) -> None:
        state = self.repo.state(task_id)
        with self._cancel_lock:
            cancel_event = self._cancel_events.setdefault(task_id, threading.Event())
        app = self.apps[state["application_id"]]
        for _ in range(max(8, len(app.stages) * 3)):
            if cancel_event.is_set():
                self.repo.cancel_task(task_id)
                return
            state = self.repo.state(task_id)
            if state["lifecycle"] != "RUNNING":
                return
            spec = app.stages[state["current_stage"]]
            store = self.repo.business(task_id)
            if app.normative_validator:
                try:
                    app.normative_validator(spec.stage_id, store)
                except RuntimeFailure as exc:
                    self.repo.security_event(task_id, "NORMATIVE_VALIDATION_FAILED",
                                             {"stage": spec.stage_id, "error_code": exc.code})
                    self.repo.fail(task_id, spec.stage_id, spec.failure_stage, exc.code)
                    self.repo.handoff(task_id, exc.code, {"stage": spec.stage_id})
                    return
            readable = {k: store[k] for k in spec.read_fields if k in store}
            grant = ExecutionGrant.issue(task_id, state["attempt_no"], spec.stage_id, spec.module_id)
            resources = _Resources(self.repo, app.application_id,
                                   app.resource_permissions.get(spec.stage_id, ()), grant)
            context = ModuleContext(task_id, app.application_id, spec.stage_id,
                                    state["input"], readable, resources, state["attempt_no"],
                                    (app.dynamic_context_builder(self.repo, task_id, spec.stage_id)
                                     if app.dynamic_context_builder else {}), cancel_event)
            for retry_no in range(spec.max_retries + 1):
              try:
                result = self._call(app.modules[spec.module_id], context, spec.timeout_seconds, grant)
                if result.status != "success":
                    raise RuntimeFailure(result.error_code or "MODULE_FAILED", result.error_message or "Module failed")
                if set(result.output) != set(spec.write_fields):
                    raise ValidationFailure("INVALID_OUTPUT_FIELDS", "Output does not match stage schema")
                for field, value in result.output.items():
                    validator = app.field_validators.get(field)
                    if validator:
                        try:
                            validator(value)
                        except Exception as exc:
                            raise ValidationFailure("BUSINESS_SCHEMA_FAILED", str(exc)) from exc
                reject_secrets(result.output)
                reject_unsafe_markup(result.output)
                reject_unsafe_markup(result.business_event)
                result = type(result)(redact(result.output, app.sensitive_fields),
                                      redact(result.business_event, app.sensitive_fields),
                                      result.status, result.error_code, result.error_message)
                if spec.stage_id == "QUALITY_CHECKING" and result.output.get("quality_result", {}).get("status") == "fail":
                    quality = result.output["quality_result"]
                    issues = quality.get("issues", [])
                    security_types = {"permission_violation", "secret_exposure", "evidence_forgery", "cross_task_access"}
                    issue_types = {x.get("issue_type") for x in issues}
                    if issue_types & security_types or self.repo.quality_recovery_count(task_id) >= 1:
                        self.repo.fail(task_id, spec.stage_id, spec.failure_stage, "QUALITY_BUSINESS_FAILED")
                        self.repo.handoff(task_id, "QUALITY_BUSINESS_FAILED", {"issues": issues})
                        return
                    check_stages = {x.get("check_stage") for x in issues}
                    if "plan_to_worker_log" in check_stages:
                        target = "WORKER_EXECUTING"
                    elif "goal_to_result" in check_stages:
                        target = "CUSTOMER_PLANNING"
                    else:
                        target = "WRITER_GENERATING"
                    self.repo.commit_stage(task_id=task_id, application_id=app.application_id,
                                           expected_stage=spec.stage_id, module_id=spec.module_id,
                                           result=result, allowed_fields=spec.write_fields,
                                           next_stage=target, completed_stage=app.completed_stage,
                                           increment_attempt=True)
                    self.repo.record_quality_recovery(task_id, target, issues)
                    break
                self.repo.commit_stage(task_id=task_id, application_id=app.application_id,
                                       expected_stage=spec.stage_id, module_id=spec.module_id,
                                       result=result, allowed_fields=spec.write_fields,
                                       next_stage=spec.success_stage, completed_stage=app.completed_stage)
                break
              except RuntimeFailure as exc:
                grant.revoke()
                if exc.code in {"TASK_CANCELLED", "LLM_CANCELLED"}:
                    self.repo.cancel_task(task_id)
                    return
                self.repo.security_event(task_id, "STAGE_ERROR", {"stage": spec.stage_id, "error_code": exc.code})
                retryable = getattr(exc, "retryable", False) or exc.code in {
                    "TEMPORARY_FAILURE", "STORE_FAILED", "STAGE_TIMEOUT",
                    "LLM_CONNECT_TIMEOUT", "LLM_FIRST_RESPONSE_TIMEOUT", "LLM_IDLE_TIMEOUT",
                }
                if retry_no < spec.max_retries and retryable:
                    attempt = self.repo.begin_attempt(task_id, spec.stage_id)
                    grant = ExecutionGrant.issue(task_id, attempt, spec.stage_id, spec.module_id)
                    resources = _Resources(self.repo, app.application_id,
                                           app.resource_permissions.get(spec.stage_id, ()), grant)
                    context = ModuleContext(task_id, app.application_id, spec.stage_id,
                                            state["input"], readable, resources, attempt,
                                            (app.dynamic_context_builder(self.repo, task_id, spec.stage_id)
                                             if app.dynamic_context_builder else {}), cancel_event)
                    continue
                self.repo.fail(task_id, spec.stage_id, spec.failure_stage, exc.code)
                self.repo.handoff(task_id, exc.code, {"stage": spec.stage_id})
                return
        state = self.repo.state(task_id)
        if state["lifecycle"] == "RUNNING":
            self.repo.fail(task_id, state["current_stage"], "LOOP_FAILED", "LOOP_LIMIT")

    @staticmethod
    def _call(module: Any, context: ModuleContext, timeout: float, grant: ExecutionGrant):
        out: queue.Queue = queue.Queue(maxsize=1)
        def target():
            try: out.put((True, module.execute(context)))
            except BaseException as exc: out.put((False, exc))
        threading.Thread(target=target, daemon=True).start()
        remaining = timeout
        while True:
            if context.cancellation_event is not None and context.cancellation_event.is_set():
                grant.revoke()
                raise CancelledFailure("TASK_CANCELLED", "Task cancelled")
            interval = min(.05, remaining)
            try:
                ok, value = out.get(timeout=interval)
                break
            except queue.Empty as exc:
                remaining -= interval
                if remaining <= 0:
                    grant.revoke()
                    raise TimeoutFailure("STAGE_TIMEOUT", "Stage exceeded timeout") from exc
        grant.revoke()
        if not ok:
            if isinstance(value, RuntimeFailure): raise value
            raise RuntimeFailure("MODULE_EXCEPTION", str(value))
        return value
