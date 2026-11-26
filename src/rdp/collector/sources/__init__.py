"""Feed sources. Each calls ``handler(payload, topic, meta)`` per broker message."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

Handler = Callable[[bytes | str | None, str | None, dict[str, Any]], None]


class Backoff:
    """Exponential backoff with jitter, capped."""

    def __init__(self, base_s: float = 1.0, cap_s: float = 300.0) -> None:
        self.base_s = base_s
        self.cap_s = cap_s
        self.attempt = 0

    def next(self) -> float:
        delay = min(self.cap_s, self.base_s * 2**self.attempt)
        self.attempt += 1
        return delay * random.uniform(0.5, 1.0)

    def reset(self) -> None:
        self.attempt = 0
