from kernel_runtime.models import ModuleContext

from ..v5_support import LLMAgent, envelope, load_package


def _response(ctx: ModuleContext):
    return envelope(
        "DISPATCHING",
        "Dispatcher",
        {"dispatch_result": {"domain": "ecommerce"}},
        "domain routed",
    )


class DispatcherAgent(LLMAgent):
    def __init__(self) -> None:
        super().__init__(
            load_package("dispatcher", "Dispatcher"),
            "DISPATCHING",
            "Dispatcher",
            ("dispatch_result",),
            _response,
        )
