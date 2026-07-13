from __future__ import annotations

import threading
import time
from typing import Any
from uuid import uuid4

from kernel_runtime.engine import Runtime
from kernel_runtime.errors import RuntimeFailure
from kernel_runtime.models import TaskRequest

from .backend import JobBackend
from .models import JobRecord
from .metrics import RuntimeMetrics


class ProductionRuntimeService:
    """将同步Runtime包装为可排队、可并发、会话有序的执行服务。"""

    def __init__(
        self,
        runtime: Runtime,
        backend: JobBackend,
        worker_count: int = 4,
        max_active_tasks: int = 8,
        lease_seconds: float = 30,
        max_attempts: int = 3,
        metrics: RuntimeMetrics | None = None,
    ) -> None:
        self.runtime = runtime
        self.backend = backend
        self.worker_count = worker_count
        self.lease_seconds = lease_seconds
        self.max_attempts = max(1, max_attempts)
        self.metrics = metrics or RuntimeMetrics()
        self.capacity = threading.BoundedSemaphore(max_active_tasks)
        self.stop_event = threading.Event()
        self.workers: list[threading.Thread] = []

    def submit(self, request: TaskRequest, session_id: str, idempotency_key: str) -> dict[str, Any]:
        if not session_id.strip() or not idempotency_key.strip():
            raise RuntimeFailure("INVALID_JOB_IDENTITY", "session_id and idempotency_key are required")
        candidate = JobRecord.create(request, session_id, idempotency_key, self.max_attempts)
        job = self.backend.submit(candidate)
        self.metrics.increment("submitted")
        if job.job_id != candidate.job_id:
            self.metrics.increment("duplicate")
        return {"job_id": job.job_id, "status": job.status, "duplicate": job.job_id != candidate.job_id}

    def start(self) -> None:
        if self.workers:
            return
        self.stop_event.clear()
        self.recover_expired()
        for index in range(self.worker_count):
            worker_id = f"worker_{index}_{uuid4().hex[:8]}"
            thread = threading.Thread(target=self._worker_loop, args=(worker_id,), daemon=True)
            thread.start()
            self.workers.append(thread)

    def stop(self, timeout: float = 5) -> None:
        self.stop_event.set()
        for thread in self.workers:
            thread.join(timeout)
        self.workers.clear()

    def cancel(self, job_id: str) -> bool:
        job = self.backend.get(job_id)
        changed = self.backend.cancel(job_id)
        if changed and job.task_id:
            self.runtime.cancel(job.task_id)
        if changed:
            self.metrics.increment("cancelled")
        return changed

    def status(self, job_id: str) -> dict[str, Any]:
        return self.backend.get(job_id).as_dict()

    def wait(self, job_id: str, timeout: float = 30) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.backend.get(job_id)
            if job.status in {"COMPLETED", "FAILED", "DEAD_LETTER", "CANCELLED"}:
                return job.as_dict()
            time.sleep(.01)
        raise RuntimeFailure("JOB_WAIT_TIMEOUT", job_id)

    def recover_expired(self) -> int:
        recovered = self.backend.requeue_expired()
        if recovered:
            self.metrics.increment("recovered", recovered)
        return recovered

    def _worker_loop(self, worker_id: str) -> None:
        while not self.stop_event.is_set():
            job = self.backend.claim(worker_id, self.lease_seconds, .2)
            if not job:
                continue
            self.metrics.increment("claimed")
            with self.backend.session_lock(job.session_id, timeout=self.lease_seconds) as acquired:
                if not acquired:
                    self.backend.fail(job.job_id, "SESSION_LOCK_TIMEOUT", "Session is busy")
                    continue
                with self.capacity:
                    self._execute(worker_id, job)

    def _execute(self, worker_id: str, job: JobRecord) -> None:
        try:
            current = self.backend.get(job.job_id)
            if current.cancelled:
                return
            created = self.runtime.create(job.task_request())
            if isinstance(created, dict):
                self.backend.complete(job.job_id, created)
                self.metrics.increment("completed")
                return
            task_id = created
            self.backend.attach_task(job.job_id, task_id)
            if self.backend.get(job.job_id).cancelled:
                self.runtime.cancel(task_id)
                return
            self.backend.heartbeat(job.job_id, worker_id, self.lease_seconds)
            self.runtime.run(task_id)
            current = self.backend.get(job.job_id)
            if current.cancelled:
                return
            self.backend.complete(job.job_id, self.runtime.repo.snapshot(task_id))
            self.metrics.increment("completed")
        except BaseException as exc:
            code = getattr(exc, "code", "JOB_EXECUTION_FAILED")
            permanent = code in {"IDENTITY_FAILED", "ENVIRONMENT_MISMATCH", "VALIDATION_FAILED", "LLM_AUTH_FAILED"}
            current = self.backend.get(job.job_id)
            if not permanent and current.attempt_no < current.max_attempts and not current.cancelled:
                self.backend.retry(job.job_id, code, str(exc))
                self.metrics.increment("retried")
            else:
                self.backend.fail(job.job_id, code, str(exc))
                self.metrics.increment("dead_letter" if current.attempt_no >= current.max_attempts else "failed")
