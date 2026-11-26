"""Merge one UTC day of raw TRUST captures (any hosts/sources) into Parquet.

- Duplicates (same message seen by several collectors, or redelivered after a
  reconnect) are collapsed using a hash of the canonical message JSON. The
  earliest receipt is kept; ``n_copies`` and ``seen_by`` record coverage.
- All TRUST fields are kept as strings (raw layer). Typing and timestamp
  conversion happen in the cleaning stage.
- A summary JSON reports per-collector counts and messages seen by only one
  collector, which measures each collector's gaps.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)


def day_dir(raw_root: Path, feed: str, day: date) -> Path:
    return raw_root / feed / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"


def iter_records(path: Path, stats: dict[str, int]) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    stats["bad_lines"] += 1
    except EOFError:
        stats["truncated_files"] += 1
        log.warning("truncated gzip file %s", path)


def message_key(msg: dict[str, Any]) -> str:
    canonical = json.dumps(msg, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _flat_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return str(value)


def flatten_trust(msg: dict[str, Any]) -> dict[str, str | None]:
    row: dict[str, str | None] = {}
    for key, value in (msg.get("header") or {}).items():
        row[f"h_{key}"] = _flat_value(value)
    for key, value in (msg.get("body") or {}).items():
        row[key] = _flat_value(value)
    return row


def compact_trust_day(
    raw_root: Path, out_root: Path, day: date, *, include_open: bool = False
) -> dict[str, Any]:
    folder = day_dir(raw_root, "trust", day)
    files = sorted(folder.glob("*.jsonl.gz"))
    if include_open:
        files += sorted(folder.glob("*.jsonl"))
    stats = {"bad_lines": 0, "truncated_files": 0, "parse_error_records": 0}
    per_collector: dict[str, int] = {}
    first: dict[str, dict[str, Any]] = {}
    seen_by: dict[str, set[str]] = {}
    copies: dict[str, int] = {}

    for path in files:
        for rec in iter_records(path, stats):
            if "msg" not in rec:
                stats["parse_error_records"] += 1
                continue
            collector = f"{rec.get('host')}/{rec.get('source')}"
            per_collector[collector] = per_collector.get(collector, 0) + 1
            key = message_key(rec["msg"])
            seen_by.setdefault(key, set()).add(collector)
            copies[key] = copies.get(key, 0) + 1
            prev = first.get(key)
            if prev is None or rec["recv_ts"] < prev["recv_ts"]:
                first[key] = rec

    rows = []
    for key, rec in first.items():
        row = flatten_trust(rec["msg"])
        row.update(
            {
                "dedup_key": key,
                "recv_ts": rec["recv_ts"],
                "first_host": rec.get("host"),
                "first_source": rec.get("source"),
                "n_copies": copies[key],
                "seen_by": ",".join(sorted(seen_by[key])),
            }
        )
        rows.append(row)

    collectors = sorted(per_collector)
    only_in = {c: sum(1 for s in seen_by.values() if s == {c}) for c in collectors}
    summary: dict[str, Any] = {
        "date": day.isoformat(),
        "files": [p.name for p in files],
        "unique_messages": len(rows),
        "records_per_collector": per_collector,
        "messages_only_seen_by": only_in,
        **stats,
    }

    out_dir = out_root / "trust" / f"date={day.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if rows:
        df = pd.DataFrame(rows).sort_values(["recv_ts", "dedup_key"], kind="stable")
        df = df[sorted(df.columns)].astype({"n_copies": "int32"})
        df.to_parquet(out_dir / "part-0.parquet", index=False)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
