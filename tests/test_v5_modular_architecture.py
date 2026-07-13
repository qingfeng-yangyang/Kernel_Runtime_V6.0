import unittest

from applications.ecommerce import build_v5_fake_llm_application, seed_v5_resources
from applications.ecommerce.providers import MockEcommerceProvider, RuntimeResourceProvider
from applications.ecommerce.v5_modules import (
    CustomerAgent,
    DispatcherAgent,
    QualityAgent,
    WorkerModule,
    WriterAgent,
)
from kernel_runtime import Runtime, SQLiteRepository, TaskRequest


class RuntimeV5ModularArchitectureTests(unittest.TestCase):
    def request(self):
        return TaskRequest(
            "ecommerce_customer_service_v5",
            "请查询订单状态",
            {"user_id": "user_v5", "shop_id": "shop_v5"},
            {"application": "ecommerce_customer_service_v5", "channel": "mock"},
        )

    def test_each_stage_has_an_independent_module(self):
        app = build_v5_fake_llm_application()
        self.assertIsInstance(app.modules["Dispatcher"], DispatcherAgent)
        self.assertIsInstance(app.modules["Customer Agent"], CustomerAgent)
        self.assertIsInstance(app.modules["Worker"], WorkerModule)
        self.assertIsInstance(app.modules["Writer"], WriterAgent)
        self.assertIsInstance(app.modules["Quality"], QualityAgent)

    def test_worker_uses_runtime_provider_by_default(self):
        app = build_v5_fake_llm_application()
        self.assertIsInstance(app.modules["Worker"].provider, RuntimeResourceProvider)

    def test_worker_accepts_replaceable_business_provider(self):
        provider = MockEcommerceProvider({
            "order_status": {"order_id": "PROVIDER-001", "status": "已发货"},
            "logistics_status": {"status": "运输中", "last_event": "已揽收"},
        })
        repo = SQLiteRepository()
        seed_v5_resources(repo)
        runtime = Runtime(repo)
        runtime.register(build_v5_fake_llm_application(provider))
        result = runtime.submit(self.request())
        self.assertEqual("TASK_COMPLETED", result["runtime_state"]["current_stage"])
        self.assertIn("PROVIDER-001", result["business_store"]["message"]["content"])

    def test_application_assembly_keeps_runtime_contract(self):
        app = build_v5_fake_llm_application()
        self.assertEqual("DISPATCHING", app.initial_stage)
        self.assertEqual("TASK_COMPLETED", app.completed_stage)
        self.assertEqual(
            [
                "DISPATCHING",
                "CUSTOMER_PLANNING",
                "WORKER_EXECUTING",
                "WRITER_GENERATING",
                "QUALITY_CHECKING",
            ],
            list(app.stages),
        )


if __name__ == "__main__":
    unittest.main()
