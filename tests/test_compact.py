from __future__ import annotations

import gzip
import json
from datetime import date

import pandas as pd

from rdp.collector.compact import compact_trust_day


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _rec(msg, host, source, ts):
    return {"v": 1, "recv_ts": ts, "host": host, "source": source, "feed": "trust", "msg": msg}


def test_dedup_across_collectors(tmp_path, trust_messages):
    a, b, c = trust_messages
    day = tmp_path / "raw" / "trust" / "2026" / "11" / "27"
    _write(
        day / "trust_20261127T10_pi-nr-stomp.jsonl.gz",
        [
            _rec(a, "pi", "nr-stomp", "2026-11-27T10:00:02.000Z"),
            _rec(b, "pi", "nr-stomp", "2026-11-27T10:00:03.000Z"),
            _rec(a, "pi", "nr-stomp", "2026-11-27T10:00:09.000Z"),  # redelivery
        ],
    )
    _write(
        day / "trust_20261127T10_vps-rdm-kafka.jsonl.gz",
        [
            _rec(a, "vps", "rdm-kafka", "2026-11-27T10:00:01.000Z"),
            _rec(c, "vps", "rdm-kafka", "2026-11-27T10:00:04.000Z"),
        ],
    )
    summary = compact_trust_day(tmp_path / "raw", tmp_path / "out", date(2026, 11, 27))

    assert summary["unique_messages"] == 3
    assert summary["records_per_collector"] == {"pi/nr-stomp": 3, "vps/rdm-kafka": 2}
    assert summary["messages_only_seen_by"] == {"pi/nr-stomp": 1, "vps/rdm-kafka": 1}

    df = pd.read_parquet(tmp_path / "out" / "trust" / "date=2026-11-27" / "part-0.parquet")
    row_a = df[df["train_id"] == "000T00MA27"].iloc[0]
    assert row_a["n_copies"] == 3
    assert row_a["first_source"] == "rdm-kafka"
    assert row_a["seen_by"] == "pi/nr-stomp,vps/rdm-kafka"
    assert row_a["h_msg_type"] == "0003"
    assert df["recv_ts"].is_monotonic_increasing


def test_truncated_and_bad_lines_counted(tmp_path, trust_messages):
    day = tmp_path / "raw" / "trust" / "2026" / "11" / "27"
    good = day / "trust_20261127T10_pi-nr-stomp.jsonl.gz"
    _write(good, [_rec(trust_messages[0], "pi", "nr-stomp", "2026-11-27T10:00:00.000Z")])
    with gzip.open(good, "at", encoding="utf-8") as fh:
        fh.write("not json\n")
    truncated = day / "trust_20261127T11_pi-nr-stomp.jsonl.gz"
    full = gzip.compress(b'{"a": 1}\n' * 100)
    truncated.write_bytes(full[: len(full) // 2])

    summary = compact_trust_day(tmp_path / "raw", tmp_path / "out", date(2026, 11, 27))
    assert summary["bad_lines"] == 1
    assert summary["truncated_files"] == 1
    assert summary["unique_messages"] == 1


def test_empty_day_writes_summary_only(tmp_path):
    summary = compact_trust_day(tmp_path / "raw", tmp_path / "out", date(2026, 11, 27))
    out = tmp_path / "out" / "trust" / "date=2026-11-27"
    assert summary["unique_messages"] == 0
    assert (out / "summary.json").exists() and not (out / "part-0.parquet").exists()
