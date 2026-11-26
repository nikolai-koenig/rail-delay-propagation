from __future__ import annotations

import base64
from datetime import UTC, datetime

from rdp.collector.records import decode_payload, iso_ms, make_record, split_trust_payload


def test_split_array(trust_frame_text):
    msgs, err = split_trust_payload(trust_frame_text)
    assert err is None
    assert [m["header"]["msg_type"] for m in msgs] == ["0003", "0003", "0001"]


def test_split_single_object():
    msgs, err = split_trust_payload('{"header": {"msg_type": "0003"}, "body": {}}')
    assert err is None and len(msgs) == 1


def test_split_invalid_json():
    msgs, err = split_trust_payload("{not json")
    assert msgs == [] and err.startswith("invalid JSON")


def test_split_drops_non_objects_and_reports():
    msgs, err = split_trust_payload('[{"a": 1}, 3]')
    assert len(msgs) == 1 and "1 non-object" in err


def test_decode_payload_variants():
    assert decode_payload(b"abc") == ("abc", "utf-8")
    assert decode_payload("abc") == ("abc", "utf-8")
    assert decode_payload(None) == ("", "utf-8")
    text, enc = decode_payload(b"\xff\xfe")
    assert enc == "base64" and base64.b64decode(text) == b"\xff\xfe"


def test_make_record_fields():
    ts = datetime(2026, 11, 27, 10, 0, 0, 123456, tzinfo=UTC)
    rec = make_record(
        feed="trust", source="nr-stomp", host="pi", topic="/topic/X", recv_ts=ts, msg={"a": 1}
    )
    assert rec["recv_ts"] == "2026-11-27T10:00:00.123Z"
    assert rec["msg"] == {"a": 1}
    assert "raw" not in rec and "meta" not in rec
    assert iso_ms(ts) == rec["recv_ts"]
