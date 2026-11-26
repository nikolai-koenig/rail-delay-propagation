"""Wire a source, a filter, a sink and status tracking into one collector."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from rdp.collector.filters import TokenFilter, TrustFilter
from rdp.collector.records import decode_payload, make_record, split_trust_payload, utc_now
from rdp.collector.sink import HourlyJsonlSink
from rdp.collector.status import StatusTracker, run_watchdog

log = logging.getLogger(__name__)

FEEDS = ("trust", "darwin")
SOURCES = ("nr-stomp", "rdm-kafka")


class FeedHandler:
    """Turn broker payloads into envelope records and write the kept ones.

    TRUST payloads are split into individual messages (filtered per message).
    Darwin payloads are stored whole as raw text (optionally token-filtered).
    Payloads that fail to parse are stored raw with ``parse_error``.
    """

    def __init__(
        self,
        *,
        feed: str,
        source: str,
        host: str,
        sink: HourlyJsonlSink,
        status: StatusTracker,
        trust_filter: TrustFilter | None = None,
        token_filter: TokenFilter | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if feed not in FEEDS:
            raise ValueError(f"unknown feed {feed!r}")
        self.feed = feed
        self.source = source
        self.host = host
        self.sink = sink
        self.status = status
        self.trust_filter = trust_filter or TrustFilter(None)
        self.token_filter = token_filter or TokenFilter(None)
        self._now = now

    def _record(self, topic: str | None, recv_ts: datetime, **kwargs: Any) -> dict[str, Any]:
        return make_record(
            feed=self.feed,
            source=self.source,
            host=self.host,
            topic=topic,
            recv_ts=recv_ts,
            **kwargs,
        )

    def __call__(
        self, payload: bytes | str | None, topic: str | None, meta: dict[str, Any]
    ) -> None:
        recv_ts = self._now()
        text, encoding = decode_payload(payload)
        meta = {k: v for k, v in meta.items() if v is not None}

        if self.feed == "darwin":
            kept = encoding != "utf-8" or self.token_filter.keep(text)
            if kept:
                self.sink.write(
                    self._record(topic, recv_ts, raw=text, raw_encoding=encoding, meta=meta)
                )
            self.status.record(self.feed, kept=kept)
            return

        msgs, error = (
            split_trust_payload(text) if encoding == "utf-8" else ([], "payload not UTF-8")
        )
        if error is not None:
            log.warning("TRUST payload problem: %s", error)
            self.sink.write(
                self._record(
                    topic, recv_ts, raw=text, raw_encoding=encoding, parse_error=error, meta=meta
                )
            )
            self.status.record(self.feed, kept=True, error=True)
            if not msgs:
                return
        for msg in msgs:
            kept = self.trust_filter.keep(msg)
            if kept:
                self.sink.write(self._record(topic, recv_ts, msg=msg, meta=meta))
            self.status.record(self.feed, kept=kept)


def run_collector(
    *,
    feed: str,
    source: str,
    host: str,
    data_root: Path,
    start_source: Callable[[FeedHandler, Callable[[], None], threading.Event], None],
    trust_filter: TrustFilter | None = None,
    token_filter: TokenFilter | None = None,
    gap_threshold_s: float = 300.0,
) -> None:
    """Run until SIGINT/SIGTERM. ``start_source`` blocks while consuming."""
    tag = f"{host}-{source}"
    raw_root = data_root / "raw"
    meta_dir = data_root / "collector"
    sink = HourlyJsonlSink(raw_root, feed, tag)
    status = StatusTracker(
        meta_dir / f"status_{feed}_{tag}.json",
        meta_dir / f"events_{feed}_{tag}.jsonl",
        host=host,
        source=source,
        feeds=[feed],
        gap_threshold_s=gap_threshold_s,
    )
    handler = FeedHandler(
        feed=feed,
        source=source,
        host=host,
        sink=sink,
        status=status,
        trust_filter=trust_filter,
        token_filter=token_filter,
    )
    stop = threading.Event()

    def _stop(signum: int, _frame: Any) -> None:
        log.info("signal %s received, stopping", signum)
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    watchdog = threading.Thread(target=run_watchdog, args=(status, stop), daemon=True)
    watchdog.start()
    log.info("collector %s/%s writing to %s", feed, tag, raw_root)
    try:
        start_source(handler, sink.flush, stop)
    finally:
        stop.set()
        sink.close()
        status.shutdown()
        log.info("collector stopped")
