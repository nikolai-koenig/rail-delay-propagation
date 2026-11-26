"""Record envelope written by the collectors, and payload decoding helpers."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

RECORD_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_ms(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def decode_payload(payload: bytes | str | None) -> tuple[str, str]:
    """Return ``(text, encoding)``; non-UTF-8 bytes are base64-encoded."""
    if payload is None:
        return "", "utf-8"
    if isinstance(payload, str):
        return payload, "utf-8"
    try:
        return payload.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return base64.b64encode(payload).decode("ascii"), "base64"


def make_record(
    *,
    feed: str,
    source: str,
    host: str,
    topic: str | None,
    recv_ts: datetime,
    msg: Any = None,
    raw: str | None = None,
    raw_encoding: str | None = None,
    parse_error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "v": RECORD_VERSION,
        "recv_ts": iso_ms(recv_ts),
        "host": host,
        "source": source,
        "feed": feed,
        "topic": topic,
    }
    if meta:
        record["meta"] = meta
    if msg is not None:
        record["msg"] = msg
    if raw is not None:
        record["raw"] = raw
        record["raw_encoding"] = raw_encoding or "utf-8"
    if parse_error is not None:
        record["parse_error"] = parse_error
    return record


def split_trust_payload(text: str) -> tuple[list[dict[str, Any]], str | None]:
    """Split a TRUST payload into individual messages.

    The Network Rail STOMP feed delivers a JSON array of messages per frame;
    a single JSON object is also accepted. Returns ``(messages, error)``.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], f"invalid JSON: {exc}"
    if isinstance(data, dict):
        return [data], None
    if isinstance(data, list):
        msgs = [m for m in data if isinstance(m, dict)]
        if len(msgs) != len(data):
            return msgs, f"{len(data) - len(msgs)} non-object element(s) dropped"
        return msgs, None
    return [], f"unexpected JSON type {type(data).__name__}"
