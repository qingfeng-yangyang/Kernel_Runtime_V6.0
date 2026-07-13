from __future__ import annotations

from kernel_runtime.errors import RuntimeFailure
from kernel_runtime.models import ModuleContext, ModuleResult

from ..providers import BusinessResourceProvider, RuntimeResourceProvider


class WorkerModule:
    """纯代码 Worker；不调用 LLM。"""

    def __init__(self, provider: BusinessResourceProvider | None = None) -> None:
        self.provider = provider or RuntimeResourceProvider()

    def execute(self, ctx: ModuleContext) -> ModuleResult:
        group = ctx.business_store["plan"]["plan_request_group"]
        items = []
        for request in group["requests"]:
            resource_id = request["resource_id"]
            required = request.get("required", group.get("default_required", True))
            try:
                data = self.provider.fetch(resource_id, ctx)
                items.append({
                    "resource_id": resource_id,
                    "status": "success",
                    "required": required,
                    "data": data,
                })
            except RuntimeFailure as exc:
                items.append({
                    "resource_id": resource_id,
                    "status": "failed",
                    "required": required,
                    "error_code": exc.code,
                    "data": None,
                })
                if required:
                    raise
        return ModuleResult({"information": {"items": items}}, "worker execution completed")
