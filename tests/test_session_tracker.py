"""Replay meter readings through the session tracker."""

from datetime import UTC, datetime, timedelta

from custom_components.ere_report.session_tracker import (
    FLAG_INTERRUPTED,
    FLAG_METER_RESET,
    FLAG_ONGOING,
    SOURCE_LIVE,
    SOURCE_UNOBSERVED,
    SessionTracker,
)

T0 = datetime(2026, 7, 4, 10, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def make_tracker() -> SessionTracker:
    return SessionTracker(timedelta(minutes=15))


def test_normal_session() -> None:
    tracker = make_tracker()
    assert tracker.update(at(0), 1000.0) == []
    assert not tracker.active
    tracker.update(at(5), 1000.5)
    assert tracker.active
    tracker.update(at(30), 1003.0)
    tracker.update(at(60), 1007.25)
    assert tracker.tick(at(70)) == []
    [session] = tracker.tick(at(75))
    assert not tracker.active
    assert session.start == at(5)
    assert session.end == at(60)
    assert session.meter_start == 1000.0
    assert session.meter_end == 1007.25
    assert session.kwh == 7.25
    assert session.source == SOURCE_LIVE
    assert session.flags == []


def test_two_sessions_separated_by_idle_time() -> None:
    tracker = make_tracker()
    tracker.update(at(0), 10.0)
    tracker.update(at(1), 11.0)
    first = tracker.tick(at(20))
    tracker.update(at(100), 12.5)
    second = tracker.tick(at(120))
    assert [s.kwh for s in first + second] == [1.0, 1.5]
    assert second[0].meter_start == 11.0


def test_tiny_session_is_kept() -> None:
    """A start that smart charging stops right away still delivered energy."""
    tracker = make_tracker()
    tracker.update(at(0), 10.0)
    tracker.update(at(1), 10.01)
    [session] = tracker.tick(at(30))
    assert session.kwh == 0.01
    assert session.meter_end == 10.01


def test_restart_during_session_continues_it() -> None:
    tracker = make_tracker()
    tracker.update(at(0), 100.0)
    tracker.update(at(5), 101.0)
    tracker.tick(at(6))

    restored = make_tracker()
    restored.restore(tracker.as_dict())
    assert restored.active
    restored.update(at(10), 102.0)
    [session] = restored.tick(at(30))
    assert session.start == at(5)
    assert session.kwh == 2.0
    assert session.source == SOURCE_LIVE
    assert session.flags == [FLAG_INTERRUPTED]


def test_consumption_while_down_is_unobserved() -> None:
    tracker = make_tracker()
    tracker.update(at(0), 100.0)
    tracker.tick(at(10))

    restored = make_tracker()
    restored.restore(tracker.as_dict())
    restored.update(at(300), 120.0)
    [session] = restored.tick(at(320))
    assert session.source == SOURCE_UNOBSERVED
    assert session.start == at(10)
    assert session.end == at(300)
    assert session.kwh == 20.0


def test_long_downtime_closes_the_open_session_first() -> None:
    tracker = make_tracker()
    tracker.update(at(0), 100.0)
    tracker.update(at(5), 103.0)
    tracker.tick(at(6))

    restored = make_tracker()
    restored.restore(tracker.as_dict())
    [before] = restored.update(at(200), 110.0)
    assert before.kwh == 3.0
    assert before.source == SOURCE_LIVE
    [after] = restored.tick(at(220))
    assert after.kwh == 7.0
    assert after.source == SOURCE_UNOBSERVED


def test_unavailable_sensor_marks_gap() -> None:
    tracker = make_tracker()
    tracker.update(at(0), 50.0)
    tracker.mark_gap(at(10))
    tracker.update(at(90), 58.0)
    [session] = tracker.tick(at(110))
    assert session.source == SOURCE_UNOBSERVED
    assert session.start == at(10)


def test_gap_without_consumption_leaves_no_trace() -> None:
    tracker = make_tracker()
    tracker.update(at(0), 50.0)
    tracker.mark_gap(at(10))
    tracker.update(at(90), 50.0)
    tracker.update(at(95), 51.0)
    [session] = tracker.tick(at(120))
    assert session.source == SOURCE_LIVE
    assert session.start == at(95)


def test_meter_reset_closes_session() -> None:
    tracker = make_tracker()
    tracker.update(at(0), 500.0)
    tracker.update(at(5), 502.0)
    [session] = tracker.update(at(6), 0.0)
    assert session.kwh == 2.0
    assert session.flags == [FLAG_METER_RESET]
    tracker.update(at(7), 1.0)
    [after] = tracker.tick(at(30))
    assert after.meter_start == 0.0
    assert after.kwh == 1.0


def test_open_session_snapshot() -> None:
    tracker = make_tracker()
    assert tracker.open_session(at(0)) is None
    tracker.update(at(0), 10.0)
    tracker.update(at(5), 12.0)
    snapshot = tracker.open_session(at(8))
    assert snapshot is not None
    assert snapshot.kwh == 2.0
    assert snapshot.end == at(8)
    assert snapshot.flags == [FLAG_ONGOING]
    assert tracker.active
