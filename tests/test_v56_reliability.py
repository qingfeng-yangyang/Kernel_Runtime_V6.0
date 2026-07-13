import tempfile
import time
import unittest
from pathlib import Path

from kernel_runtime.errors import RuntimeFailure
from kernel_runtime.models import TaskRequest
from kernel_runtime.production import ProductionRuntimeService, SQLiteJobBackend


def request():
    return TaskRequest("demo", "hello", {"user_id": "u", "shop_id": "s"}, {"application": "demo"})


class RuntimeStub:
    def __init__(self, failures=0, code="TEMPORARY"):
        self.failures = failures
        self.code = code
        self.calls = 0
        self.repo = self

    def create(self, value):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeFailure(self.code, "planned failure")
        return "task-ok"

    def run(self, task_id): pass
    def snapshot(self, task_id): return {"runtime_state": {"current_stage": "TASK_COMPLETED"}}
    def cancel(self, task_id): pass


class RuntimeV56ReliabilityTests(unittest.TestCase):
    def backend(self, folder):
        return SQLiteJobBackend(str(Path(folder) / "jobs.db"))

    def test_job_survives_backend_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self.backend(folder)
            job = first.submit(__import__("kernel_runtime.production.models", fromlist=["JobRecord"]).JobRecord.create(request(), "session", "key"))
            second = self.backend(folder)
            self.assertEqual(job.job_id, second.get(job.job_id).job_id)
            self.assertEqual(job.job_id, second.claim("worker", 30, 0).job_id)

    def test_transient_failure_retries_then_completes(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime = RuntimeStub(failures=1)
            service = ProductionRuntimeService(runtime, self.backend(folder), worker_count=1, max_attempts=3)
            service.start()
            try:
                job_id = service.submit(request(), "session", "retry")["job_id"]
                result = service.wait(job_id, 3)
                self.assertEqual("COMPLETED", result["status"])
                self.assertEqual(2, result["attempt_no"])
            finally: service.stop()

    def test_exhausted_retry_enters_dead_letter(self):
        with tempfile.TemporaryDirectory() as folder:
            service = ProductionRuntimeService(RuntimeStub(failures=9), self.backend(folder), worker_count=1, max_attempts=2)
            service.start()
            try:
                result = service.wait(service.submit(request(), "session", "dead")["job_id"], 3)
                self.assertEqual("DEAD_LETTER", result["status"])
                self.assertEqual(2, result["attempt_no"])
            finally: service.stop()

    def test_permanent_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            service = ProductionRuntimeService(RuntimeStub(failures=9, code="IDENTITY_FAILED"), self.backend(folder), worker_count=1)
            service.start()
            try:
                result = service.wait(service.submit(request(), "session", "permanent")["job_id"], 3)
                self.assertEqual("DEAD_LETTER", result["status"])
                self.assertEqual(1, result["attempt_no"])
            finally: service.stop()

    def test_expired_running_job_recovers_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = self.backend(folder)
            record = __import__("kernel_runtime.production.models", fromlist=["JobRecord"]).JobRecord.create(request(), "session", "lease")
            backend.submit(record)
            claimed = backend.claim("lost-worker", .01, 0)
            time.sleep(.02)
            restarted = self.backend(folder)
            self.assertEqual(1, restarted.requeue_expired())
            self.assertEqual("RETRY", restarted.get(claimed.job_id).status)


if __name__ == "__main__":
    unittest.main()
