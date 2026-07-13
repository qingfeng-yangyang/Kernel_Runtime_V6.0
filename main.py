import json

from applications.ecommerce import build_v5_fake_llm_application, seed_v5_resources
from kernel_runtime import Runtime, SQLiteRepository, TaskRequest


repo = SQLiteRepository(":memory:")
seed_v5_resources(repo)
runtime = Runtime(repo)
runtime.register(build_v5_fake_llm_application())
result = runtime.submit(TaskRequest(
    application_id="ecommerce_customer_service_v5",
    input="请查询订单当前状态",
    trusted_identity={"user_id": "mock_user_001", "shop_id": "mock_shop_001"},
    trusted_environment={"channel": "github_actions_mock", "application": "ecommerce_customer_service_v5"},
))
print(json.dumps({
    "runtime": {
        "task_id": result["runtime_state"]["task_id"],
        "application_id": result["runtime_state"]["application_id"],
        "lifecycle": result["runtime_state"]["lifecycle"],
        "current_stage": result["runtime_state"]["current_stage"],
    },
    "message": result["business_store"].get("message"),
    "quality": result["business_store"].get("quality_result"),
    "runtime_audit_events": len(result["runtime_audit"]),
    "business_log_events": len(result["business_log"]),
}, ensure_ascii=False, indent=2))
