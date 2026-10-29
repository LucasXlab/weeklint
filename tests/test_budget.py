from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import yaml

from weeklint.budget import build_check, day_capacity_dicts, parse_week_arg, week_for_now
from weeklint.config import load_config
from weeklint.errors import WeeklintError
from weeklint.ics import load_events
from weeklint.model import CalendarEvent, Finding, Task
from weeklint.tasks import parse_task_text
from weeklint.timeutil import local_datetime, parse_iso_datetime

from conftest import TZ, local, write_ics

TZINFO = ZoneInfo(TZ)


def tasks(text, default=60):
    return parse_task_text(text, TZINFO, default)


def run(workspace, make_config, task_text="", events=None, week="2026-W45", now="2026-11-02T09:00:00-05:00", **planning):
    write_ics(workspace / "calendar.ics", events or []) if events is not None else None
    config = make_config(**planning)
    wr = parse_week_arg(week, config.tz)
    start = local_datetime(wr.start, time(0, 0), config.tz)
    end = local_datetime(wr.end, time(0, 0), config.tz)
    evs, findings = load_events(config, start, end)
    return build_check(config, tasks(task_text), evs, parse_iso_datetime(now, config.tz), wr, findings)


def test_capacity_without_events(workspace, make_config):
    check = run(workspace, make_config)
    assert check.capacity["workMinutes"] == 5 * 450
    assert check.capacity["busyMinutes"] == 0
    assert check.capacity["freeMinutes"] == 5 * 450
    assert check.capacity["usableMinutes"] == 5 * 450
    assert len(check.slots) == 10


def test_event_and_buffer(workspace, make_config):
    check = run(
        workspace,
        make_config,
        events=[{"summary": "会", "start": local(2026, 11, 3, 10), "end": local(2026, 11, 3, 11)}],
    )
    assert check.capacity["busyMinutes"] == 70
    assert check.capacity["freeMinutes"] == 5 * 450 - 70
    assert check.capacity["usableMinutes"] == 5 * 450 - 70


def test_buffer_clipped_to_work_end(workspace, make_config):
    # Event ends at 11:50; buffer must not leak into lunch (12:00-13:30).
    check = run(
        workspace,
        make_config,
        events=[{"summary": "会", "start": local(2026, 11, 3, 11, 0), "end": local(2026, 11, 3, 11, 50)}],
    )
    assert check.capacity["busyMinutes"] == 60
    assert check.capacity["bufferMinutes"] == 10
    assert check.capacity["freeMinutes"] == 5 * 450 - 60


def test_task_demand_and_gap(workspace, make_config):
    check = run(workspace, make_config, "- [ ] 大任务 @estimate(2400m)\n")
    assert check.demand["taskCount"] == 1
    assert check.demand["estimatedMinutes"] == 2400
    # The estimate cap is 2400; capacity is 2250, so gap is 150.
    assert check.gap_minutes == 150
    assert check.overcommitted is True


def test_overcommitted_and_deadline_findings(workspace, make_config):
    check = run(workspace, make_config, "- [ ] 大任务 @estimate(2400m) @due(2026-11-05)\n")
    codes = [f.code for f in check.findings]
    assert "overcommitted" in codes
    assert "deadline_at_risk" in codes
    assert check.overcommitted is True


def test_no_tasks_and_no_calendar(workspace, make_config):
    config = make_config(calendar_files=[])
    wr = parse_week_arg("2026-W45", config.tz)
    check = build_check(
        config,
        [],
        [],
        parse_iso_datetime("2026-11-02T09:00:00-05:00", config.tz),
        wr,
        [Finding("no_calendar_files", "warning", "no calendar")],
    )
    codes = [f.code for f in check.findings]
    assert "no_tasks" in codes
    assert "no_calendar_files" in codes
    assert check.capacity["workMinutes"] == 2250


def test_unestimated_and_overdue(workspace, make_config):
    check = run(workspace, make_config, "- [ ] 未估算 @due(2026-10-30)\n")
    codes = [f.code for f in check.findings]
    assert "task_unestimated" in codes
    assert "overdue_task" in codes


def test_task_after_horizon_not_in_demand(workspace, make_config):
    check = run(workspace, make_config, "- [ ] 下周任务 @estimate(120m) @due(2026-11-20)\n")
    assert check.demand["estimatedMinutes"] == 0
    assert check.demand["taskCount"] == 0
    assert any(f.code == "task_after_horizon" for f in check.findings)


def test_fragmented_day(workspace, make_config):
    check = run(
        workspace,
        make_config,
        events=[{"summary": "会", "start": local(2026, 11, 2, 9, 10), "end": local(2026, 11, 2, 9, 20)}],
        min_block_minutes=60,
        work_hours={
            "mon": ["09:00-10:00"],
            "tue": ["09:00-12:00", "13:30-18:00"],
            "wed": ["09:00-12:00", "13:30-18:00"],
            "thu": ["09:00-12:00", "13:30-18:00"],
            "fri": ["09:00-12:00", "13:30-18:00"],
            "sat": [],
            "sun": [],
        },
    )
    day = date(2026, 11, 2)
    assert check.day_capacity[day]["usableMinutes"] == 0
    assert any(f.code == "fragmented_day" and f.day == day.isoformat() for f in check.findings)


def test_no_work_hours_for_weekday(workspace):
    import yaml

    data = yaml.safe_load((workspace / "weeklint.yaml").read_text())
    data["planning"]["work_hours"]["mon"] = []
    (workspace / "weeklint.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    config = load_config(workspace / "weeklint.yaml")
    wr = parse_week_arg("2026-W45", config.tz)
    check = build_check(config, [], [], parse_iso_datetime("2026-11-02T09:00:00-05:00", config.tz), wr, [])
    assert any(f.code == "no_work_hours" and f.day == "2026-11-02" for f in check.findings)


def test_days_shape(workspace, make_config):
    check = run(workspace, make_config)
    days = day_capacity_dicts(check)
    assert len(days) == 7
    assert days[0]["date"] == "2026-11-02"
    assert set(days[0]) == {"date", "workMinutes", "busyMinutes", "freeMinutes", "usableMinutes"}
    assert days[5]["usableMinutes"] == 0


def test_week_for_now_crosses_year():
    now = parse_iso_datetime("2026-12-30T10:00:00-05:00", TZINFO)
    wr = week_for_now(now, TZINFO)
    assert wr.iso == "2026-W53"
    assert wr.start == date(2026, 12, 28)
    assert wr.end == date(2027, 1, 4)


def test_invalid_week():
    with pytest.raises(WeeklintError) as exc:
        parse_week_arg("2027-W53", TZINFO)
    assert exc.value.code == "invalid_week"


def test_dst_nonexistent_local_time_shifts_forward():
    # 2026-03-08 02:30 does not exist in New York.
    dt = local_datetime(date(2026, 3, 8), time(2, 30), TZINFO)
    assert dt.hour == 3 and dt.minute == 30
    assert dt.utcoffset() == timedelta(hours=-4)


def test_dst_ambiguous_uses_fold_zero():
    dt = local_datetime(date(2026, 11, 1), time(1, 30), TZINFO)
    assert dt.fold == 0


def test_dst_adjusted_finding(workspace, make_config):
    check = run(
        workspace,
        make_config,
        "- [ ] 春季任务 @due(2026-03-08T02:30) @estimate(30m)\n",
        week="2026-W10",
        now="2026-03-08T00:00:00-05:00",
    )
    assert any(f.code == "dst_adjusted" for f in check.findings)
