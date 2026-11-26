from __future__ import annotations

import json

from rdp.collector.filters import TokenFilter, TrustFilter
from rdp.collector.run import FeedHandler
from rdp.collector.sink import HourlyJsonlSink
from rdp.collector.status import StatusTracker


def _setup(tmp_path, clock, feed, **filters):
    sink = HourlyJsonlSink(tmp_path / "raw", feed, "pi-nr-stomp", now=clock, fsync=False)
    status = StatusTracker(
        tmp_path / "s.json",
        tmp_path / "e.jsonl",
        host="pi",
        source="nr-stomp",
        feeds=[feed],
        now=clock,
    )
    handler = FeedHandler(
        feed=feed, source="nr-stomp", host="pi", sink=sink, status=status, now=clock, **filters
    )
    return handler, sink, status


def _lines(sink):
    sink.close()
    return [json.loads(x) for x in sink.current_path.read_text(encoding="utf-8").splitlines()]


def test_trust_frame_split_and_filtered(tmp_path, clock, trust_frame_text):
    handler, sink, status = _setup(tmp_path, clock, "trust", trust_filter=TrustFilter({"99001"}))
    handler(trust_frame_text.encode(), "/topic/TRAIN_MVT_ALL_TOC", {"message_id": "m1"})
    recs = _lines(sink)
    assert [r["msg"]["header"]["msg_type"] for r in recs] == ["0003", "0001"]
    assert all(r["meta"] == {"message_id": "m1"} for r in recs)
    feed = status.snapshot()["feeds"]["trust"]
    assert (feed["received"], feed["kept"]) == (3, 2)


def test_trust_bad_payload_stored_raw(tmp_path, clock):
    handler, sink, status = _setup(tmp_path, clock, "trust")
    handler(b"{broken", "t", {})
    (rec,) = _lines(sink)
    assert rec["raw"] == "{broken" and "parse_error" in rec
    assert status.snapshot()["feeds"]["trust"]["errors"] == 1


def test_darwin_raw_and_token_filter(tmp_path, clock):
    handler, sink, _ = _setup(tmp_path, clock, "darwin", token_filter=TokenFilter({"RDNG"}))
    handler(b'{"bytes": "<Location tpl=\\"RDNG\\"/>"}', "darwin", {"partition": 0})
    handler(b'{"bytes": "<Location tpl=\\"OTHER\\"/>"}', "darwin", {"partition": 0})
    recs = _lines(sink)
    assert len(recs) == 1 and "RDNG" in recs[0]["raw"]


def test_darwin_binary_payload_kept_as_base64(tmp_path, clock):
    handler, sink, _ = _setup(tmp_path, clock, "darwin", token_filter=TokenFilter({"RDNG"}))
    handler(b"\x1f\x8b\xff", "darwin", {})
    (rec,) = _lines(sink)
    assert rec["raw_encoding"] == "base64"
