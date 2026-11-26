"""Health check over collector status files (for cron / systemd timers)."""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def check_status_files(
    paths: list[Path], *, max_age_s: float, now: datetime | None = None
) -> list[str]:
    """Return a list of problems; an empty list means healthy."""
    now = now or datetime.now(UTC)
    if not paths:
        return ["no status files found"]
    problems: list[str] = []
    for path in paths:
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: unreadable ({exc})")
            continue
        label = f"{status.get('host')}/{status.get('source')}"
        updated = status.get("updated")
        if not updated or (now - _parse_ts(updated)).total_seconds() > max_age_s:
            problems.append(f"{label}: status not updated since {updated} (collector down?)")
        for feed, info in status.get("feeds", {}).items():
            last = info.get("last_msg_ts")
            if last is None:
                problems.append(f"{label}/{feed}: no messages received yet")
            elif (age := (now - _parse_ts(last)).total_seconds()) > max_age_s:
                problems.append(f"{label}/{feed}: last message {age:.0f} s ago")
    return problems


def ping(url: str, timeout_s: float = 10.0) -> None:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        resp.read()
