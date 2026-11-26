"""Hour-rotated JSON Lines sink.

The current hour is written as plain ``.jsonl`` (robust to crashes: at worst
the last line is truncated). When the hour changes, the file is gzip-compressed
to ``.jsonl.gz``. Leftover ``.jsonl`` files from earlier hours are compressed
on start-up. Filenames carry a tag so captures from several machines
can be merged into one tree.

Layout: ``<root>/<feed>/YYYY/MM/DD/<feed>_YYYYMMDDTHH_<tag>.jsonl[.gz]`` (UTC), where
``<tag>`` is ``<host>-<source>`` so two collectors never share a file.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from rdp.collector.records import utc_now

log = logging.getLogger(__name__)


def compress_file(path: Path) -> Path:
    """Gzip ``path`` to ``path.gz`` and remove the original.

    If the target already exists, the new data is appended as a further gzip
    member (readers see the concatenation).
    """
    target = path.with_name(path.name + ".gz")
    tmp = path.with_name(path.name + ".gz.tmp")
    with open(path, "rb") as src, gzip.open(tmp, "wb") as dst:
        shutil.copyfileobj(src, dst)
    if target.exists():
        with open(target, "ab") as out, open(tmp, "rb") as extra:
            shutil.copyfileobj(extra, out)
        tmp.unlink()
    else:
        os.replace(tmp, target)
    path.unlink()
    log.info("compressed %s", target)
    return target


class HourlyJsonlSink:
    def __init__(
        self,
        root: Path,
        feed: str,
        tag: str,
        *,
        now: Callable[[], datetime] = utc_now,
        fsync: bool = True,
    ) -> None:
        self.root = Path(root)
        self.feed = feed
        self.tag = tag
        self._now = now
        self._fsync = fsync
        self._lock = threading.Lock()
        self._fh: IO[str] | None = None
        self._hour: datetime | None = None
        self._path: Path | None = None
        self.bytes_written = 0
        self.compress_stale()

    def _hour_of(self, dt: datetime) -> datetime:
        return dt.replace(minute=0, second=0, microsecond=0)

    def path_for(self, hour: datetime) -> Path:
        return (
            self.root
            / self.feed
            / f"{hour:%Y}"
            / f"{hour:%m}"
            / f"{hour:%d}"
            / f"{self.feed}_{hour:%Y%m%dT%H}_{self.tag}.jsonl"
        )

    @property
    def current_path(self) -> Path | None:
        return self._path

    def compress_stale(self) -> None:
        current = self.path_for(self._hour_of(self._now()))
        feed_dir = self.root / self.feed
        if not feed_dir.exists():
            return
        for p in sorted(feed_dir.rglob(f"{self.feed}_*_{self.tag}.jsonl")):
            if p != current and p != self._path:
                compress_file(p)

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
        with self._lock:
            hour = self._hour_of(self._now())
            if hour != self._hour or self._fh is None:
                self._rotate(hour)
            assert self._fh is not None
            self._fh.write(line)
            self.bytes_written += len(line.encode("utf-8"))

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if self._fh is not None:
            self._fh.flush()
            if self._fsync:
                os.fsync(self._fh.fileno())

    def _rotate(self, hour: datetime) -> None:
        old = self._path
        if self._fh is not None:
            self._flush_locked()
            self._fh.close()
            self._fh = None
        if old is not None and old.exists():
            compress_file(old)
        path = self.path_for(hour)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")  # noqa: SIM115 - long-lived handle
        self._hour = hour
        self._path = path

    def close(self) -> None:
        """Flush and close. The current hour stays uncompressed until the next
        rotation or start-up, so a restart within the hour appends to it."""
        with self._lock:
            if self._fh is not None:
                self._flush_locked()
                self._fh.close()
                self._fh = None
