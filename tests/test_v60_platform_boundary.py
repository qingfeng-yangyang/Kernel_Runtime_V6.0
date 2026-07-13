import unittest

from applications.ecommerce.providers import GatewayResourceProvider
from kernel_runtime.delivery_channels import DeliveryPayload, DeliveryRouter, MockChannelProvider
from kernel_runtime.errors import PermissionFailure, ValidationFailure
from kernel_runtime.media import MediaReference, MockMediaStorage
from kernel_runtime.models import ModuleContext
from kernel_runtime.production import RuntimeMetrics


DIGEST = "a" * 64


class GatewayStub:
    def get_order(self, arguments): return {"order_id": arguments["order_id"], "status": "paid"}
    def get_logistics(self, arguments): return {"status": "shipping", "last_event": "hub"}
    def get_product(self, arguments): return {"product_id": "p1", "name": "demo"}
    def get_shop_policy(self, arguments): return {"policy_id": "policy1", "content": "demo"}
    def get_sop(self, kind, arguments): return {"version": "v1", "constraints": [kind]}
    def get_history(self, arguments, limit=10): return []


class NoResources:
    def get(self, resource_id, payload=None): raise AssertionError("Runtime resource access was bypassed")


class RuntimeV60PlatformBoundaryTests(unittest.TestCase):
    def test_media_contract_and_mock_storage(self):
        media = MediaReference("m1", "image", "storage://safe/m1", "image/png", 32, DIGEST, "product")
        media.validate()
        storage = MockMediaStorage()
        storage.add(media)
        self.assertEqual(media, storage.resolve("m1"))

    def test_media_rejects_external_unsafe_uri_and_oversize(self):
        with self.assertRaises(ValidationFailure):
            MediaReference("m1", "image", "file:///secret", "image/png", 1, DIGEST).validate()
        with self.assertRaises(ValidationFailure):
            MediaReference("m2", "video", "https://safe.test/v", "video/mp4", 30_000_000, DIGEST).validate()

    def test_delivery_router_is_idempotent(self):
        provider = MockChannelProvider()
        router = DeliveryRouter({"ecommerce_window": provider})
        payload = DeliveryPayload("ecommerce_window", "conversation-1", "订单已发货")
        first = router.deliver(payload, "delivery-1")
        second = router.deliver(payload, "delivery-1")
        self.assertEqual(first, second)
        self.assertEqual(1, len(provider.sent))

    def test_disabled_delivery_channel_is_rejected(self):
        with self.assertRaises(PermissionFailure):
            DeliveryRouter({}).deliver(DeliveryPayload("email", "safe@example.test", "hello"), "key")

    def test_gateway_provider_maps_business_resources_without_runtime_change(self):
        context = ModuleContext("t", "ecommerce", "WORKER_EXECUTING", "query", {}, NoResources(),
                                dynamic_context={"resource_arguments": {"order_status": {"order_id": "O-1"}}})
        result = GatewayResourceProvider(GatewayStub()).fetch("order_status", context)
        self.assertEqual("O-1", result["order_id"])

    def test_gateway_rejects_unknown_resource(self):
        context = ModuleContext("t", "ecommerce", "WORKER_EXECUTING", "query", {}, NoResources())
        with self.assertRaises(Exception):
            GatewayResourceProvider(GatewayStub()).fetch("secret_database", context)

    def test_metrics_are_allowlisted_counts_only(self):
        metrics = RuntimeMetrics()
        metrics.increment("submitted")
        self.assertEqual(1, metrics.snapshot()["submitted"])
        with self.assertRaises(ValueError):
            metrics.increment("user_email")


if __name__ == "__main__":
    unittest.main()
