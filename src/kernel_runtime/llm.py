from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from uuid import uuid4

from .errors import (
    CancelledFailure,
    ProviderAuthenticationFailure,
    ProviderContentRejected,
    ProviderRateLimitFailure,
    ProviderTemporaryFailure,
    TimeoutFailure,
    ValidationFailure,
)


@dataclass(frozen=True)
class TimeoutPolicy:
    connect_seconds: float = 10.0
    first_response_seconds: float = 30.0
    idle_seconds: float = 30.0
    total_seconds: float = 120.0


@dataclass(frozen=True)
class LLMRequest:
    request_id: str
    model: str
    messages: tuple[dict[str, str], ...]
    response_schema: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ):
        return cls(f"llm_{uuid4().hex}", model, tuple(messages), response_schema, metadata or {})


@dataclass(frozen=True)
class LLMResponse:
    request_id: str
    content: dict[str, Any]
    provider_request_id: str
    finish_reason: str = "stop"


class LLMProvider(Protocol):
    def stream(
        self,
        request: LLMRequest,
        emit: Callable[[str, Any], None],
        cancelled: threading.Event,
    ) -> None: ...

    def cancel(self, request_id: str) -> None: ...


class LLMClient:
    """Provider-neutral layered timeouts and cooperative/server cancellation."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def generate(
        self,
        request: LLMRequest,
        policy: TimeoutPolicy,
        external_cancel: threading.Event | None = None,
    ) -> LLMResponse:
        events: queue.Queue[tuple[str, Any, float]] = queue.Queue()
        cancelled = external_cancel or threading.Event()

        def emit(kind: str, payload: Any = None) -> None:
            events.put((kind, payload, time.monotonic()))

        def run() -> None:
            try:
                self.provider.stream(request, emit, cancelled)
            except BaseException as exc:
                emit("error", exc)

        threading.Thread(target=run, daemon=True).start()
        started = time.monotonic()
        connected_at: float | None = None
        first_at: float | None = None
        last_progress = started
        chunks: list[str] = []

        while True:
            now = time.monotonic()
            if cancelled.is_set():
                self._cancel(request.request_id, cancelled)
                raise CancelledFailure("LLM_CANCELLED", "LLM request cancelled")
            if now - started >= policy.total_seconds:
                self._cancel(request.request_id, cancelled)
                raise TimeoutFailure("LLM_TOTAL_TIMEOUT", "LLM total timeout exceeded")
            if connected_at is None:
                remaining = min(
                    policy.connect_seconds - (now - started),
                    policy.total_seconds - (now - started),
                )
                timeout_code = "LLM_CONNECT_TIMEOUT"
            elif first_at is None:
                remaining = min(
                    policy.first_response_seconds - (now - connected_at),
                    policy.total_seconds - (now - started),
                )
                timeout_code = "LLM_FIRST_RESPONSE_TIMEOUT"
            else:
                remaining = min(
                    policy.idle_seconds - (now - last_progress),
                    policy.total_seconds - (now - started),
                )
                timeout_code = "LLM_IDLE_TIMEOUT"
            if remaining <= 0:
                self._cancel(request.request_id, cancelled)
                raise TimeoutFailure(timeout_code, "LLM timed out")
            try:
                kind, payload, timestamp = events.get(timeout=min(remaining, 0.01))
            except queue.Empty:
                if cancelled.is_set():
                    self._cancel(request.request_id, cancelled)
                    raise CancelledFailure("LLM_CANCELLED", "LLM request cancelled")
                continue
            if kind == "connected":
                connected_at = timestamp
                last_progress = timestamp
            elif kind == "chunk":
                if connected_at is None:
                    connected_at = timestamp
                if first_at is None:
                    first_at = timestamp
                last_progress = timestamp
                chunks.append(str(payload))
            elif kind == "done":
                try:
                    content = json.loads("".join(chunks))
                except json.JSONDecodeError as exc:
                    raise ValidationFailure("LLM_INVALID_JSON", "LLM response is not valid JSON") from exc
                if not isinstance(content, dict):
                    raise ValidationFailure("LLM_SCHEMA_FAILED", "LLM response must be an object")
                return LLMResponse(request.request_id, content, str(payload or request.request_id))
            elif kind == "error":
                if isinstance(payload, BaseException):
                    raise payload
                raise ProviderTemporaryFailure("LLM_PROVIDER_ERROR", str(payload))

    def _cancel(self, request_id: str, cancelled: threading.Event) -> None:
        cancelled.set()
        try:
            self.provider.cancel(request_id)
        except Exception:
            pass


class FakeLLMProvider:
    """Deterministic provider used only for CI and security/failure tests."""

    def __init__(
        self,
        response: dict[str, Any] | None = None,
        *,
        connect_delay: float = 0,
        first_delay: float = 0,
        chunk_delay: float = 0,
        fault: str | None = None,
    ) -> None:
        self.response = response or {"status": "ok"}
        self.connect_delay = connect_delay
        self.first_delay = first_delay
        self.chunk_delay = chunk_delay
        self.fault = fault
        self.cancelled_ids: set[str] = set()

    def _wait(self, seconds: float, cancelled: threading.Event) -> bool:
        return cancelled.wait(seconds)

    def stream(
        self,
        request: LLMRequest,
        emit: Callable[[str, Any], None],
        cancelled: threading.Event,
    ) -> None:
        if self._wait(self.connect_delay, cancelled):
            return
        if self.fault == "auth":
            raise ProviderAuthenticationFailure("LLM_AUTH_FAILED", "Authentication failed")
        if self.fault == "rate_limit":
            raise ProviderRateLimitFailure("LLM_RATE_LIMIT", "Rate limited")
        if self.fault == "temporary":
            raise ProviderTemporaryFailure("LLM_TEMPORARY", "Temporary failure")
        if self.fault == "content":
            raise ProviderContentRejected("LLM_CONTENT_REJECTED", "Content rejected")
        emit("connected")
        if self._wait(self.first_delay, cancelled):
            return
        raw = json.dumps(self.response, ensure_ascii=False)
        midpoint = max(1, len(raw) // 2)
        emit("chunk", raw[:midpoint])
        if self._wait(self.chunk_delay, cancelled):
            return
        emit("chunk", raw[midpoint:])
        emit("done", f"fake_{request.request_id}")

    def cancel(self, request_id: str) -> None:
        self.cancelled_ids.add(request_id)


class ArkOpenAICompatibleProvider:
    """Volcengine Ark provider through the OpenAI-compatible SDK."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url or os.getenv(
            "ARK_BASE_URL",
            "https://ark.cn-beijing.volces.com/api/v3",
        )
        self.api_key = api_key or os.getenv("ARK_API_KEY")
        self.cancelled_ids: set[str] = set()

    def stream(
        self,
        request: LLMRequest,
        emit: Callable[[str, Any], None],
        cancelled: threading.Event,
    ) -> None:
        if not self.api_key:
            raise ProviderAuthenticationFailure(
                "LLM_AUTH_FAILED",
                "ARK_API_KEY is missing",
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderTemporaryFailure(
                "LLM_SDK_MISSING",
                "openai package is not installed",
            ) from exc

        emit("connected")

        if cancelled.is_set():
            return

        try:
            client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )
            response = client.responses.create(
                model=request.model,
                input=[
                    {
                        "role": message["role"],
                        "content": message["content"],
                    }
                    for message in request.messages
                ],
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            message = str(exc)

            if status in {401, 403}:
                raise ProviderAuthenticationFailure(
                    "LLM_AUTH_FAILED",
                    "Ark authentication failed",
                ) from exc

            if status == 429:
                raise ProviderRateLimitFailure(
                    "LLM_RATE_LIMIT",
                    "Ark rate limit exceeded",
                ) from exc

            if isinstance(status, int) and 400 <= status < 500:
                raise ProviderContentRejected(
                    "LLM_CONTENT_REJECTED",
                    message,
                ) from exc

            raise ProviderTemporaryFailure(
                "LLM_PROVIDER_ERROR",
                message,
            ) from exc

        if cancelled.is_set():
            return

        raw = getattr(response, "output_text", None)
        if not raw:
            dumped = response.model_dump() if hasattr(response, "model_dump") else {}
            raw = self._extract_text(dumped)

        if not raw:
            raise ProviderTemporaryFailure(
                "LLM_EMPTY_RESPONSE",
                "Ark returned empty text",
            )

        emit("chunk", raw)
        emit("done", getattr(response, "id", request.request_id))

    def cancel(self, request_id: str) -> None:
        self.cancelled_ids.add(request_id)

    def _extract_text(self, value: Any) -> str:
        if isinstance(value, dict):
            if (
                value.get("type") in {"output_text", "text"}
                and isinstance(value.get("text"), str)
            ):
                return value["text"]

            for child in value.values():
                found = self._extract_text(child)
                if found:
                    return found

        elif isinstance(value, list):
            for child in value:
                found = self._extract_text(child)
                if found:
                    return found

        return ""
