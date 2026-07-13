from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .errors import ProviderAuthenticationFailure, RuntimeFailure


@dataclass(frozen=True)
class ResourceCall:
    task_id: str
    application_id: str
    resource_id: str
    trusted_identity: dict[str, str]
    trusted_environment: dict[str, str]


class ResourceProviderAdapter(Protocol):
    def fetch(self, call: ResourceCall) -> Any: ...


class DisabledRealProvider:
    """Safe default placeholder for store APIs, SOP and History services."""
    def fetch(self, call: ResourceCall) -> Any:
        raise ProviderAuthenticationFailure("REAL_PROVIDER_DISABLED", "Real provider is disabled")


class MappingProvider:
    def __init__(self, resources: dict[str, Any]) -> None:
        self.resources = resources

    def fetch(self, call: ResourceCall) -> Any:
        if call.resource_id not in self.resources:
            raise RuntimeFailure("RESOURCE_NOT_FOUND", call.resource_id)
        return self.resources[call.resource_id]

