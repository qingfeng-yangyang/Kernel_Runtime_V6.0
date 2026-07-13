from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from applications.ecommerce import build_v5_fake_llm_application, seed_v5_resources
from kernel_runtime import Runtime, SQLiteRepository, TaskRequest
from kernel_runtime.production import InMemoryJobBackend, ProductionRuntimeService


SCENARIOS = ["请查询订单状态", "订单现在到哪里了", "请查询订单当前状态", "帮我看看物流", "这个订单怎么退款"]


def task(index: int) -> TaskRequest:
    return TaskRequest(
        "ecommerce_customer_service_v5", SCENARIOS[index % len(SCENARIOS)],
        {"user_id": f"load-user-{index % 20}", "shop_id": "load-shop"},
        {"application": "ecommerce_customer_service_v5", "channel": "sanitized_load_test"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="V6.0 零Token脱敏预生产压测")
    parser.add_argument("--tasks", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()
    repo = SQLiteRepository(":memory:")
    seed_v5_resources(repo)
    runtime = Runtime(repo)
    runtime.register(build_v5_fake_llm_application())
    service = ProductionRuntimeService(runtime, InMemoryJobBackend(), worker_count=args.concurrency, max_active_tasks=args.concurrency)
    service.start()
    started = time.perf_counter()

    def one(index: int):
        begin = time.perf_counter()
        # 20个会话会制造“同会话串行、不同会话并行”的真实争用形态。
        submitted = service.submit(task(index), f"session-{index % 20}", f"load-{index}")
        result = service.wait(submitted["job_id"], timeout=30)
        return result["status"], time.perf_counter() - begin, result.get("error")

    values = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(one, index) for index in range(args.tasks)]
        for future in as_completed(futures):
            values.append(future.result())
    service.stop()
    elapsed = time.perf_counter() - started
    latencies = sorted(value[1] for value in values)
    success = sum(value[0] == "COMPLETED" for value in values)
    error_statuses = {}
    error_samples = []
    for status, _, error in values:
        if status != "COMPLETED":
            error_statuses[status] = error_statuses.get(status, 0) + 1
            if error and len(error_samples) < 5:
                error_samples.append(error)
    percentile = lambda p: latencies[min(len(latencies) - 1, int((len(latencies) - 1) * p))] if latencies else 0
    report = {
        "version": "6.0.0", "mode": "fake_llm_sanitized_zero_token",
        "tasks": args.tasks, "concurrency": args.concurrency, "completed": success,
        "failed": args.tasks - success, "failure_statuses": error_statuses, "failure_samples": error_samples, "elapsed_seconds": round(elapsed, 4),
        "throughput_per_second": round(args.tasks / elapsed, 2) if elapsed else 0,
        "latency_seconds": {"mean": round(statistics.mean(latencies), 4), "p50": round(percentile(.50), 4), "p95": round(percentile(.95), 4), "p99": round(percentile(.99), 4)},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if success != args.tasks:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
