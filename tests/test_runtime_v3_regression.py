import tempfile
import time
import unittest

from applications.ecommerce import build_application, seed_resources
from kernel_runtime import Application, ModuleResult, Runtime, SQLiteRepository, StageSpec, TaskRequest
from kernel_runtime.delivery import DeliveryRequest, DeliveryService, MockEmailProvider
from kernel_runtime.errors import PermissionFailure, RuntimeFailure


class RuntimeV3RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db")
        self.repo = SQLiteRepository(self.tmp.name)
        seed_resources(self.repo)
        self.runtime = Runtime(self.repo)
        self.runtime.register(build_application())

    def request(self, text="请查询订单当前状态"):
        return TaskRequest("ecommerce_customer_service", text,
                           {"user_id": "mock", "shop_id": "mock_shop"},
                           {"channel": "test", "application": "ecommerce_customer_service"})

    def test_ecommerce_closed_loop(self):
        result = self.runtime.submit(self.request())
        self.assertEqual("FINISHED", result["runtime_state"]["lifecycle"])
        self.assertEqual("TASK_COMPLETED", result["runtime_state"]["current_stage"])
        self.assertEqual(100, result["business_store"]["quality_result"]["score"])
        self.assertEqual(5, len(result["business_log"]))
        self.assertEqual(6, len(result["runtime_audit"]))

    def test_runtime_and_business_are_separate(self):
        result = self.runtime.submit(self.request())
        self.assertNotIn("goal", result["runtime_state"])
        self.assertNotIn("current_stage", result["business_store"])
        self.assertTrue(all("module_id" not in e for e in result["runtime_audit"]))

    def test_refund_uses_external_sop(self):
        result = self.runtime.submit(self.request("这个订单怎么退款？"))
        self.assertEqual("refund_sop", result["business_store"]["sop_reference"]["resource_id"])

    def test_module_cannot_write_runtime_state(self):
        app = build_application()
        class Bad:
            def execute(self, ctx): return ModuleResult({"current_stage": "TASK_COMPLETED"}, "attack")
        app.modules["dispatcher"] = Bad()
        rt = Runtime(self.repo); rt.register(app)
        result = rt.submit(self.request())
        self.assertEqual("FAILED", result["runtime_state"]["lifecycle"])
        self.assertEqual("DISPATCH_FAILED", result["runtime_state"]["current_stage"])

    def test_resource_permission(self):
        app = build_application()
        class Bad:
            def execute(self, ctx):
                ctx.resources.get("refund_sop")
                return ModuleResult({"dispatch_result": {}}, "bad")
        app.modules["dispatcher"] = Bad()
        rt = Runtime(self.repo); rt.register(app)
        result = rt.submit(self.request())
        self.assertEqual("DISPATCH_FAILED", result["runtime_state"]["current_stage"])

    def test_timeout_rejects_late_result(self):
        app = build_application()
        app.stages["DISPATCHING"] = StageSpec("DISPATCHING", "dispatcher", "CUSTOMER_PLANNING", "DISPATCH_FAILED", (), ("dispatch_result",), .01)
        class Slow:
            def execute(self, ctx):
                time.sleep(.05)
                return ModuleResult({"dispatch_result": {"domain": "ecommerce"}}, "late")
        app.modules["dispatcher"] = Slow()
        rt = Runtime(self.repo); rt.register(app)
        result = rt.submit(self.request())
        self.assertEqual("DISPATCH_FAILED", result["runtime_state"]["current_stage"])
        self.assertEqual({}, result["business_store"])

    def test_second_industry_without_runtime_change(self):
        class Echo:
            def execute(self, ctx): return ModuleResult({"document": {"text": ctx.task_input}}, "document created")
        app = Application("document_app", "PROCESSING", "DONE",
                          {"PROCESSING": StageSpec("PROCESSING", "echo", "DONE", "FAILED", (), ("document",), 1)},
                          {"echo": Echo()})
        self.runtime.register(app)
        result = self.runtime.submit(TaskRequest("document_app", "hello", {}, {}))
        self.assertEqual("DONE", result["runtime_state"]["current_stage"])
        self.assertEqual("hello", result["business_store"]["document"]["text"])

    def test_identity_failure_creates_no_task_and_handoff(self):
        bad = TaskRequest("ecommerce_customer_service", "hello", {"user_id": "u"},
                          {"application": "ecommerce_customer_service"})
        result = self.runtime.submit(bad)
        self.assertEqual("HUMAN_HANDOFF", result["status"])
        count = self.repo.db.execute("SELECT COUNT(*) AS n FROM runtime_tasks").fetchone()["n"]
        self.assertEqual(0, count)

    def test_transient_module_failure_retries_once(self):
        app = build_application()
        class Flaky:
            calls = 0
            def execute(self, ctx):
                self.calls += 1
                if self.calls == 1: raise RuntimeFailure("TEMPORARY_FAILURE", "retry")
                return ModuleResult({"dispatch_result": {"domain": "ecommerce"}}, "recovered")
        flaky = Flaky(); app.modules["dispatcher"] = flaky
        rt = Runtime(self.repo); rt.register(app)
        result = rt.submit(self.request())
        self.assertEqual("FINISHED", result["runtime_state"]["lifecycle"])
        self.assertEqual(2, flaky.calls)
        self.assertEqual(2, result["runtime_state"]["attempt_no"])

    def test_permanent_failure_closes_and_handoffs(self):
        app = build_application()
        class Broken:
            def execute(self, ctx): raise RuntimeFailure("PERMANENT_FAILURE", "broken")
        app.modules["customer"] = Broken()
        rt = Runtime(self.repo); rt.register(app)
        result = rt.submit(self.request())
        self.assertEqual("CUSTOMER_FAILED", result["runtime_state"]["current_stage"])
        handoffs = self.repo.db.execute("SELECT COUNT(*) AS n FROM human_handoffs WHERE task_id=?",
                                        (result["runtime_state"]["task_id"],)).fetchone()["n"]
        self.assertEqual(1, handoffs)

    def test_secret_cannot_enter_business_store(self):
        app = build_application()
        class Leaker:
            def execute(self, ctx): return ModuleResult({"dispatch_result": {"api_key": "secret"}}, "leak")
        app.modules["dispatcher"] = Leaker()
        rt = Runtime(self.repo); rt.register(app)
        result = rt.submit(self.request())
        self.assertEqual("DISPATCH_FAILED", result["runtime_state"]["current_stage"])
        self.assertEqual({}, result["business_store"])

    def test_delivery_requires_bound_recipient_and_approval(self):
        result = self.runtime.submit(self.request())
        task_id = result["runtime_state"]["task_id"]
        provider = MockEmailProvider()
        service = DeliveryService(self.repo, provider, {"mock": "owner@example.com"})
        delivery_id = service.create(DeliveryRequest(task_id, "owner@example.com", "测试结果"))
        with self.assertRaises(PermissionFailure): service.send(delivery_id)
        service.approve(delivery_id, "owner")
        sent = service.send(delivery_id)
        self.assertEqual("delivered", sent["status"])

    def test_delivery_recipient_whitelist(self):
        result = self.runtime.submit(self.request())
        task_id = result["runtime_state"]["task_id"]
        service = DeliveryService(self.repo, MockEmailProvider(), {"mock": "owner@example.com"})
        with self.assertRaises(PermissionFailure):
            service.create(DeliveryRequest(task_id, "attacker@example.com", "data"))

    def test_delivery_is_idempotent(self):
        result = self.runtime.submit(self.request())
        task_id = result["runtime_state"]["task_id"]
        provider = MockEmailProvider(); service = DeliveryService(self.repo, provider, {"mock": "owner@example.com"})
        request = DeliveryRequest(task_id, "owner@example.com", "same")
        one = service.create(request); two = service.create(request)
        self.assertEqual(one, two)
        service.approve(one, "owner")
        first = service.send(one); second = service.send(one)
        self.assertEqual(first["provider_message_id"], second["provider_message_id"])
        self.assertEqual(1, len(provider.sent))

    def test_delivery_timeout_becomes_uncertain(self):
        result = self.runtime.submit(self.request()); task_id = result["runtime_state"]["task_id"]
        class Unknown:
            def send(self, recipient, content, idempotency_key): raise TimeoutError()
        service = DeliveryService(self.repo, Unknown(), {"mock": "owner@example.com"})
        delivery_id = service.create(DeliveryRequest(task_id, "owner@example.com", "same"))
        service.approve(delivery_id, "owner")
        with self.assertRaises(RuntimeFailure): service.send(delivery_id)
        self.assertEqual("UNCERTAIN", self.repo.delivery(delivery_id)["status"])


if __name__ == "__main__": unittest.main()
