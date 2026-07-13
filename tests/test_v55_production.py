import json
import tempfile
import time
import unittest
from pathlib import Path

from applications.ecommerce import build_v5_fake_llm_application, seed_v5_resources
from applications.ecommerce.providers import PlaybackEcommerceProvider, ResilientEcommerceProvider
from kernel_runtime import Runtime, SQLiteRepository, TaskRequest
from kernel_runtime.production import InMemoryJobBackend, ProductionRuntimeService
from kernel_runtime.production.models import JobRecord


def request(text="请查询订单状态"):
    return TaskRequest("ecommerce_customer_service_v5", text, {"user_id": "user-v55", "shop_id": "shop-v55"}, {"application": "ecommerce_customer_service_v5", "channel": "preproduction"})


class RuntimeV55ProductionTests(unittest.TestCase):
    def setUp(self):
        self.repo = SQLiteRepository()
        seed_v5_resources(self.repo)
        runtime = Runtime(self.repo)
        runtime.register(build_v5_fake_llm_application())
        self.backend = InMemoryJobBackend()
        self.service = ProductionRuntimeService(runtime, self.backend, worker_count=4, max_active_tasks=2)

    def tearDown(self):
        self.service.stop()

    def test_idempotent_submit_returns_same_job(self):
        first = self.service.submit(request(), "session-1", "same-key")
        second = self.service.submit(request(), "session-1", "same-key")
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])

    def test_async_closed_loop(self):
        self.service.start()
        submitted = self.service.submit(request(), "session-1", "job-1")
        result = self.service.wait(submitted["job_id"], timeout=3)
        self.assertEqual("COMPLETED", result["status"])
        self.assertEqual("TASK_COMPLETED", result["result"]["runtime_state"]["current_stage"])

    def test_different_sessions_complete_under_capacity_limit(self):
        self.service.start()
        ids = [self.service.submit(request(), f"session-{i}", f"job-{i}")["job_id"] for i in range(8)]
        values = [self.service.wait(job_id, timeout=5) for job_id in ids]
        self.assertTrue(all(value["status"] == "COMPLETED" for value in values))

    def test_cancel_queued_job(self):
        submitted = self.service.submit(request(), "session-1", "cancel-me")
        self.assertTrue(self.service.cancel(submitted["job_id"]))
        self.assertEqual("CANCELLED", self.service.status(submitted["job_id"])["status"])

    def test_expired_lease_is_requeued(self):
        job = self.backend.submit(JobRecord.create(request(), "session-1", "lease"))
        claimed = self.backend.claim("dead-worker", lease_seconds=.01, wait_seconds=0)
        self.assertEqual(job.job_id, claimed.job_id)
        time.sleep(.02)
        self.assertEqual(1, self.service.recover_expired())
        self.assertEqual("RETRY", self.backend.get(job.job_id).status)

    def test_playback_provider_validates_sanitized_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "resources.json"
            path.write_text(json.dumps({"order_status": {"order_id": "DEMO", "status": "paid"}}), encoding="utf-8")
            provider = ResilientEcommerceProvider(PlaybackEcommerceProvider(path))
            value = provider.fetch("order_status", object())
            self.assertEqual("DEMO", value["order_id"])


if __name__ == "__main__":
    unittest.main()
