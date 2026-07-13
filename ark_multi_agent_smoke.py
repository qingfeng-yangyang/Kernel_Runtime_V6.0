from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kernel_runtime.envelope import EnvelopeValidator
from kernel_runtime.errors import RuntimeFailure
from kernel_runtime.llm import (
    ArkOpenAICompatibleProvider,
    LLMClient,
    LLMRequest,
    TimeoutPolicy,
)


MODEL = "ep-20260628222322-mstpq"
PROMPT_ROOT = Path(__file__).parent / "src" / "applications" / "ecommerce" / "prompts"


SCENARIOS = [
    {
        "name": "order_query",
        "task_input": "请帮我查询订单 ORDER-DEMO-001 当前状态",
        "expected_domain": "ecommerce",
    },
    {
        "name": "logistics_query",
        "task_input": "我的包裹现在到哪里了？订单号 ORDER-DEMO-001",
        "expected_domain": "ecommerce",
    },
    {
        "name": "product_question",
        "task_input": "这款商品支持七天无理由退货吗？",
        "expected_domain": "ecommerce",
    },
    {
        "name": "refund_question",
        "task_input": "订单 ORDER-DEMO-001 我想退款，需要怎么处理？",
        "expected_domain": "ecommerce",
    },
    {
        "name": "after_sales_question",
        "task_input": "商品收到后有破损，售后怎么处理？",
        "expected_domain": "ecommerce",
    },
    {
        "name": "shop_policy_question",
        "task_input": "你们店铺发货和退换货政策是什么？",
        "expected_domain": "ecommerce",
    },
]


def _read_prompt(name: str) -> str:
    return (PROMPT_ROOT / f"{name}_prompt.txt").read_text(encoding="utf-8")


def _json_instruction(stage: str, module: str, example_output: dict[str, Any]) -> str:
    return (
        "你必须只输出一个严格 JSON 对象。"
        "禁止输出 Markdown、解释说明、代码块、XML、HTML。"
        "禁止输出尖括号字符。"
        "禁止在 JSON 前后添加任何文本。"
        "log_content 必须是顶层字段，禁止放入 output。"
        "output 只能包含示例 output 中列出的字段。"
        f"stage 必须是 {stage}。"
        f"module 必须是 {module}。"
        "输出结构必须符合下面示例，但内容要根据当前输入生成：\n"
        + json.dumps(example_output, ensure_ascii=False, indent=2)
    )


def _call_llm(
    *,
    agent: str,
    model: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    response = LLMClient(ArkOpenAICompatibleProvider()).generate(
        LLMRequest.create(
            model,
            messages,
            {"type": "object"},
            {"smoke": f"ark_multi_agent_generated_{agent}"},
        ),
        TimeoutPolicy(
            connect_seconds=10,
            first_response_seconds=60,
            idle_seconds=60,
            total_seconds=180,
        ),
    )
    return {
        "provider_request_id": response.provider_request_id,
        "content": response.content,
    }


def _validate(
    *,
    content: dict[str, Any],
    stage: str,
    module: str,
    allowed_output_fields: tuple[str, ...],
):
    return EnvelopeValidator().validate_raw(
        content,
        stage=stage,
        module=module,
        allowed_output_fields=allowed_output_fields,
    )


def _fail(
    *,
    scenario: str,
    agent: str,
    stage: str,
    error: BaseException,
    raw_content: Any | None = None,
) -> dict[str, Any]:
    item = {
        "scenario": scenario,
        "agent": agent,
        "stage": stage,
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    if raw_content is not None:
        item["raw_top_level_keys"] = (
            list(raw_content.keys()) if isinstance(raw_content, dict) else None
        )
        item["raw_stage"] = raw_content.get("stage") if isinstance(raw_content, dict) else None
        item["raw_module"] = raw_content.get("module") if isinstance(raw_content, dict) else None
        item["raw_output_keys"] = (
            list(raw_content.get("output", {}).keys())
            if isinstance(raw_content, dict) and isinstance(raw_content.get("output"), dict)
            else None
        )
    return item


def _dispatcher(scenario: dict[str, Any]) -> dict[str, Any]:
    stage = "DISPATCHING"
    module = "Dispatcher"
    example = {
        "stage": stage,
        "module": module,
        "output": {
            "dispatch_result": {
                "domain": "ecommerce",
            },
        },
        "log_content": {
            "status": "success",
            "event": "domain routed",
            "error_code": None,
            "error_message": None,
        },
    }
    messages = [
        {"role": "system", "content": _read_prompt("dispatcher")},
        {
            "role": "user",
            "content": _json_instruction(stage, module, example)
            + "\n当前用户输入："
            + scenario["task_input"],
        },
    ]
    raw = _call_llm(agent=module, model=MODEL, messages=messages)
    validated = _validate(
        content=raw["content"],
        stage=stage,
        module=module,
        allowed_output_fields=("dispatch_result",),
    )
    return {
        "agent": module,
        "stage": stage,
        "provider_request_id": raw["provider_request_id"],
        "output": validated.output,
    }


def _customer(scenario: dict[str, Any], dispatch_result: dict[str, Any]) -> dict[str, Any]:
    stage = "CUSTOMER_PLANNING"
    module = "Customer Agent"
    example = {
        "stage": stage,
        "module": module,
        "output": {
            "goal": {
                "goal_id": "goal_smoke",
                "description": "根据用户输入形成可验证的电商客服目标",
            },
            "resource_request": None,
            "sop_reference": None,
            "sop_constraints": None,
            "plan": {
                "summary": "采集完成答复所需的授权业务信息",
                "steps": [
                    {
                        "step_id": "step_001",
                        "action": "request_resource",
                        "resource_id": "order_status",
                        "purpose": "采集订单状态",
                    }
                ],
                "plan_request_group": {
                    "group_id": "plan_group_smoke",
                    "default_required": True,
                    "requests": [
                        {
                            "resource_id": "order_status",
                            "required": True,
                        }
                    ],
                },
            },
        },
        "log_content": {
            "status": "success",
            "event": "customer planning completed",
            "error_code": None,
            "error_message": None,
        },
    }
    messages = [
        {"role": "system", "content": _read_prompt("customer")},
        {
            "role": "user",
            "content": _json_instruction(stage, module, example)
            + "\n当前用户输入："
            + scenario["task_input"]
            + "\nDispatcher 输出："
            + json.dumps(dispatch_result, ensure_ascii=False),
        },
    ]
    raw = _call_llm(agent=module, model=MODEL, messages=messages)

    try:
        validated = _validate(
            content=raw["content"],
            stage=stage,
            module=module,
            allowed_output_fields=(
                "goal",
                "resource_request",
                "sop_reference",
                "sop_constraints",
                "plan",
            ),
        )
    except BaseException as exc:
        raise RuntimeError(
            json.dumps(
                {
                    "customer_raw_top_level_keys": list(raw["content"].keys())
                    if isinstance(raw["content"], dict)
                    else None,
                    "customer_raw_stage": raw["content"].get("stage")
                    if isinstance(raw["content"], dict)
                    else None,
                    "customer_raw_module": raw["content"].get("module")
                    if isinstance(raw["content"], dict)
                    else None,
                    "customer_raw_output_keys": list(raw["content"].get("output", {}).keys())
                    if isinstance(raw["content"], dict)
                    and isinstance(raw["content"].get("output"), dict)
                    else None,
                    "original_error": str(exc),
                },
                ensure_ascii=False,
            )
        ) from exc
    return {
        "agent": module,
        "stage": stage,
        "provider_request_id": raw["provider_request_id"],
        "output": validated.output,
    }


def _mock_information(customer_output: dict[str, Any]) -> dict[str, Any]:
    plan = customer_output.get("plan") or {}
    group = plan.get("plan_request_group") or {}
    requests = group.get("requests") or []

    items = []
    for request in requests:
        resource_id = request.get("resource_id")
        required = bool(request.get("required", group.get("default_required", True)))
        if resource_id == "order_status":
            items.append(
                {
                    "resource_id": "order_status",
                    "status": "success",
                    "required": required,
                    "data": {
                        "order_id": "ORDER-DEMO-001",
                        "status": "运输中",
                    },
                }
            )
        elif resource_id == "logistics_status":
            items.append(
                {
                    "resource_id": "logistics_status",
                    "status": "success",
                    "required": required,
                    "data": {
                        "status": "运输中",
                        "last_event": "包裹已到达转运中心",
                    },
                }
            )
        elif resource_id == "refund_sop":
            items.append(
                {
                    "resource_id": "refund_sop",
                    "status": "success",
                    "required": required,
                    "data": {
                        "version": "mock-v1",
                        "constraints": ["退款前必须核验订单状态"],
                    },
                }
            )
        else:
            items.append(
                {
                    "resource_id": resource_id,
                    "status": "failed",
                    "required": required,
                    "data": None,
                    "error_code": "MOCK_RESOURCE_NOT_AVAILABLE",
                }
            )

    return {"items": items}


def _writer(
    scenario: dict[str, Any],
    customer_output: dict[str, Any],
    information: dict[str, Any],
) -> dict[str, Any]:
    stage = "WRITER_GENERATING"
    module = "Writer"
    example = {
        "stage": stage,
        "module": module,
        "output": {
            "result": {
                "status": "success",
                "content": "基于 evidence 生成的事实性结果",
                "evidence_refs": ["order_status"],
            },
            "message": {
                "status": "success",
                "content": "面向用户的客服回复",
            },
        },
        "log_content": {
            "status": "success",
            "event": "writer generation completed",
            "error_code": None,
            "error_message": None,
        },
    }
    messages = [
        {"role": "system", "content": _read_prompt("writer")},
        {
            "role": "user",
            "content": _json_instruction(stage, module, example)
            + "\n当前用户输入："
            + scenario["task_input"]
            + "\nGoal/Plan："
            + json.dumps(customer_output, ensure_ascii=False)
            + "\nInformation："
            + json.dumps(information, ensure_ascii=False),
        },
    ]
    raw = _call_llm(agent=module, model=MODEL, messages=messages)
    validated = _validate(
        content=raw["content"],
        stage=stage,
        module=module,
        allowed_output_fields=("result", "message"),
    )
    return {
        "agent": module,
        "stage": stage,
        "provider_request_id": raw["provider_request_id"],
        "output": validated.output,
    }


def _quality(
    scenario: dict[str, Any],
    customer_output: dict[str, Any],
    information: dict[str, Any],
    writer_output: dict[str, Any],
) -> dict[str, Any]:
    stage = "QUALITY_CHECKING"
    module = "Quality"
    example = {
        "stage": stage,
        "module": module,
        "output": {
            "quality_result": {
                "status": "pass",
                "score": 100,
                "issues": [],
            },
        },
        "log_content": {
            "status": "success",
            "event": "quality check completed",
            "error_code": None,
            "error_message": None,
        },
    }
    messages = [
        {"role": "system", "content": _read_prompt("quality")},
        {
            "role": "user",
            "content": _json_instruction(stage, module, example)
            + "\n当前用户输入："
            + scenario["task_input"]
            + "\nGoal/Plan："
            + json.dumps(customer_output, ensure_ascii=False)
            + "\nInformation："
            + json.dumps(information, ensure_ascii=False)
            + "\nWriter 输出："
            + json.dumps(writer_output, ensure_ascii=False),
        },
    ]
    raw = _call_llm(agent=module, model=MODEL, messages=messages)
    validated = _validate(
        content=raw["content"],
        stage=stage,
        module=module,
        allowed_output_fields=("quality_result",),
    )
    return {
        "agent": module,
        "stage": stage,
        "provider_request_id": raw["provider_request_id"],
        "output": validated.output,
    }


def run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    failures = []
    agents = []

    try:
        dispatcher = _dispatcher(scenario)
        agents.append(dispatcher)
    except BaseException as exc:
        failures.append(
            _fail(
                scenario=scenario["name"],
                agent="Dispatcher",
                stage="DISPATCHING",
                error=exc,
            )
        )
        return {"scenario": scenario["name"], "status": "failed", "agents": agents, "failures": failures}

    try:
        customer = _customer(scenario, dispatcher["output"])
        agents.append(customer)
    except BaseException as exc:
        failures.append(
            _fail(
                scenario=scenario["name"],
                agent="Customer Agent",
                stage="CUSTOMER_PLANNING",
                error=exc,
            )
        )
        return {"scenario": scenario["name"], "status": "failed", "agents": agents, "failures": failures}

    information = _mock_information(customer["output"])

    try:
        writer = _writer(scenario, customer["output"], information)
        agents.append(writer)
    except BaseException as exc:
        failures.append(
            _fail(
                scenario=scenario["name"],
                agent="Writer",
                stage="WRITER_GENERATING",
                error=exc,
            )
        )
        return {
            "scenario": scenario["name"],
            "status": "failed",
            "agents": agents,
            "information": information,
            "failures": failures,
        }

    try:
        quality = _quality(scenario, customer["output"], information, writer["output"])
        agents.append(quality)
    except BaseException as exc:
        failures.append(
            _fail(
                scenario=scenario["name"],
                agent="Quality",
                stage="QUALITY_CHECKING",
                error=exc,
            )
        )
        return {
            "scenario": scenario["name"],
            "status": "failed",
            "agents": agents,
            "information": information,
            "failures": failures,
        }

    return {
        "scenario": scenario["name"],
        "status": "ok",
        "agents": agents,
        "information": information,
        "failures": failures,
    }


def main() -> None:
    results = [run_scenario(scenario) for scenario in SCENARIOS]
    failures = [result for result in results if result["status"] != "ok"]

    output = {
        "status": "ok" if not failures else "failed",
        "scenario_count": len(results),
        "failed_count": len(failures),
        "results": results,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
