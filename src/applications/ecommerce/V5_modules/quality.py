from kernel_runtime.models import ModuleContext

from ..v5_support import LLMAgent, envelope, load_package


def _response(ctx: ModuleContext):
    return envelope(
        "QUALITY_CHECKING",
        "Quality",
        {"quality_result": {"status": "pass", "score": 100, "issues": []}},
        "quality check completed",
    )


class QualityAgent(LLMAgent):
    def __init__(self) -> None:
        super().__init__(
            load_package("quality", "Quality"),
            "QUALITY_CHECKING",
            "Quality",
            ("quality_result",),
            _response,
        )
