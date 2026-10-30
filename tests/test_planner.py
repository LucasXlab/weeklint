from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from weeklint.budget import build_check, parse_week_arg
from weeklint.ics import load_events
from weeklint.planner import plan_week, split_minutes, task_sort_key
from weeklint.report import write_plan_files
from weeklint.tasks import parse_task_text
from weeklint.model import minutes_between
from weeklint.timeutil import local_datetime, parse_iso_datetime

from conftest import TZ, local, write_ics

TZINFO = ZoneInfo(TZ)


def make(workspace, make_config, tasks_text="", events=None, now="2026-11-02T09:00:00-05:00", **planning):
    write_ics(workspace / "calendar.ics", events or [])
    config = make_config(**planning)
    tz = config.tz
    wr = parse_week_arg("2026-W45", tz)
    start = local_datetime(wr.start, time(0, 0), tz)
    end = local_datetime(wr.end, time(0, 0), tz)
    evs, findings = load_events(config, start, end)
    check = build_check(config, parse_task_text(tasks_text, tz, config.planning.default_estimate_minutes), evs, parse_iso_datetime(now, tz), wr, findings)
    return config, check, plan_week(config, check)


@pytest.mark.parametrize(
    ("total", "expected"),
    [(120, [120]), (121, [61, 60]), (240, [120, 120]), (250, [84, 83, 83]), (30, [30]), (45, [45])],
)
def test_split_minutes(total, expected):
    assert split_minutes(total, 120, 30) == expected
    assert sum(split_minutes(total, 120, 30)) == total


def test_task_sort_key():
    now = parse_iso_datetime("2026-11-02T09:00:00-05:00", TZINFO)
    tasks = parse_task_text(
        "- [ ] b @priority(high) @estimate(30m) @id(b)\n"
        "- [ ] a @priority(high) @estimate(30m) @id(a)\n",
        TZINFO,
        60,
    )
    assert [t.id for t in sorted(tasks, key=lambda t: task_sort_key(t, now))] == ["a", "b"]


def test_high_priority_goes_morning(workspace, make_config):
    _, check, plan = make(workspace, make_config, "- [ ] 论文 @priority(high) @estimate(60m)\n")
    assert plan.blocks[0].start.hour < 12


def test_one_block_per_task_per_day(workspace, make_config):
    _, check, plan = make(workspace, make_config, "- [ ] 论文 @priority(high) @estimate(180m)\n")
    days = [b.start.date() for b in plan.blocks if b.task_id == plan.blocks[0].task_id]
    assert len(days) == len(set(days))


def test_deep_work_limit_unscheduled(workspace, make_config):
    _, check, plan = make(
        workspace,
        make_config,
        "- [ ] 大任务 @priority(high) @estimate(500m)\n",
        max_deep_work_minutes_per_day=60,
    )
    assert plan.summary["tasksUnscheduled"] == 1
    assert plan.unscheduled[0][1] == 500
    assert plan.unscheduled[0][2] == "deep_work_limit"
    assert any(f.code == "task_unscheduled" and f.severity == "error" for f in plan.findings)


def test_task_limit_unscheduled(workspace, make_config):
    _, check, plan = make(
        workspace,
        make_config,
        "".join(f"- [ ] 任务{i} @estimate(30m)\n" for i in range(6)),
        max_tasks_per_day=1,
    )
    assert plan.summary["tasksUnscheduled"] == 1
    assert plan.unscheduled[0][2] == "task_limit"

def test_rollback_has_no_half_task(workspace, make_config):
    _, check, plan = make(
        workspace,
        make_config,
        "- [ ] 两小时 @estimate(180m)\n",
        work_hours={
            "mon": ["09:00-12:00"],
            "tue": [],
            "wed": [],
            "thu": [],
            "fri": [],
            "sat": [],
            "sun": [],
        },
        gap_between_tasks_minutes=10,
    )
    assert plan.blocks == []
    assert plan.summary["tasksUnscheduled"] == 1
    assert plan.unscheduled[0][1] == 180
    assert plan.summary["unscheduledMinutes"] == 180


def test_lock_second_run_idempotent(workspace, make_config):
    config, check, first = make(workspace, make_config, "- [ ] 论文 @priority(high) @estimate(120m)\n")
    write_plan_files(first, config)
    _, check2, second = make(workspace, make_config, "- [ ] 论文 @priority(high) @estimate(120m)\n", now="2026-11-02T12:00:00-05:00")
    assert second.blocks
    assert all(b.locked for b in second.blocks)
    assert [(b.task_id, b.start, b.end) for b in first.blocks] == [(b.task_id, b.start, b.end) for b in second.blocks]


def test_locked_block_dropped_on_event_conflict(workspace, make_config):
    config, check, first = make(workspace, make_config, "- [ ] 论文 @priority(high) @estimate(120m)\n")
    write_plan_files(first, config)
    _, check2, second = make(
        workspace,
        make_config,
        "- [ ] 论文 @priority(high) @estimate(120m)\n",
        events=[{"summary": "冲突", "start": local(2026, 11, 2, 9), "end": local(2026, 11, 2, 10)}],
    )
    assert any(f.code == "locked_block_dropped" for f in second.findings)
    assert not any(b.locked for b in second.blocks)


def test_unscheduled_keeps_locked_block(workspace, make_config):
    config, check, first = make(workspace, make_config, "- [ ] 论文 @estimate(120m)\n")
    # Lock a 120m block, then change the estimate down to 60m so the locked block
    # already exceeds the estimate; it must be dropped, not silently kept.
    write_plan_files(first, config)
    _, check2, second = make(workspace, make_config, "- [ ] 论文 @estimate(60m)\n")
    assert all(not b.locked for b in second.blocks)


def test_at_risk_deadline(workspace, make_config):
    _, check, plan = make(
        workspace,
        make_config,
        "- [ ] 论文 @priority(high) @estimate(120m) @due(2026-11-02T10:00)\n",
    )
    assert any(f.code == "deadline_at_risk" for f in plan.findings)


def test_summary_and_files(workspace, make_config):
    config, check, plan = make(workspace, make_config, "- [ ] 论文 @estimate(90m)\n")
    assert plan.summary["scheduledMinutes"] == 90
    assert plan.summary["tasksScheduled"] == 1
    assert plan.summary["capacityMinutes"] == check.capacity["usableMinutes"]
    assert plan.files["planJson"].endswith("plan.json")


def test_small_task_cannot_use_sub_min_block_slot(workspace, make_config):
    _, check, plan = make(
        workspace,
        make_config,
        "- [ ] 小任务 @estimate(20m)\n",
        work_hours={"mon": ["09:00-09:20"], "tue": [], "wed": [], "thu": [], "fri": [], "sat": [], "sun": []},
    )
    assert check.capacity["usableMinutes"] == 0
    assert plan.blocks == []
    assert plan.unscheduled[0][1] == 20


def test_spring_forward_capacity_is_elapsed_minutes(workspace, make_config):
    write_ics(workspace / "calendar.ics", [])
    config = make_config(
        include_weekends=True,
        work_hours={"mon": [], "tue": [], "wed": [], "thu": [], "fri": [], "sat": [], "sun": ["01:00-04:00"]},
        min_block_minutes=15,
        max_block_minutes=240,
    )
    tz = config.tz
    wr = parse_week_arg("2026-W10", tz)
    start = local_datetime(wr.start, time(0, 0), tz)
    end = local_datetime(wr.end, time(0, 0), tz)
    evs, findings = load_events(config, start, end)
    check = build_check(
        config,
        parse_task_text("- [ ] 夜班 @estimate(150m)\n", tz, config.planning.default_estimate_minutes),
        evs,
        parse_iso_datetime("2026-03-02T08:00:00-05:00", tz),
        wr,
        findings,
    )
    assert check.capacity["workMinutes"] == 120
    assert check.day_capacity[wr.start + __import__("datetime").timedelta(days=6)]["workMinutes"] == 120
    plan = plan_week(config, check)
    assert plan.blocks == []
    assert plan.summary["unscheduledMinutes"] == 150


def test_spring_forward_block_minutes_are_elapsed(workspace, make_config):
    write_ics(workspace / "calendar.ics", [])
    config = make_config(
        include_weekends=True,
        work_hours={"mon": [], "tue": [], "wed": [], "thu": [], "fri": [], "sat": [], "sun": ["01:00-04:00"]},
        min_block_minutes=15,
        max_block_minutes=240,
    )
    tz = config.tz
    wr = parse_week_arg("2026-W10", tz)
    start = local_datetime(wr.start, time(0, 0), tz)
    end = local_datetime(wr.end, time(0, 0), tz)
    evs, findings = load_events(config, start, end)
    check = build_check(
        config,
        parse_task_text("- [ ] 夜班 @estimate(90m)\n", tz, config.planning.default_estimate_minutes),
        evs,
        parse_iso_datetime("2026-03-02T08:00:00-05:00", tz),
        wr,
        findings,
    )
    plan = plan_week(config, check)
    assert len(plan.blocks) == 1
    block = plan.blocks[0]
    assert minutes_between(block.start, block.end) == 90
    assert int((block.end.astimezone(__import__("datetime").timezone.utc) - block.start.astimezone(__import__("datetime").timezone.utc)).total_seconds() // 60) == 90
