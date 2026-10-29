from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar, Event

from weeklint.budget import parse_week_arg
from weeklint.errors import WeeklintError
from weeklint.ics import load_events
from weeklint.timeutil import local_datetime

from conftest import TZ, local, write_ics


def horizon(week="2026-W45"):
    from weeklint.config import load_config

    tz = ZoneInfo(TZ)
    wr = parse_week_arg(week, tz)
    return local_datetime(wr.start, __import__("datetime").time(0, 0), tz), local_datetime(wr.end, __import__("datetime").time(0, 0), tz)


def load(make_config, path, week="2026-W45"):
    config = make_config()
    start, end = horizon(week)
    return load_events(config, start, end)


def test_single_event(make_config, workspace):
    write_ics(workspace / "calendar.ics", [{"summary": "组会", "start": local(2026, 11, 3, 10), "end": local(2026, 11, 3, 11)}])
    events, findings = load(make_config, workspace / "calendar.ics")
    assert len(events) == 1
    assert events[0].summary == "组会"
    assert events[0].minutes == 60
    assert not [f for f in findings if f.severity == "error"]


def test_all_day_event(make_config, workspace):
    write_ics(workspace / "calendar.ics", [{"summary": "假期", "start": date(2026, 11, 3), "end": date(2026, 11, 4)}])
    events, _ = load(make_config, workspace / "calendar.ics")
    assert len(events) == 1
    assert events[0].all_day is True
    assert events[0].start.date() == date(2026, 11, 3)
    assert events[0].end.date() == date(2026, 11, 4)


def test_all_day_can_be_disabled(workspace):
    write_ics(workspace / "calendar.ics", [{"summary": "假期", "start": date(2026, 11, 3), "end": date(2026, 11, 4)}])
    from weeklint.config import load_config
    import yaml

    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["planning"]["block_all_day_events"] = False
    (workspace / "weeklint.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    config = load_config(workspace / "weeklint.yaml")
    start, end = horizon()
    events, findings = load_events(config, start, end)
    assert events == []
    assert any(f.code == "all_day_ignored" for f in findings)


def test_recurring_with_exdate(make_config, workspace):
    write_ics(
        workspace / "calendar.ics",
        [
            {
                "summary": "课",
                "start": local(2026, 11, 2, 10),
                "end": local(2026, 11, 2, 11),
                "rrule": {"freq": "weekly", "count": 3},
                "exdate": [local(2026, 11, 9, 10)],
            }
        ],
    )
    events, _ = load(make_config, workspace / "calendar.ics")
    # 11-02, 11-09, 11-16; the second is EXDATE, only the first is in this week.
    assert len(events) == 1
    assert events[0].start.day == 2


def test_cancelled_and_transparent_are_ignored(make_config, workspace):
    write_ics(
        workspace / "calendar.ics",
        [
            {"summary": "取消", "start": local(2026, 11, 3, 10), "end": local(2026, 11, 3, 11), "status": "CANCELLED"},
            {"summary": "空闲", "start": local(2026, 11, 3, 10), "end": local(2026, 11, 3, 11), "transp": "TRANSPARENT"},
        ],
    )
    events, _ = load(make_config, workspace / "calendar.ics")
    assert events == []


def test_missing_end_warns(make_config, workspace):
    cal = Calendar()
    cal.add("prodid", "-//Test//Test//EN")
    cal.add("version", "2.0")
    ev = Event()
    ev.add("uid", "x@test")
    ev.add("summary", "没有结束")
    ev.add("dtstart", local(2026, 11, 3, 10))
    cal.add_component(ev)
    (workspace / "calendar.ics").write_bytes(cal.to_ical())
    events, findings = load(make_config, workspace / "calendar.ics")
    assert events == []
    assert any(f.code == "event_missing_end" for f in findings)


def test_parse_error(make_config, workspace):
    (workspace / "calendar.ics").write_text("not a calendar", encoding="utf-8")
    with pytest.raises(WeeklintError) as exc:
        load(make_config, workspace / "calendar.ics")
    assert exc.value.code == "ics_parse_error"


def test_missing_file(make_config, workspace):
    (workspace / "calendar.ics").unlink()
    with pytest.raises(WeeklintError) as exc:
        load(make_config, workspace / "calendar.ics")
    assert exc.value.code == "calendar_file_not_found"


def test_empty_calendar_list(make_config):
    config = make_config(calendar_files=[])
    start, end = horizon()
    events, findings = load_events(config, start, end)
    assert events == []
    assert any(f.code == "no_calendar_files" for f in findings)


def test_dst_recurring_keeps_wall_clock(make_config, workspace):
    write_ics(
        workspace / "calendar.ics",
        [
            {
                "summary": "晨会",
                "start": local(2026, 3, 1, 9),
                "end": local(2026, 3, 1, 10),
                "rrule": {"freq": "weekly", "count": 4},
            }
        ],
    )
    config = make_config()
    start, end = horizon("2026-W10")
    events, _ = load_events(config, start, end)
    # The event itself starts before this week; only 03-02..03-06 is in W10.
    assert events
    for ev in events:
        assert ev.start.hour == 9
        assert ev.start.utcoffset() in (timedelta(hours=-5), timedelta(hours=-4))


def test_fallback_uid_and_duplicate(make_config, workspace):
    # Two events without UID and identical content should get different fallback ids,
    # then duplicate by UID+start+end is not triggered.
    cal = Calendar()
    cal.add("prodid", "-//Test//Test//EN")
    cal.add("version", "2.0")
    for _ in range(2):
        ev = Event()
        ev.add("summary", "专注")
        ev.add("dtstart", local(2026, 11, 3, 10))
        ev.add("dtend", local(2026, 11, 3, 11))
        cal.add_component(ev)
    (workspace / "calendar.ics").write_bytes(cal.to_ical())
    events, _ = load(make_config, workspace / "calendar.ics")
    assert len(events) == 2
    assert events[0].uid != events[1].uid


def test_recurrence_override_skipped(make_config, workspace):
    cal = Calendar()
    cal.add("prodid", "-//Test//Test//EN")
    cal.add("version", "2.0")
    ev = Event()
    ev.add("uid", "x@test")
    ev.add("summary", "重复")
    ev.add("dtstart", local(2026, 11, 3, 10))
    ev.add("dtend", local(2026, 11, 3, 11))
    ev.add("rrule", {"freq": "weekly", "count": 2})
    cal.add_component(ev)
    override = Event()
    override.add("uid", "x@test")
    override.add("recurrence-id", local(2026, 11, 10, 10))
    override.add("summary", "改期")
    override.add("dtstart", local(2026, 11, 10, 14))
    override.add("dtend", local(2026, 11, 10, 15))
    cal.add_component(override)
    (workspace / "calendar.ics").write_bytes(cal.to_ical())
    events, findings = load(make_config, workspace / "calendar.ics")
    assert any(f.code == "recurrence_override_ignored" for f in findings)
    assert all(e.summary == "重复" for e in events)
