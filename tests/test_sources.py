from __future__ import annotations

import threading
from types import SimpleNamespace

from rdp.collector.sources import Backoff
from rdp.collector.sources.kafka_source import KafkaConfig, run_kafka
from rdp.collector.sources.stomp_source import AckingListener, StompConfig, run_stomp


class FakeStompConn:
    def __init__(self, *args, **kwargs):
        self.acks = []
        self.listener = None
        self.connected = False

    def set_listener(self, name, listener):
        self.listener = listener

    def connect(self, **kwargs):
        self.connected = True

    def subscribe(self, **kwargs):
        self.subscribe_kwargs = kwargs

    def ack(self, message_id, subscription):
        self.acks.append((message_id, subscription))

    def is_connected(self):
        return self.connected

    def disconnect(self):
        self.connected = False


def _frame(mid="m1"):
    return SimpleNamespace(
        headers={"message-id": mid, "subscription": "1", "destination": "/topic/X"}, body="[]"
    )


def test_listener_acks_after_handle_and_flush():
    conn = FakeStompConn()
    order = []
    listener = AckingListener(
        conn,
        handler=lambda body, topic, meta: order.append(("handle", meta["message_id"])),
        flush=lambda: order.append(("flush",)),
        on_disconnect=lambda: None,
    )
    listener.on_message(_frame("m1"))
    assert order == [("handle", "m1"), ("flush",)]
    assert conn.acks == [("m1", "1")]


def test_listener_does_not_ack_on_failure():
    conn = FakeStompConn()

    def boom(*_):
        raise OSError("disk full")

    listener = AckingListener(conn, boom, lambda: None, lambda: None)
    listener.on_message(_frame())
    assert conn.acks == []


def test_run_stomp_reconnects_after_disconnect():
    stop = threading.Event()
    conns = []

    def factory(*args, **kwargs):
        conn = FakeStompConn()
        conns.append(conn)
        if len(conns) == 1:
            # First connection drops immediately after subscribing.
            orig = conn.subscribe

            def subscribe_then_drop(**kw):
                orig(**kw)
                conn.listener.on_disconnected()

            conn.subscribe = subscribe_then_drop
        else:
            stop.set()
        return conn

    cfg = StompConfig(host="h", port=1, username="u", password="p", client_id="c")
    import rdp.collector.sources.stomp_source as mod

    original = mod.Backoff.next
    mod.Backoff.next = lambda self: 0.0
    try:
        run_stomp(cfg, lambda *a: None, lambda: None, stop, connection_factory=factory)
    finally:
        mod.Backoff.next = original
    assert len(conns) == 2
    sub = conns[0].subscribe_kwargs
    assert sub["ack"] == "client-individual"
    assert sub["headers"]["activemq.subscriptionName"] == "c-TRAIN_MVT_ALL_TOC"


class FakeKafkaMsg:
    def __init__(self, value, offset):
        self._value, self._offset = value, offset

    def error(self):
        return None

    def value(self):
        return self._value

    def topic(self):
        return "t"

    def partition(self):
        return 0

    def offset(self):
        return self._offset

    def timestamp(self):
        return (1, 1795777140000)


class FakeConsumer:
    def __init__(self, messages, stop):
        self.messages = list(messages)
        self.stop = stop
        self.commits = 0
        self.closed = False

    def subscribe(self, topics):
        self.topics = topics

    def poll(self, timeout):
        if self.messages:
            return self.messages.pop(0)
        self.stop.set()
        return None

    def commit(self, asynchronous=True):
        self.commits += 1

    def close(self):
        self.closed = True


def test_run_kafka_flushes_before_commit_and_closes():
    stop = threading.Event()
    consumer = FakeConsumer([FakeKafkaMsg(b"a", 1), FakeKafkaMsg(b"b", 2)], stop)
    seen, events = [], []

    def flush():
        events.append("flush")

    def handler(value, topic, meta):
        seen.append((value, meta["offset"]))

    cfg = KafkaConfig(bootstrap="b", topic="t", username="u", password="p", group_id="g")
    orig_commit = consumer.commit

    def commit(asynchronous=True):
        events.append("commit")
        orig_commit(asynchronous)

    consumer.commit = commit
    run_kafka(cfg, handler, flush, stop, consumer_factory=lambda settings: consumer)
    assert seen == [(b"a", 1), (b"b", 2)]
    assert events[-2:] == ["flush", "commit"]
    assert consumer.closed


def test_backoff_grows_and_caps():
    b = Backoff(base_s=1, cap_s=8)
    delays = [b.next() for _ in range(6)]
    assert all(0.5 <= d <= 8 for d in delays)
    assert delays[-1] >= 4  # capped at 8, jitter >= 0.5x
    b.reset()
    assert b.next() <= 1
