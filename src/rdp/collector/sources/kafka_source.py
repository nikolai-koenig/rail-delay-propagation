"""Rail Data Marketplace Kafka source (SASL_SSL / PLAIN).

Offsets are committed manually, only after the sink has been flushed, so a
crash leads to re-reading (duplicates) rather than loss. librdkafka handles
reconnection internally; fatal errors raise, and systemd restarts the process.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rdp.collector.sources import Handler

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class KafkaConfig:
    bootstrap: str
    topic: str
    username: str
    password: str
    group_id: str


def consumer_settings(cfg: KafkaConfig) -> dict[str, Any]:
    return {
        "bootstrap.servers": cfg.bootstrap,
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "PLAIN",
        "sasl.username": cfg.username,
        "sasl.password": cfg.password,
        "group.id": cfg.group_id,
        "enable.auto.commit": False,
        # On first start (no committed offset) read whatever the broker retains.
        "auto.offset.reset": "earliest",
        "session.timeout.ms": 45000,
    }


def run_kafka(
    cfg: KafkaConfig,
    handler: Handler,
    flush: Callable[[], None],
    stop: threading.Event,
    *,
    commit_interval_s: float = 5.0,
    consumer_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> None:
    if consumer_factory is None:
        from confluent_kafka import Consumer

        consumer_factory = Consumer
    consumer = consumer_factory(consumer_settings(cfg))
    consumer.subscribe([cfg.topic])
    log.info("subscribed to Kafka topic %s (group %s)", cfg.topic, cfg.group_id)
    pending = False
    last_commit = time.monotonic()

    def commit() -> None:
        nonlocal pending, last_commit
        flush()
        try:
            consumer.commit(asynchronous=False)
        except Exception:
            log.warning("offset commit failed", exc_info=True)
        else:
            pending = False
        last_commit = time.monotonic()

    try:
        while not stop.is_set():
            msg = consumer.poll(1.0)
            if msg is not None:
                err = msg.error()
                if err is not None:
                    if getattr(err, "fatal", lambda: False)():
                        raise RuntimeError(f"fatal Kafka error: {err}")
                    log.warning("Kafka error: %s", err)
                else:
                    handler(
                        msg.value(),
                        msg.topic(),
                        {
                            "partition": msg.partition(),
                            "offset": msg.offset(),
                            "kafka_ts": msg.timestamp()[1],
                        },
                    )
                    pending = True
            if pending and time.monotonic() - last_commit >= commit_interval_s:
                commit()
    finally:
        if pending:
            commit()
        consumer.close()
