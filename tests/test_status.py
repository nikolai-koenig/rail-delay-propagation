from __future__ import annotations

import json
from datetime import timedelta

from rdp.collector.health import check_status_files
from rdp.collector.status import StatusTracker


def _events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _tracker(tmp_path, clock, threshold=300.0):
    return StatusTracker(
        tmp_path / "status.json",
        tmp_path / "events.jsonl",
        host="pi",
        source="nr-stomp",
        feeds=["trust"],
        gap_threshold_s=threshold,
        now=clock,
    )


def test_gap_detected_and_closed(tmp_path, clock):
    t = _tracker(tmp_path, clock)
    t.record("trust", kept=True)
    clock.advance(seconds=200)
    t.check_gaps()
    assert not t.snapshot()["feeds"]["trust"]["in_gap"]
    clock.advance(seconds=200)  # 400 s silence
    t.check_gaps()
    assert t.snapshot()["feeds"]["trust"]["in_gap"]
    clock.advance(seconds=100)
    t.record("trust", kept=True)
    events = _events(tmp_path / "events.jsonl")
    assert events[0]["event"] == "restart"
    gap = events[1]
    assert gap["event"] == "gap" and gap["seconds"] == 500.0


def test_gap_from_start_without_messages(tmp_path, clock):
    t = _tracker(tmp_path, clock)
    clock.advance(seconds=301)
    t.check_gaps()
    t.shutdown()
    events = _events(tmp_path / "events.jsonl")
    assert events[-1]["event"] == "gap" and events[-1]["seconds"] == 301.0


def test_restart_event_reports_previous_last_message(tmp_path, clock):
    t = _tracker(tmp_path, clock)
    t.record("trust", kept=True)
    t.write()
    clock.advance(hours=1)
    _tracker(tmp_path, clock)
    restart = _events(tmp_path / "events.jsonl")[-1]
    assert restart["event"] == "restart"
    assert restart["previous_last_msg_ts"]["trust"] == "2026-11-27T10:59:00.000Z"


def test_counts(tmp_path, clock):
    t = _tracker(tmp_path, clock)
    t.record("trust", kept=True)
    t.record("trust", kept=False)
    t.record("trust", kept=True, error=True)
    feed = t.snapshot()["feeds"]["trust"]
    assert (feed["received"], feed["kept"], feed["errors"]) == (3, 2, 1)


def test_health_check(tmp_path, clock):
    t = _tracker(tmp_path, clock)
    path = tmp_path / "status.json"
    t.write()
    assert any("no messages" in p for p in check_status_files([path], max_age_s=900, now=clock()))
    t.record("trust", kept=True)
    t.write()
    assert check_status_files([path], max_age_s=900, now=clock()) == []
    later = clock() + timedelta(seconds=1000)
    problems = check_status_files([path], max_age_s=900, now=later)
    assert len(problems) == 2  # status stale and last message stale
    assert check_status_files([], max_age_s=900) == ["no status files found"]
