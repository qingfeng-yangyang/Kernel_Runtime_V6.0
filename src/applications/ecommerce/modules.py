from __future__ import annotations

from kernel_runtime.models import ModuleContext, ModuleResult


class Dispatcher:
    def execute(self, ctx: ModuleContext) -> ModuleResult:
        return ModuleResult({"dispatch_result": {"domain": "ecommerce"}}, "domain routed")


class Customer:
    def execute(self, ctx: ModuleContext) -> ModuleResult:
        refund = "退款" in ctx.task_input
        sop = ctx.resources.get("refund_sop") if refund else None
        resources = ["order_status"] if refund else ["order_status", "logistics_status"]
        return ModuleResult({
            "goal": {"description": "处理电商客户请求"},
            "plan": {"resources": resources, "summary": "读取授权业务资源并形成答复"},
            "sop_reference": ({"resource_id": "refund_sop", "version": sop["version"]} if sop else None),
        }, "customer plan created")


class Worker:
    def execute(self, ctx: ModuleContext) -> ModuleResult:
        facts = []
        for resource_id in ctx.business_store["plan"]["resources"]:
            facts.append({"resource_id": resource_id, "data": ctx.resources.get(resource_id)})
        return ModuleResult({"information": {"facts": facts}}, "business resources collected")


class Writer:
    def execute(self, ctx: ModuleContext) -> ModuleResult:
        facts = ctx.business_store["information"]["facts"]
        values = {item["resource_id"]: item["data"] for item in facts}
        order = values["order_status"]
        text = f"订单 {order['order_id']} 当前状态为{order['status']}。"
        if "logistics_status" in values:
            logistics = values["logistics_status"]
            text += f"物流状态为{logistics['status']}，最新进展：{logistics['last_event']}。"
        return ModuleResult({"result": {"content": text, "facts": facts},
                             "message": {"content": "您好，" + text}}, "response generated")


class Quality:
    def execute(self, ctx: ModuleContext) -> ModuleResult:
        result = ctx.business_store["result"]
        message = ctx.business_store["message"]
        information = ctx.business_store["information"]
        evidence = {x.get("resource_id") for x in information.get("facts", [])}
        result_evidence = {x.get("resource_id") for x in result.get("facts", [])}
        passed = bool(result.get("content") and result.get("facts") and message.get("content"))
        passed = passed and result_evidence.issubset(evidence)
        forbidden = ("api_key", "authorization", "cookie", "password", "secret")
        passed = passed and not any(word in message["content"].lower() for word in forbidden)
        if not passed:
            return ModuleResult({}, "quality failed", "failed", "QUALITY_FAILED", "Missing evidence")
        return ModuleResult({"quality_result": {"status": "pass", "score": 100, "issues": []}},
                            "quality passed")
