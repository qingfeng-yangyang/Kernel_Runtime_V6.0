from __future__ import annotations

from typing import Any, Protocol

from kernel_runtime.models import ModuleContext


class BusinessResourceProvider(Protocol):
    """Worker 读取业务资源的统一入口。"""

    def fetch(self, resource_id: str, ctx: ModuleContext) -> Any: ...


class RuntimeResourceProvider:
    """将 Runtime 已授权的资源访问器适配成业务资源接口。"""

    def fetch(self, resource_id: str, ctx: ModuleContext) -> Any:
        return ctx.resources.get(resource_id)
