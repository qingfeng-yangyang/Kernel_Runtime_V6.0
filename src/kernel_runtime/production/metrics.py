from __future__ import annotations

import threading


class RuntimeMetrics:
    """只记录计数，不接收任务文本、身份、结果或密钥。"""

    ALLOWED = frozenset({
        "submitted", "duplicate", "claimed", "completed", "retried",
        "dead_letter", "failed", "cancelled", "recovered",
    })

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts = {name: 0 for name in self.ALLOWED}

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in self.ALLOWED:
            raise ValueError("Unknown metric")
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counts.items()))
