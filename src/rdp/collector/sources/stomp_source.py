"""Network Rail Open Data STOMP source (durable topic subscription).

Uses client-individual acknowledgement: each frame is acknowledged only after
the handler has written and flushed it, so a crash leads to redelivery
(duplicates, removed at compaction) instead of loss. The durable subscription
means messages published while disconnected are retained by the broker for a
while and delivered on reconnect.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import stomp

from rdp.collector.sources import Backoff, Handler

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StompConfig:
    host: str
    port: int
    username: str
    password: str
    client_id: str
    topic: str = "TRAIN_MVT_ALL_TOC"
    heartbeat_ms: int = 15000


class AckingListener(stomp.ConnectionListener):
    def __init__(
        self,
        conn: Any,
        handler: Handler,
        flush: Callable[[], None],
        on_disconnect: Callable[[], None],
    ) -> None:
        self.conn = conn
        self.handler = handler
        self.flush = flush
        self.on_disconnect = on_disconnect

    def on_message(self, frame: Any) -> None:
        headers = frame.headers
        try:
            self.handler(
                frame.body,
                headers.get("destination"),
                {"message_id": headers.get("message-id")},
            )
            self.flush()
        except Exception:
            # Not acknowledged: the broker redelivers after reconnect.
            log.exception("failed to handle STOMP frame %s", headers.get("message-id"))
            return
        self.conn.ack(headers["message-id"], headers["subscription"])

    def on_error(self, frame: Any) -> None:
        log.error("STOMP error frame: %s %s", frame.headers.get("message"), frame.body)

    def on_heartbeat_timeout(self) -> None:
        log.warning("STOMP heartbeat timeout")

    def on_disconnected(self) -> None:
        log.warning("STOMP disconnected")
        self.on_disconnect()


def run_stomp(
    cfg: StompConfig,
    handler: Handler,
    flush: Callable[[], None],
    stop: threading.Event,
    *,
    connection_factory: Callable[..., Any] | None = None,
) -> None:
    """Connect, subscribe and keep reconnecting with backoff until ``stop``."""
    factory = connection_factory or stomp.Connection
    backoff = Backoff(base_s=2.0, cap_s=300.0)
    while not stop.is_set():
        disconnected = threading.Event()
        conn = factory(
            [(cfg.host, cfg.port)],
            heartbeats=(cfg.heartbeat_ms, cfg.heartbeat_ms),
            reconnect_attempts_max=1,
        )
        conn.set_listener("rdp", AckingListener(conn, handler, flush, disconnected.set))
        try:
            log.info("connecting to %s:%s as client-id %s", cfg.host, cfg.port, cfg.client_id)
            conn.connect(
                username=cfg.username,
                passcode=cfg.password,
                wait=True,
                headers={"client-id": cfg.client_id},
            )
            conn.subscribe(
                destination=f"/topic/{cfg.topic}",
                id="1",
                ack="client-individual",
                headers={"activemq.subscriptionName": f"{cfg.client_id}-{cfg.topic}"},
            )
            log.info("subscribed to /topic/%s", cfg.topic)
            backoff.reset()
            while not stop.is_set() and not disconnected.is_set():
                stop.wait(1.0)
        except Exception:
            log.exception("STOMP connection failed")
        finally:
            try:
                if conn.is_connected():
                    conn.disconnect()
            except Exception:
                log.debug("error during disconnect", exc_info=True)
        if stop.is_set():
            break
        delay = backoff.next()
        log.info("reconnecting in %.0f s", delay)
        stop.wait(delay)
