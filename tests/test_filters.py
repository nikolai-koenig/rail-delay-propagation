from __future__ import annotations

from rdp.collector.filters import TokenFilter, TrustFilter


def test_trust_filter_none_keeps_all(trust_messages):
    f = TrustFilter(None)
    assert all(f.keep(m) for m in trust_messages)


def test_trust_filter_corridor(trust_messages):
    f = TrustFilter({"99001", "99002"})
    in_corridor, outside, activation = trust_messages
    assert f.keep(in_corridor)
    assert not f.keep(outside)
    assert f.keep(activation)  # activations always kept


def test_trust_filter_next_report_stanox_counts():
    f = TrustFilter({"99002"})
    msg = {
        "header": {"msg_type": "0003"},
        "body": {"loc_stanox": "88000", "next_report_stanox": "99002"},
    }
    assert f.keep(msg)


def test_trust_filter_keeps_unknown_shape():
    f = TrustFilter({"99001"})
    assert f.keep({"header": {"msg_type": "0009"}, "body": {"something": "else"}})


def test_token_filter_whole_words():
    f = TokenFilter({"RDNG", "SLOUGH"})
    assert f.keep('<Location tpl="RDNG" wta="10:00"/>')
    assert f.keep('{\\"tpl\\":\\"SLOUGH\\"}')
    assert not f.keep('<Location tpl="RDNGX"/>')
    assert not f.keep('<Location tpl="XRDNG"/>')


def test_token_filter_none_and_empty_keep_all():
    assert TokenFilter(None).keep("anything")
    assert TokenFilter([]).keep("anything")
