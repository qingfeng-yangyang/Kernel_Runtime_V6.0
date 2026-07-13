from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kernel_runtime.errors import RuntimeFailure
from kernel_runtime.models import ModuleContext

from .contracts import validate_resource


class PlaybackEcommerceProvider:
    """读取脱敏录制数据，最大限度复现店铺接口而不接触真实用户。"""

    def __init__(self, fixture_path: str | Path) -> None:
        path = Path(fixture_path)
        self.resources = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(self.resources, dict):
            raise RuntimeFailure("INVALID_PLAYBACK_FIXTURE", str(path))

    def fetch(self, resource_id: str, ctx: ModuleContext) -> Any:
        if resource_id not in self.resources:
            raise RuntimeFailure("PLAYBACK_RESOURCE_NOT_AVAILABLE", resource_id)
        return validate_resource(resource_id, self.resources[resource_id])
