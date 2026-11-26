"""Collector status file and gap log.

The status file (JSON, rewritten atomically) holds per-feed counters and the
time of the last message. The gap log (JSON Lines, append-only) records:

- ``restart``: the collector started; includes the last message time of the
  previous run, so downtime between runs is measurable.
- ``gap``: no message arrived for longer than the threshold; written when
  messages resume (or at shutdown), with start, end and duration.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rdp.collector.records import iso_ms, utc_now

log = logging.getLogger(__name__)


@dataclass
class FeedStats:
    received: int = 0
    kept: int = 0
    errors: int = 0
    last_msg_ts: datetime | None = None
    gap_start: datetime | None = None


class StatusTracker:
    def __init__(
        self,
        status_path: Path,
        gaps_path: Path,
        *,
        host: str,
        source: str,
        feeds: list[str],
        gap_threshold_s: float = 300.0,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.status_path = Path(status_path)
        self.gaps_path = Path(gaps_path)
        self.host = host
        self.source = source
        self.gap_threshold_s = gap_threshold_s
        self._now = now
        self._lock = threading.Lock()
        self.started = now()
        self.feeds = {f: FeedStats() for f in feeds}
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.gaps_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_restart()

    def _log_restart(self) -> None:
        previous: dict[str, Any] = {}
        if self.status_path.exists():
            try:
                previous = json.loads(self.status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                log.warning("could not read previous status file %s", self.status_path)
        prev_last = {
            feed: info.get("last_msg_ts") for feed, info in previous.get("feeds", {}).items()
        }
        self._append_event(
            {"event": "restart", "at": iso_ms(self.started), "previous_last_msg_ts": prev_last}
        )

    def _append_event(self, event: dict[str, Any]) -> None:
        event = {"host": self.host, "source": self.source, **event}
        with open(self.gaps_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def record(self, feed: str, *, kept: bool, error: bool = False) -> None:
        now = self._now()
        with self._lock:
            st = self.feeds[feed]
            st.received += 1
            st.kept += int(kept)
            st.errors += int(error)
            if st.gap_start is not None:
                self._close_gap(feed, st, end=now)
            st.last_msg_ts = now

    def _close_gap(self, feed: str, st: FeedStats, end: datetime) -> None:
        assert st.gap_start is not None
        seconds = (end - st.gap_start).total_seconds()
        self._append_event(
            {
                "event": "gap",
                "feed": feed,
                "start": iso_ms(st.gap_start),
                "end": iso_ms(end),
                "seconds": round(seconds, 1),
            }
        )
        log.warning("feed %s resumed after %.0f s gap", feed, seconds)
        st.gap_start = None

    def check_gaps(self) -> None:
        now = self._now()
        with self._lock:
            for feed, st in self.feeds.items():
                reference = st.last_msg_ts or self.started
                if (
                    st.gap_start is None
                    and (now - reference).total_seconds() > self.gap_threshold_s
                ):
                    st.gap_start = reference
                    log.warning("feed %s: no messages since %s", feed, iso_ms(reference))

    def shutdown(self) -> None:
        """Close any open gap at shutdown so it is not lost."""
        now = self._now()
        with self._lock:
            for feed, st in self.feeds.items():
                if st.gap_start is not None:
                    self._close_gap(feed, st, end=now)
        self.write()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "host": self.host,
                "source": self.source,
                "started": iso_ms(self.started),
                "updated": iso_ms(self._now()),
                "gap_threshold_s": self.gap_threshold_s,
                "feeds": {
                    feed: {
                        "received": st.received,
                        "kept": st.kept,
                        "errors": st.errors,
                        "last_msg_ts": iso_ms(st.last_msg_ts) if st.last_msg_ts else None,
                        "in_gap": st.gap_start is not None,
                    }
                    for feed, st in self.feeds.items()
                },
            }

    def write(self) -> None:
        data = self.snapshot()
        tmp = self.status_path.with_name(self.status_path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.status_path)


def run_watchdog(tracker: StatusTracker, stop: threading.Event, interval_s: float = 15.0) -> None:
    """Periodically check for gaps and rewrite the status file until ``stop``."""
    while not stop.wait(interval_s):
        try:
            tracker.check_gaps()
            tracker.write()
        except Exception:  # keep the watchdog alive
            log.exception("watchdog iteration failed")
