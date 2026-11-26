from __future__ import annotations

import gzip
import json

from rdp.collector.sink import HourlyJsonlSink, compress_file


def _read_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def test_rotation_compresses_previous_hour(tmp_path, clock):
    sink = HourlyJsonlSink(tmp_path, "trust", "pi-nr-stomp", now=clock, fsync=False)
    sink.write({"n": 1})
    first = sink.current_path
    assert first.name == "trust_20261127T10_pi-nr-stomp.jsonl"
    clock.advance(minutes=2)  # 11:01 -> new hour
    sink.write({"n": 2})
    sink.close()

    assert not first.exists()
    gz = first.with_name(first.name + ".gz")
    assert _read_gz(gz) == [{"n": 1}]
    current = sink.current_path
    assert current.name == "trust_20261127T11_pi-nr-stomp.jsonl"
    assert current.read_text(encoding="utf-8").strip() == '{"n":2}'


def test_restart_same_hour_appends(tmp_path, clock):
    s1 = HourlyJsonlSink(tmp_path, "trust", "pi-nr-stomp", now=clock, fsync=False)
    s1.write({"n": 1})
    s1.close()
    s2 = HourlyJsonlSink(tmp_path, "trust", "pi-nr-stomp", now=clock, fsync=False)
    s2.write({"n": 2})
    s2.close()
    lines = s2.current_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["n"] for x in lines] == [1, 2]


def test_startup_compresses_stale_files_only_for_own_tag(tmp_path, clock):
    s1 = HourlyJsonlSink(tmp_path, "trust", "pi-nr-stomp", now=clock, fsync=False)
    s1.write({"n": 1})
    s1.close()
    other = HourlyJsonlSink(tmp_path, "trust", "vps-rdm-kafka", now=clock, fsync=False)
    other.write({"n": 9})
    other.close()

    clock.advance(hours=3)
    HourlyJsonlSink(tmp_path, "trust", "pi-nr-stomp", now=clock, fsync=False)

    assert not s1.current_path.exists()
    assert s1.current_path.with_name(s1.current_path.name + ".gz").exists()
    assert other.current_path.exists()  # another collector's file is untouched


def test_compress_appends_member_when_target_exists(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"n":1}\n', encoding="utf-8")
    compress_file(p)
    p.write_text('{"n":2}\n', encoding="utf-8")
    compress_file(p)
    assert _read_gz(tmp_path / "x.jsonl.gz") == [{"n": 1}, {"n": 2}]


def test_bytes_written_counts_utf8(tmp_path, clock):
    sink = HourlyJsonlSink(tmp_path, "darwin", "vps-rdm-kafka", now=clock, fsync=False)
    sink.write({"s": "é"})
    sink.close()
    assert sink.bytes_written == len('{"s":"é"}\n'.encode())
