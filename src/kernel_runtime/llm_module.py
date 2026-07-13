from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .llm import LLMClient, LLMRequest, TimeoutPolicy
from .models import ModuleContext, ModuleResult


PromptBuilder = Callable[[ModuleContext], list[dict[str, str]]]


@dataclass
class LLMRuntimeModule:
    """Application-owned adapter; trusted identity/environment never enter prompts."""

    client: LLMClient
    model: str
    response_schema: dict[str, Any]
    prompt_builder: PromptBuilder
    timeout_policy: TimeoutPolicy
    business_event: str

    def execute(self, context: ModuleContext) -> ModuleResult:
        request = LLMRequest.create(
            model=self.model,
            messages=self.prompt_builder(context),
            response_schema=self.response_schema,
            metadata={
                "task_id": context.task_id,
                "application_id": context.application_id,
                "stage": context.stage_id,
                "attempt_no": context.attempt_no,
            },
        )
        response = self.client.generate(request, self.timeout_policy)
        return ModuleResult(response.content, self.business_event)

