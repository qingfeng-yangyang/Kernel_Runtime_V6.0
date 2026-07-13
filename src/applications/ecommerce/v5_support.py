from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from kernel_runtime.envelope import EnvelopeValidator
from kernel_runtime.llm import (
    ArkOpenAICompatibleProvider,
    FakeLLMProvider,
    LLMClient,
    LLMRequest,
    TimeoutPolicy,
)
from kernel_runtime.models import ModuleContext, ModuleResult
from kernel_runtime.prompt_package import PromptPackage


PROMPT_ROOT = Path(__file__).parent / "prompts"


def real_llm_enabled() -> bool:
    return os.getenv("REAL_LLM_ENABLED", "false").lower() == "true"


def llm_model(fake_model: str) -> str:
    return os.getenv("LLM_MODEL", fake_model) if real_llm_enabled() else fake_model


def llm_client(fake_envelope: dict[str, Any]) -> LLMClient:
    if real_llm_enabled() and os.getenv("LLM_PROVIDER", "fake") == "ark_openai_compatible":
        return LLMClient(ArkOpenAICompatibleProvider())
    return LLMClient(FakeLLMProvider(fake_envelope))


def llm_timeout() -> TimeoutPolicy:
    if not real_llm_enabled():
        return TimeoutPolicy(.2, .2, .2, 1)
    return TimeoutPolicy(
        connect_seconds=float(os.getenv("LLM_CONNECT_TIMEOUT", "10")),
        first_response_seconds=float(os.getenv("LLM_FIRST_RESPONSE_TIMEOUT", "60")),
        idle_seconds=float(os.getenv("LLM_IDLE_TIMEOUT", "60")),
        total_seconds=float(os.getenv("LLM_TOTAL_TIMEOUT", "180")),
    )


def load_package(name: str, module_id: str) -> PromptPackage:
    return PromptPackage.load_compiled(
        PROMPT_ROOT / f"{name}_prompt.txt",
        prompt_id=f"ecommerce.{name}",
        version="1.0.1-v5",
        application_id="ecommerce_customer_service_v5",
        module_id=module_id,
    )


def envelope(stage: str, module: str, output: dict[str, Any], event: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "module": module,
        "output": output,
        "log_content": {
            "status": "success",
            "event": event,
            "error_code": None,
            "error_message": None,
        },
    }


class LLMAgent:
    """电商 LLM 模块的统一代码外壳。"""

    def __init__(
        self,
        package: PromptPackage,
        stage: str,
        module: str,
        fields: tuple[str, ...],
        response_builder: Callable[[ModuleContext], dict[str, Any]],
    ) -> None:
        self.package = package
        self.stage = stage
        self.module = module
        self.fields = fields
        self.response_builder = response_builder
        self.validator = EnvelopeValidator()

    def execute(self, ctx: ModuleContext) -> ModuleResult:
        dynamic = dict(ctx.dynamic_context)
        dynamic.update(ctx.business_store)
        response = llm_client(self.response_builder(ctx)).generate(
            LLMRequest.create(
                llm_model("fake-ecommerce-v5"),
                self.package.messages(dynamic, ctx.task_input),
                {"type": "object"},
                {"prompt_checksum": self.package.checksum},
            ),
            llm_timeout(),
            external_cancel=ctx.cancellation_event,
        )
        return self.validator.validate_raw(
            response.content,
            stage=self.stage,
            module=self.module,
            allowed_output_fields=self.fields,
        )
