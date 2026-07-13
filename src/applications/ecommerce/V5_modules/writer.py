from kernel_runtime.models import ModuleContext

from ..v5_support import LLMAgent, envelope, load_package


def _response(ctx: ModuleContext):
    items = ctx.business_store["information"]["items"]
    success = [item for item in items if item["status"] == "success"]
    order = next((item["data"] for item in success if item["resource_id"] == "order_status"), None)
    logistics = next((item["data"] for item in success if item["resource_id"] == "logistics_status"), None)
    if not order:
        result = {
            "status": "insufficient_information",
            "content": None,
            "evidence_refs": [],
            "missing_information": ["order_status"],
        }
        message = {"status": "insufficient_information", "content": "当前订单信息不足，请稍后重试。"}
    else:
        content = f"订单 {order['order_id']} 当前状态为{order['status']}。"
        refs = ["order_status"]
        if logistics:
            content += f"物流状态为{logistics['status']}，最新进展为{logistics['last_event']}。"
            refs.append("logistics_status")
        result = {"status": "success", "content": content, "evidence_refs": refs}
        message = {"status": "success", "content": "您好，" + content}
    return envelope(
        "WRITER_GENERATING",
        "Writer",
        {"result": result, "message": message},
        "writer generation completed",
    )


class WriterAgent(LLMAgent):
    def __init__(self) -> None:
        super().__init__(
            load_package("writer", "Writer"),
            "WRITER_GENERATING",
            "Writer",
            ("result", "message"),
            _response,
        )
