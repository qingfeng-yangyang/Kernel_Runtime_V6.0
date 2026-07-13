from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import PermissionFailure, ValidationFailure
from .media import MediaReference
from .security import reject_secrets, reject_unsafe_markup


@dataclass(frozen=True)
class DeliveryPayload:
    channel: str
    recipient: str
    text: str
    media: tuple[MediaReference, ...] = ()

    def validate(self) -> None:
        if self.channel not in {"email", "ecommerce_window", "webhook"}:
            raise ValidationFailure("INVALID_DELIVERY_CHANNEL", "Unsupported delivery channel")
        if not self.recipient or not self.text:
            raise ValidationFailure("INVALID_DELIVERY_PAYLOAD", "Recipient and text are required")
        reject_secrets({"recipient": self.recipient, "text": self.text})
        reject_unsafe_markup({"text": self.text})
        for item in self.media:
            item.validate()


class ChannelProvider(Protocol):
    def send(self, payload: DeliveryPayload, idempotency_key: str) -> dict[str, str]: ...


class MockChannelProvider:
    """Safe fake channel for CI; records no real external side effects."""

    def __init__(self) -> None:
        self.sent: dict[str, dict[str, str]] = {}

    def send(self, payload: DeliveryPayload, idempotency_key: str) -> dict[str, str]:
        payload.validate()
        if not idempotency_key:
            raise ValidationFailure("IDEMPOTENCY_REQUIRED", "Delivery idempotency key is required")
        if idempotency_key not in self.sent:
            self.sent[idempotency_key] = {
                "status": "sent",
                "provider_message_id": f"mock-{len(self.sent) + 1}",
            }
        return dict(self.sent[idempotency_key])


class DeliveryRouter:
    def __init__(self, providers: dict[str, ChannelProvider]) -> None:
        self.providers = dict(providers)

    def deliver(self, payload: DeliveryPayload, idempotency_key: str) -> dict[str, str]:
        payload.validate()
        provider = self.providers.get(payload.channel)
        if provider is None:
            raise PermissionFailure("DELIVERY_CHANNEL_DISABLED", "Delivery channel is not enabled")
        return provider.send(payload, idempotency_key)
