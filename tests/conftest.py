from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kwargs: float) -> None:
        self.t += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 27, 10, 59, 0, tzinfo=UTC))


@pytest.fixture
def trust_frame_text() -> str:
    """A synthetic STOMP frame body: a JSON array of TRUST messages.

    Location codes are fake (99xxx) and only exercise the code paths.
    """
    return (FIXTURES / "trust_frame.json").read_text(encoding="utf-8")


@pytest.fixture
def trust_messages(trust_frame_text: str) -> list[dict]:
    return json.loads(trust_frame_text)
