from __future__ import annotations

from typing import Any

from kernel_runtime.errors import RuntimeFailure
from kernel_runtime.models import ModuleContext


class MockEcommerceProvider:
    """独立测试使用；不连接真实店铺。"""

    def __init__(self, resources: dict[str, Any]) -> None:
        self.resources = dict(resources)

    def fetch(self, resource_id: str, ctx: ModuleContext) -> Any:
        if resource_id not in self.resources:
            raise RuntimeFailure("MOCK_RESOURCE_NOT_AVAILABLE", resource_id)
        return self.resources[resource_id]
