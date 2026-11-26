"""Optional corridor filters applied before writing to disk.

Filters are deliberately permissive: when in doubt, a message is kept.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# Body fields of TRUST messages that carry a STANOX location code.
TRUST_STANOX_FIELDS = (
    "loc_stanox",
    "reporting_stanox",
    "original_loc_stanox",
    "next_report_stanox",
    "sched_origin_stanox",
    "tp_origin_stanox",
)

# Activation (0001) and change-of-identity (0007) messages cannot be tied to
# the corridor without the schedule, and are low volume, so they are always kept.
TRUST_ALWAYS_KEEP = frozenset({"0001", "0007"})


class TrustFilter:
    """Keep TRUST messages that mention a corridor STANOX.

    ``stanox=None`` keeps everything.
    """

    def __init__(self, stanox: Iterable[str] | None = None) -> None:
        self.stanox = None if stanox is None else frozenset(s.strip() for s in stanox)

    def keep(self, msg: dict[str, Any]) -> bool:
        if self.stanox is None:
            return True
        header = msg.get("header") or {}
        if header.get("msg_type") in TRUST_ALWAYS_KEEP:
            return True
        body = msg.get("body") or {}
        values = [
            str(body[f]).strip() for f in TRUST_STANOX_FIELDS if body.get(f) not in (None, "")
        ]
        values = [v for v in values if v]
        if not values:
            # Unknown shape: keep rather than silently drop.
            return True
        return any(v in self.stanox for v in values)


class TokenFilter:
    """Keep text payloads that contain any of the given tokens (e.g. TIPLOCs).

    Tokens match whole words only: ``RDNG`` does not match ``RDNGX``.
    ``tokens=None`` keeps everything.
    """

    def __init__(self, tokens: Iterable[str] | None = None) -> None:
        self.pattern: re.Pattern[str] | None = None
        if tokens is not None:
            toks = sorted({t.strip() for t in tokens if t.strip()}, key=len, reverse=True)
            if toks:
                alternation = "|".join(re.escape(t) for t in toks)
                self.pattern = re.compile(rf"(?<![A-Za-z0-9])(?:{alternation})(?![A-Za-z0-9])")

    def keep(self, text: str) -> bool:
        return True if self.pattern is None else bool(self.pattern.search(text))
