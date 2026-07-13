from __future__ import annotations

from typing import Any

from kernel_runtime.envelope import EnvelopeValidator
from kernel_runtime.errors import ValidationFailure
from kernel_runtime.llm import LLMRequest
from kernel_runtime.models import ModuleContext, ModuleResult
from kernel_runtime.security import digest

from ..v5_support import envelope, llm_client, llm_model, llm_timeout, load_package


class CustomerAgent:
    """先锁定 Goal，再读取 SOP 并生成 Plan。"""

    def __init__(self) -> None:
        self.package = load_package("customer", "Customer Agent")
        self.validator = EnvelopeValidator()

    def _call(
        self,
        ctx: ModuleContext,
        dynamic: dict[str, Any],
        fake_envelope: dict[str, Any],
        fields: tuple[str, ...],
    ):
        response = llm_client(fake_envelope).generate(
            LLMRequest.create(
                llm_model("fake-customer-v5"),
                self.package.messages(dynamic, ctx.task_input),
                {"type": "object"},
                {"prompt_checksum": self.package.checksum},
            ),
            llm_timeout(),
            external_cancel=ctx.cancellation_event,
        )
        return self.validator.validate_raw(
            response.content,
            stage="CUSTOMER_PLANNING",
            module="Customer Agent",
            allowed_output_fields=fields,
        )

    def execute(self, ctx: ModuleContext) -> ModuleResult:
        goal = {"goal_id": "goal_v5", "description": "根据当前电商客服请求形成可验证答复"}
        needs_sop = "退款" in ctx.task_input or "售后" in ctx.task_input
        request = ({
            "resource_request_group": {
                "group_id": "customer_group_v5",
                "default_required": True,
                "requests": [{"resource_id": "refund_sop", "required": True}],
            }
        } if needs_sop else None)
        phase1 = envelope(
            "CUSTOMER_PLANNING",
            "Customer Agent",
            {"goal": goal, "resource_request": request},
            "customer goal locked",
        )
        dynamic = {
            "dispatch_result": ctx.business_store["dispatch_result"],
            "recent_conversation_context": ctx.dynamic_context.get("recent_conversation_context", []),
            "available_resource_hints": ["refund_sop", "order_status", "logistics_status"],
        }
        first = self._call(ctx, dynamic, phase1, ("goal", "resource_request"))
        locked_goal = first.output["goal"]
        locked_digest = digest(locked_goal)

        sop_reference = None
        sop_constraints = None
        if request:
            sop = ctx.resources.get("refund_sop")
            sop_reference = {"resource_id": "refund_sop", "version": sop["version"], "status": "used"}
            sop_constraints = sop.get("constraints", [])

        plan_resources = (
            [{"resource_id": "order_status", "required": True}]
            if needs_sop else [
                {"resource_id": "order_status", "required": True},
                {"resource_id": "logistics_status", "required": False},
            ]
        )
        plan = {
            "summary": "依据Goal采集完成答复所需的授权业务信息",
            "steps": [
                {
                    "step_id": f"step_{i + 1:03d}",
                    "action": "request_resource",
                    "resource_id": item["resource_id"],
                    "purpose": "采集授权业务信息",
                }
                for i, item in enumerate(plan_resources)
            ],
            "plan_request_group": {
                "group_id": "plan_group_v5",
                "default_required": True,
                "requests": plan_resources,
            },
        }
        phase2 = envelope(
            "CUSTOMER_PLANNING",
            "Customer Agent",
            {
                "resource_request": request,
                "sop_reference": sop_reference,
                "sop_constraints": sop_constraints,
                "plan": plan,
            },
            "customer planning completed",
        )
        dynamic.update({
            "locked_goal": locked_goal,
            "locked_goal_digest": locked_digest,
            "resource_responses": ({"refund_sop": sop_constraints} if request else {}),
            "sop_reference": sop_reference,
        })
        second = self._call(
            ctx,
            dynamic,
            phase2,
            ("resource_request", "sop_reference", "sop_constraints", "plan"),
        )
        if digest(locked_goal) != locked_digest:
            raise ValidationFailure("GOAL_MUTATION_REJECTED", "Locked goal changed")
        return ModuleResult({"goal": locked_goal, **second.output}, "customer planning completed")
