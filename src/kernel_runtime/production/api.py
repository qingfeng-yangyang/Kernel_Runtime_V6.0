import os
from typing import Any

from applications.ecommerce import build_v5_fake_llm_application, seed_v5_resources
from kernel_runtime.engine import Runtime
from kernel_runtime.models import TaskRequest
from kernel_runtime.persistence import SQLiteRepository

from .backend import InMemoryJobBackend, RedisJobBackend, SQLiteJobBackend
from .service import ProductionRuntimeService


def build_service() -> ProductionRuntimeService:
    repo = SQLiteRepository(os.getenv("RUNTIME_DB_PATH", "/tmp/kernel-runtime-v55.db"))
    seed_v5_resources(repo)
    runtime = Runtime(repo)
    runtime.register(build_v5_fake_llm_application())
    redis_url = os.getenv("REDIS_URL")
    backend = RedisJobBackend(redis_url) if redis_url else SQLiteJobBackend(os.getenv("JOB_DB_PATH", "/tmp/kernel-runtime-v56-jobs.db"))
    return ProductionRuntimeService(runtime, backend, worker_count=int(os.getenv("RUNTIME_WORKERS", "4")), max_active_tasks=int(os.getenv("RUNTIME_MAX_ACTIVE", "8")))


def create_app(service: ProductionRuntimeService | None = None):
    try:
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("Install the preproduction dependencies to run the HTTP API") from exc

    active = service or build_service()
    app = FastAPI(title="Kernel Runtime V6.0", version="6.0.0")

    class SubmitBody(BaseModel):
        input: str = Field(min_length=1, max_length=10000)
        session_id: str = Field(min_length=1, max_length=128)
        idempotency_key: str = Field(min_length=1, max_length=128)
        user_id: str = Field(min_length=1, max_length=128)
        shop_id: str = Field(min_length=1, max_length=128)

    @app.on_event("startup")
    def startup() -> None:
        active.start()

    @app.on_event("shutdown")
    def shutdown() -> None:
        active.stop()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "6.0.0"}

    @app.get("/v1/metrics")
    def metrics() -> dict[str, int]:
        return active.metrics.snapshot()

    @app.post("/v1/jobs")
    def submit(body: SubmitBody) -> dict[str, Any]:
        task = TaskRequest("ecommerce_customer_service_v5", body.input, {"user_id": body.user_id, "shop_id": body.shop_id}, {"application": "ecommerce_customer_service_v5", "channel": "http_api"})
        return active.submit(task, body.session_id, body.idempotency_key)

    @app.get("/v1/jobs/{job_id}")
    def status(job_id: str) -> dict[str, Any]:
        try:
            return active.status(job_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

    @app.post("/v1/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> dict[str, Any]:
        try:
            return {"job_id": job_id, "cancelled": active.cancel(job_id)}
        except Exception as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

    app.state.runtime_service = active
    return app


app = create_app() if os.getenv("CREATE_HTTP_APP", "true").lower() == "true" else None
