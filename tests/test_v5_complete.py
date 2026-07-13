from datetime import datetime, timedelta, timezone
import unittest

from applications.ecommerce import build_v5_fake_llm_application, seed_v5_resources
from applications.ecommerce.v5_application import _package
from kernel_runtime import ModuleResult, Runtime, SQLiteRepository, TaskRequest
from kernel_runtime.delivery import DeliveryRequest, DeliveryService, MockEmailProvider
from kernel_runtime.envelope import EnvelopeValidator
from kernel_runtime.errors import PermissionFailure, ValidationFailure
from kernel_runtime.provider_adapters import DisabledRealProvider, MappingProvider


class RuntimeV5CompleteTests(unittest.TestCase):
    def setUp(self):
        self.repo = SQLiteRepository()
        seed_v5_resources(self.repo)
        self.runtime = Runtime(self.repo)
        self.app = build_v5_fake_llm_application()
        self.runtime.register(self.app)

    def request(self, text="请查询订单状态"):
        return TaskRequest("ecommerce_customer_service_v5", text,
                           {"user_id": "user_v5", "shop_id": "shop_v5"},
                           {"application": "ecommerce_customer_service_v5", "channel": "mock"})

    def seed_history(self, count=12):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(count):
            self.repo.add_history_message("ecommerce_customer_service_v5", "user_v5",
                                          "user" if i % 2 == 0 else "assistant", f"message-{i}",
                                          (start + timedelta(seconds=i)).isoformat(), f"m-{i:02d}")

    def test_v5_fake_llm_closed_loop(self):
        result = self.runtime.submit(self.request())
        self.assertEqual("TASK_COMPLETED", result["runtime_state"]["current_stage"])
        self.assertEqual("FINISHED", result["runtime_state"]["lifecycle"])
        self.assertEqual(["order_status", "logistics_status"], result["business_store"]["result"]["evidence_refs"])

    def test_history_snapshot_is_last_ten_messages(self):
        self.seed_history(12)
        result = self.runtime.submit(self.request())
        snapshot = self.repo.history_snapshot(result["runtime_state"]["task_id"])
        self.assertEqual(10, len(snapshot))
        self.assertEqual("message-2", snapshot[0]["content"])
        self.assertEqual("message-11", snapshot[-1]["content"])

    def test_history_snapshot_does_not_change_during_task(self):
        self.seed_history(3)
        result = self.runtime.submit(self.request())
        task_id = result["runtime_state"]["task_id"]
        before = self.repo.history_snapshot(task_id)
        self.repo.add_history_message("ecommerce_customer_service_v5", "user_v5", "user", "new",
                                      "2026-02-01T00:00:00+00:00", "new-message")
        self.assertEqual(before, self.repo.history_snapshot(task_id))

    def test_dispatcher_dynamic_context_has_no_history_or_runtime_context(self):
        package = _package("dispatcher", "Dispatcher")
        messages = package.messages({"domain_enum": ["ecommerce"]}, "hello")
        dynamic = messages[1]["content"]
        self.assertNotIn("recent_conversation_context", dynamic)
        self.assertNotIn("runtime_context", dynamic)

    def test_dynamic_history_does_not_change_static_checksum(self):
        package = _package("customer", "Customer Agent")
        checksum = package.checksum
        one = package.messages({"recent_conversation_context": [{"content": "a"}]}, "x")
        two = package.messages({"recent_conversation_context": [{"content": "b"}]}, "y")
        self.assertEqual(checksum, package.checksum)
        self.assertEqual(one[0], two[0])
        self.assertNotEqual(one[1], two[1])

    def test_all_llm_prompts_have_ecommerce_identity(self):
        for name, module in (("dispatcher", "Dispatcher"), ("customer", "Customer Agent"),
                             ("writer", "Writer"), ("quality", "Quality")):
            self.assertIn("电商客服", _package(name, module).static_prompt)

    def test_prompt_files_are_unique_and_not_cross_wired(self):
        expected = {
            "dispatcher": "Dispatcher", "customer": "Customer Agent",
            "writer": "Writer", "quality": "Quality",
        }
        for name, module in expected.items():
            prompt = _package(name, module).static_prompt
            self.assertIn(module, prompt)
            self.assertIn("电商客服", prompt)
        dispatcher = " ".join(_package("dispatcher", "Dispatcher").static_prompt.split())
        quality = " ".join(_package("quality", "Quality").static_prompt.split())
        self.assertIn("你只接收 task_input 与 domain_enum", dispatcher)
        self.assertNotIn("你只接收 task_input 与 domain_enum", quality)
        self.assertNotIn("“stage”", dispatcher)

    def test_refund_uses_sop_after_goal_is_created(self):
        result = self.runtime.submit(self.request("这个订单怎么退款？"))
        store = result["business_store"]
        self.assertEqual("refund_sop", store["sop_reference"]["resource_id"])
        self.assertTrue(store["sop_constraints"])
        self.assertEqual("goal_v5", store["goal"]["goal_id"])

    def test_optional_logistics_failure_does_not_fail_task(self):
        self.repo.db.execute("DELETE FROM external_resources WHERE application_id=? AND resource_id=?",
                             ("ecommerce_customer_service_v5", "logistics_status"))
        self.repo.db.commit()
        result = self.runtime.submit(self.request())
        self.assertEqual("TASK_COMPLETED", result["runtime_state"]["current_stage"])
        self.assertEqual(["order_status"], result["business_store"]["result"]["evidence_refs"])

    def test_required_order_failure_handoffs(self):
        self.repo.db.execute("DELETE FROM external_resources WHERE application_id=? AND resource_id=?",
                             ("ecommerce_customer_service_v5", "order_status"))
        self.repo.db.commit()
        result = self.runtime.submit(self.request())
        self.assertEqual("WORKER_FAILED", result["runtime_state"]["current_stage"])

    def test_envelope_rejects_trailing_text_and_markup(self):
        validator = EnvelopeValidator()
        good = '{"stage":"S","module":"M","output":{"x":{"content":"ok"}},"log_content":{"status":"success","event":"ok","error_code":null,"error_message":null}}'
        with self.assertRaises(ValidationFailure): validator.validate_raw(good + " extra", stage="S", module="M", allowed_output_fields=("x",))
        bad = good.replace("ok\"}},", "<b>\"}},")
        with self.assertRaises(ValidationFailure): validator.validate_raw(bad, stage="S", module="M", allowed_output_fields=("x",))

    def test_runtime_rejects_forged_evidence(self):
        class ForgingWriter:
            def execute(self, ctx):
                return ModuleResult({"result": {"status": "success", "content": "伪造", "evidence_refs": ["secret_order"]},
                                     "message": {"status": "success", "content": "伪造"}}, "forged")
        self.app.modules["Writer"] = ForgingWriter()
        result = self.runtime.submit(self.request())
        self.assertEqual("QUALITY_FAILED", result["runtime_state"]["current_stage"])

    def test_quality_business_failure_recovers_once(self):
        class FlakyQuality:
            calls = 0
            def execute(self, ctx):
                self.calls += 1
                if self.calls == 1:
                    return ModuleResult({"quality_result": {"status": "fail", "score": 60,
                        "issues": [{"check_stage": "information_to_result", "issue_type": "unsupported_fact",
                                    "description": "retry writer", "severity": "high"}]}}, "quality checked")
                return ModuleResult({"quality_result": {"status": "pass", "score": 100, "issues": []}}, "quality checked")
        quality = FlakyQuality(); self.app.modules["Quality"] = quality
        result = self.runtime.submit(self.request())
        self.assertEqual("TASK_COMPLETED", result["runtime_state"]["current_stage"])
        self.assertEqual(2, quality.calls)
        self.assertEqual(1, self.repo.quality_recovery_count(result["runtime_state"]["task_id"]))

    def test_quality_security_failure_does_not_retry(self):
        class SecurityQuality:
            def execute(self, ctx):
                return ModuleResult({"quality_result": {"status": "fail", "score": 0,
                    "issues": [{"check_stage": "security", "issue_type": "permission_violation",
                                "description": "blocked", "severity": "critical"}]}}, "quality checked")
        self.app.modules["Quality"] = SecurityQuality()
        result = self.runtime.submit(self.request())
        self.assertEqual("QUALITY_FAILED", result["runtime_state"]["current_stage"])
        self.assertEqual(0, self.repo.quality_recovery_count(result["runtime_state"]["task_id"]))

    def test_quality_second_business_failure_handoffs(self):
        class AlwaysFailQuality:
            def execute(self, ctx):
                return ModuleResult({"quality_result": {"status": "fail", "score": 60,
                    "issues": [{"check_stage": "information_to_result", "issue_type": "unsupported_fact",
                                "description": "still bad", "severity": "high"}]}}, "quality checked")
        self.app.modules["Quality"] = AlwaysFailQuality()
        result = self.runtime.submit(self.request())
        self.assertEqual("QUALITY_FAILED", result["runtime_state"]["current_stage"])
        self.assertEqual(1, self.repo.quality_recovery_count(result["runtime_state"]["task_id"]))

    def test_external_provider_adapter_receives_trusted_context(self):
        seen = {}
        class Adapter:
            def fetch(self, call):
                seen["task_id"] = call.task_id; seen["shop_id"] = call.trusted_identity["shop_id"]
                return {"order_id": "REAL-ADAPTER-MOCK", "status": "测试中"}
        self.repo.register_resource_handler("ecommerce_customer_service_v5", "order_status", Adapter())
        result = self.runtime.submit(self.request())
        self.assertEqual("TASK_COMPLETED", result["runtime_state"]["current_stage"])
        self.assertEqual("shop_v5", seen["shop_id"])

    def test_real_provider_is_disabled_by_default(self):
        self.repo.register_resource_handler("ecommerce_customer_service_v5", "order_status", DisabledRealProvider())
        result = self.runtime.submit(self.request())
        self.assertEqual("WORKER_FAILED", result["runtime_state"]["current_stage"])

    def test_delivery_reject_expire_cancel_and_content_change(self):
        result = self.runtime.submit(self.request()); task = result["runtime_state"]["task_id"]
        service = DeliveryService(self.repo, MockEmailProvider(), {"user_v5": "owner@example.com"})
        one = service.create(DeliveryRequest(task, "owner@example.com", "one")); service.reject(one)
        self.assertEqual("REJECTED", self.repo.delivery(one)["status"])
        two = service.create(DeliveryRequest(task, "owner@example.com", "two")); service.approve(two, "owner")
        service.change_content(two, "changed")
        self.assertEqual("APPROVAL_REQUIRED", self.repo.delivery(two)["status"])
        service.expire(two); self.assertEqual("EXPIRED", self.repo.delivery(two)["status"])
        three = service.create(DeliveryRequest(task, "owner@example.com", "three")); service.cancel(three)
        self.assertEqual("CANCELLED", self.repo.delivery(three)["status"])


if __name__ == "__main__": unittest.main()
