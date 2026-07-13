from __future__ import annotations

from typing import Any, Protocol

from kernel_runtime.errors import RuntimeFailure
from kernel_runtime.models import ModuleContext

from .contracts import validate_resource


class EcommerceGateway(Protocol):
    """真实店铺适配器应实现的最小能力；凭据只存在于适配器内部。"""

    def get_order(self, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def get_logistics(self, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def get_product(self, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def get_shop_policy(self, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def get_sop(self, kind: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def get_history(self, arguments: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]: ...


class GatewayResourceProvider:
    """把业务资源名映射到店铺网关，不让 Runtime 绑定具体平台 SDK。"""

    def __init__(self, gateway: EcommerceGateway) -> None:
        self.gateway = gateway

    def fetch(self, resource_id: str, ctx: ModuleContext) -> Any:
        arguments = dict(ctx.dynamic_context.get("resource_arguments", {}).get(resource_id, {}))
        calls = {
            "order_status": lambda: self.gateway.get_order(arguments),
            "logistics_status": lambda: self.gateway.get_logistics(arguments),
            "product_info": lambda: self.gateway.get_product(arguments),
            "shop_policy": lambda: self.gateway.get_shop_policy(arguments),
            "refund_sop": lambda: self.gateway.get_sop("refund", arguments),
            "after_sales_sop": lambda: self.gateway.get_sop("after_sales", arguments),
        }
        try:
            value = calls[resource_id]()
        except KeyError as exc:
            raise RuntimeFailure("RESOURCE_NOT_ALLOWLISTED", resource_id) from exc
        return validate_resource(resource_id, value)
