"""Broker server clocks → UTC across US and EU daylight-saving changes (research 08 §A.10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fxbot.domain.server_time import (
    FixedOffsetServerTime,
    NewYorkCloseServerTime,
    ZoneServerTime,
    from_server_epoch,
    infer_new_york_shift,
    parse_server_time_policy,
)


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("server", "expected"),
    [
        (datetime(2024, 1, 8, 0, 0), utc(2024, 1, 7, 22)),  # winter: server = UTC+2
        (datetime(2024, 7, 8, 0, 0), utc(2024, 7, 7, 21)),  # summer: server = UTC+3
        # 2024-03-12: US already on DST, EU not yet. The rule follows New York.
        (datetime(2024, 3, 12, 0, 0), utc(2024, 3, 11, 21)),
        # 2024-10-29: EU back on winter time, US still on DST.
        (datetime(2024, 10, 29, 0, 0), utc(2024, 10, 28, 21)),
    ],
)
def test_new_york_close_clock(server: datetime, expected: datetime) -> None:
    policy = NewYorkCloseServerTime()

    assert policy.to_utc(server) == expected
    assert policy.from_utc(expected) == server


def test_fixed_and_zone_clocks() -> None:
    fixed = FixedOffsetServerTime(2)
    athens = ZoneServerTime("Europe/Athens")

    assert fixed.to_utc(datetime(2024, 7, 8)) == utc(2024, 7, 7, 22)
    assert fixed.from_utc(utc(2024, 7, 7, 22)) == datetime(2024, 7, 8)
    # Europe/Athens follows EU DST: on 2024-03-12 it is still UTC+2.
    assert athens.to_utc(datetime(2024, 3, 12)) == utc(2024, 3, 11, 22)
    assert athens.from_utc(utc(2024, 3, 11, 22)) == datetime(2024, 3, 12)
    with pytest.raises(ValueError, match="unknown time zone"):
        ZoneServerTime("Mars/Olympus")
    with pytest.raises(ValueError, match="naive"):
        fixed.to_utc(utc(2024, 1, 1))


def test_server_epoch_seconds_are_server_wall_clock() -> None:
    # 1716508800 = "2024-05-24 00:00" on an MT5 D1 bar: midnight server time, not UTC.
    assert from_server_epoch(1716508800, NewYorkCloseServerTime()) == utc(2024, 5, 23, 21)


@pytest.mark.parametrize(
    ("spec", "probe", "expected"),
    [
        ("utc", datetime(2024, 1, 1), utc(2024, 1, 1)),
        ("utc+2", datetime(2024, 1, 1, 2), utc(2024, 1, 1)),
        ("-5", datetime(2024, 1, 1), utc(2024, 1, 1, 5)),
        ("ny-close", datetime(2024, 1, 8), utc(2024, 1, 7, 22)),
        ("Europe/Athens", datetime(2024, 1, 1, 2), utc(2024, 1, 1)),
    ],
)
def test_parse_policy(spec: str, probe: datetime, expected: datetime) -> None:
    assert parse_server_time_policy(spec).to_utc(probe) == expected


def test_infer_new_york_shift_from_week_opens() -> None:
    # First bar of each week on a "New York + 7h" server: Monday 00:00 all year round.
    mondays = [datetime(2024, 1, 8) + timedelta(weeks=w) for w in range(52)]
    assert infer_new_york_shift(mondays) == NewYorkCloseServerTime(7)

    # A UTC server opens the week at 22:00 in winter and 21:00 in summer: no single shift.
    utc_opens = [datetime(2024, 1, 7, 22), datetime(2024, 7, 7, 21)]
    assert infer_new_york_shift(utc_opens) is None
    assert infer_new_york_shift([datetime(2024, 1, 8, 0, 30)]) is None
