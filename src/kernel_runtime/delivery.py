from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from uuid import uuid4

from .errors import PermissionFailure, RuntimeFailure, ValidationFailure
from .security import digest, reject_secrets


class DeliveryProvider(Protocol):
    def send(self, recipient: str, content: str, idempotency_key: str) -> dict[str, Any]: ...


class MockEmailProvider:
    def __init__(self) -> None:
        self.sent: dict[str, dict[str, Any]] = {}

    def send(self, recipient: str, content: str, idempotency_key: str) -> dict[str, Any]:
        if idempotency_key in self.sent:
            return self.sent[idempotency_key]
        result = {"provider_message_id": f"mock_{uuid4().hex}", "status": "delivered"}
        self.sent[idempotency_key] = result
        return result


@dataclass(frozen=True)
class DeliveryRequest:
    task_id: str
    recipient: str
    content: str


class DeliveryService:
    """Runtime-owned delivery. Agents cannot select recipients or call providers."""

    def __init__(self, repository, provider: DeliveryProvider, recipient_bindings: dict[str, str],
                 max_deliveries_per_recipient: int = 20):
        self.repo, self.provider, self.recipient_bindings = repository, provider, recipient_bindings
        self.max_deliveries_per_recipient = max_deliveries_per_recipient

    def create(self, request: DeliveryRequest) -> str:
        reject_secrets({"content": request.content})
        state = self.repo.state(request.task_id)
        user_id = json.loads(state["identity_json"]).get("user_id")
        expected = self.recipient_bindings.get(user_id)
        # Normal use resolves by user id; fallback is deliberately forbidden.
        if expected is None or expected != request.recipient:
            raise PermissionFailure("RECIPIENT_NOT_ALLOWED", "Recipient is not bound to trusted identity")
        return self.repo.create_delivery(request.task_id, request.recipient, digest(request.content), request.content)

    def approve(self, delivery_id: str, approver: str) -> None:
        self.repo.approve_delivery(delivery_id, approver)

    def reject(self, delivery_id: str) -> None:
        self.repo.mark_delivery(delivery_id, "REJECTED", None)

    def cancel(self, delivery_id: str) -> None:
        record = self.repo.delivery(delivery_id)
        if record["status"] in {"DELIVERED", "UNCERTAIN"}:
            raise PermissionFailure("DELIVERY_NOT_CANCELLABLE", record["status"])
        self.repo.mark_delivery(delivery_id, "CANCELLED", None)

    def expire(self, delivery_id: str) -> None:
        record = self.repo.delivery(delivery_id)
        if record["status"] not in {"APPROVAL_REQUIRED", "APPROVED"}:
            raise PermissionFailure("DELIVERY_NOT_EXPIRABLE", record["status"])
        self.repo.mark_delivery(delivery_id, "EXPIRED", None)

    def change_content(self, delivery_id: str, content: str) -> None:
        reject_secrets({"content": content})
        self.repo.update_delivery_content(delivery_id, content, digest(content))

    def send(self, delivery_id: str) -> dict[str, Any]:
        record = self.repo.delivery(delivery_id)
        if record["status"] == "DELIVERED":
            return {"provider_message_id": record["provider_message_id"], "status": "delivered"}
        if record["status"] != "APPROVED":
            raise PermissionFailure("APPROVAL_REQUIRED", "Delivery requires approval")
        if self.repo.delivery_count(record["recipient"]) >= self.max_deliveries_per_recipient:
            self.repo.mark_delivery(delivery_id, "FAILED", None)
            raise PermissionFailure("DELIVERY_RATE_LIMIT", "Recipient delivery limit reached")
        self.repo.mark_delivery(delivery_id, "SENDING", None)
        key = record["idempotency_key"]
        try:
            result = self.provider.send(record["recipient"], record["content"], key)
        except TimeoutError as exc:
            self.repo.mark_delivery(delivery_id, "UNCERTAIN", None)
            raise RuntimeFailure("DELIVERY_UNCERTAIN", "Provider outcome is unknown") from exc
        self.repo.mark_delivery(delivery_id, "DELIVERED", result["provider_message_id"])
        return result
