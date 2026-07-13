from __future__ import annotations

import threading
import time
from typing import Any

from kernel_runtime.errors import RuntimeFailure
from kernel_runtime.models import ModuleContext

from .contracts import validate_resource


class ResilientEcommerceProvider:
    """统一提供超时、有限重试、并发上限和返回结构校验。"""

    def __init__(self, provider, timeout_seconds: float = 3, retries: int = 1, max_concurrency: int = 16) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.capacity = threading.BoundedSemaphore(max_concurrency)

    def fetch(self, resource_id: str, ctx: ModuleContext) -> Any:
        last: BaseException | None = None
        for attempt in range(self.retries + 1):
            result: list[Any] = []
            error: list[BaseException] = []

            def call() -> None:
                try:
                    result.append(self.provider.fetch(resource_id, ctx))
                except BaseException as exc:
                    error.append(exc)

            with self.capacity:
                thread = threading.Thread(target=call, daemon=True)
                thread.start()
                thread.join(self.timeout_seconds)
            if thread.is_alive():
                last = RuntimeFailure("RESOURCE_TIMEOUT", resource_id)
            elif error:
                last = error[0]
            else:
                return validate_resource(resource_id, result[0])
            if attempt < self.retries:
                time.sleep(min(.05 * (2 ** attempt), .2))
        if isinstance(last, RuntimeFailure):
            raise last
        raise RuntimeFailure("RESOURCE_PROVIDER_FAILED", str(last))
