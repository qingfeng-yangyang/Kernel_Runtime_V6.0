from __future__ import annotations

import json

from kernel_runtime.envelope import EnvelopeValidator
from kernel_runtime.llm import (
    ArkOpenAICompatibleProvider,
    LLMClient,
    LLMRequest,
    TimeoutPolicy,
)


def main() -> None:
    envelope = {
        "stage": "DISPATCHING",
        "module": "Dispatcher",
        "output": {
            "dispatch_result": {
                "domain": "ecommerce",
            },
        },
        "log_content": {
            "status": "success",
            "event": "ark smoke completed",
            "error_code": None,
            "error_message": None,
        },
    }

    messages = [
        {
            "role": "system",
            "content": (
                "你是电商客服 Dispatcher。"
                "你只能输出一个严格 JSON 对象。"
                "禁止输出 Markdown、解释说明、代码块、XML、HTML。"
                "禁止输出尖括号字符。"
                "输出必须完全符合用户给出的 JSON 示例结构。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请原样输出这个 JSON 对象，不要增加任何内容：\n"
                + json.dumps(envelope, ensure_ascii=False)
            ),
        },
    ]

    response = LLMClient(ArkOpenAICompatibleProvider()).generate(
        LLMRequest.create(
            "ep-20260628222322-mstpq",
            messages,
            {"type": "object"},
            {"smoke": "ark_minimal_envelope"},
        ),
        TimeoutPolicy(
            connect_seconds=10,
            first_response_seconds=60,
            idle_seconds=60,
            total_seconds=180,
        ),
    )

    validated = EnvelopeValidator().validate_raw(
        response.content,
        stage="DISPATCHING",
        module="Dispatcher",
        allowed_output_fields=("dispatch_result",),
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "provider_request_id": response.provider_request_id,
                "stage": "DISPATCHING",
                "module": "Dispatcher",
                "output": validated.output,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
