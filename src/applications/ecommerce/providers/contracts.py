from __future__ import annotations

from typing import Any

from kernel_runtime.errors import RuntimeFailure


ALLOWED_RESOURCE_IDS = frozenset({
    "order_status",
    "logistics_status",
    "product_info",
    "shop_policy",
    "refund_sop",
    "after_sales_sop",
})


def validate_resource(resource_id: str, value: Any) -> Any:
    """电商边界校验；Runtime 只接收已登记、结构可验证的业务数据。"""
    if resource_id not in ALLOWED_RESOURCE_IDS:
        raise RuntimeFailure("RESOURCE_NOT_ALLOWLISTED", resource_id)
    if not isinstance(value, dict):
        raise RuntimeFailure("INVALID_RESOURCE_SCHEMA", resource_id)
    required: dict[str, tuple[str, ...]] = {
        "order_status": ("order_id", "status"),
        "logistics_status": ("status", "last_event"),
        "product_info": ("product_id", "name"),
        "shop_policy": ("policy_id", "content"),
        "refund_sop": ("version", "constraints"),
        "after_sales_sop": ("version", "constraints"),
    }
    missing = [name for name in required[resource_id] if name not in value]
    if missing:
        raise RuntimeFailure("INVALID_RESOURCE_SCHEMA", f"{resource_id}:{','.join(missing)}")
    return value
