"""Week range, busy/free computation, demand and findings."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo

from .config import Config
from .errors import WeeklintError
from .model import (
    CalendarEvent,
    CheckData,
    Finding,
    FreeSlot,
    PRIORITY_RANK,
    Task,
    WeekRange,
    minutes_between,
)
from .timeutil import add_minutes, local_datetime, parse_iso_datetime


def _err(code: str, message: str, **detail: object) -> WeeklintError:
    return WeeklintError(code, message, detail)


def parse_week_arg(value: str, tz: ZoneInfo) -> WeekRange:
    try:
        if not re.fullmatch(r"\d{4}-W\d{2}", value):
            raise ValueError
        year_s, week_s = value.split("-W", 1)
        year, week = int(year_s), int(week_s)
        if not (1 <= week <= 53):
            raise ValueError
        monday = date.fromisocalendar(year, week, 1)
        week_end = monday + timedelta(days=7)
    except (ValueError, AttributeError, OverflowError):
        raise _err(
            "invalid_week",
            f"--week 的值 {value!r} 无效：请写成 YYYY-Www，例如 2026-W45。",
            value=value,
        ) from None
    return WeekRange(iso=f"{year}-W{week:02d}", start=monday, end=week_end, timezone=str(tz))


def week_for_now(now: datetime, tz: ZoneInfo) -> WeekRange:
    local = now.astimezone(tz)
    iso_year, iso_week, _ = local.date().isocalendar()
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    try:
        week_end = monday + timedelta(days=7)
    except OverflowError:
        raise _err("invalid_now", f"本周范围超出日期可表示范围：{monday.isoformat()}。") from None
    return WeekRange(iso=f"{iso_year}-W{iso_week:02d}", start=monday, end=week_end, timezone=str(tz))


def resolve_now(cli_now: str | None, env: dict[str, str], tz: ZoneInfo) -> datetime:
    if cli_now:
        raw = cli_now
        code = "invalid_now"
        label = "--now"
    else:
        raw = env.get("WEEKLINT_NOW") or ""
        code = "invalid_env"
        label = "WEEKLINT_NOW"
    if raw.strip():
        try:
            value = raw.strip()
            if len(value) == 10 and value[4] == "-" and value[7] == "-":
                day = date.fromisoformat(value)
                return local_datetime(day, time(0, 0), tz)
            return parse_iso_datetime(value, tz)
        except (ValueError, OverflowError):
            raise _err(
                code,
                f"{label} 的值 {raw!r} 不是合法的 ISO 8601 时间。例：2026-11-02T09:00:00+08:00。",
                value=raw,
            ) from None
    return datetime.now(tz)


def _subtract(intervals: list[tuple[datetime, datetime]], blocks: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Return intervals minus busy blocks (both sorted, half-open)."""
    if not blocks:
        return intervals
    result: list[tuple[datetime, datetime]] = []
    blocks = sorted(blocks)
    for start, end in intervals:
        cursor = start
        for bstart, bend in blocks:
            if bend <= cursor:
                continue
            if bstart >= end:
                break
            if bstart > cursor:
                result.append((cursor, min(bstart, end)))
            cursor = max(cursor, bend)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return [(a, b) for a, b in result if b > a]


def _merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _day_work_intervals(config: Config, day: date) -> list[tuple[datetime, datetime]]:
    key = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[day.weekday()]
    if not config.planning.include_weekends and day.weekday() >= 5:
        return []
    out = []
    for start_t, end_t in config.planning.work_hours.get(key, []):
        start = local_datetime(day, start_t, config.tz)
        end = local_datetime(day, end_t, config.tz)
        if end > start:
            out.append((start, end))
    return out


def build_check(config: Config, tasks: list[Task], events: list[CalendarEvent], now: datetime, week: WeekRange, event_findings: list[Finding] | None = None) -> CheckData:
    tz = config.tz
    day_capacity: dict[date, dict[str, int]] = {}
    day_slots: dict[date, list[FreeSlot]] = {}
    slots: list[FreeSlot] = []
    work_total = busy_total = buffer_total = 0
    findings: list[Finding] = list(event_findings or [])

    for offset in range(7):
        day = week.start + timedelta(days=offset)
        work = _day_work_intervals(config, day)
        work_minutes = sum(minutes_between(a, b) for a, b in work)
        work_total += work_minutes
        # Clip events to this day's work intervals, merge, then add buffer.
        raw: list[tuple[datetime, datetime]] = []
        extended: list[tuple[datetime, datetime]] = []
        buffer_minutes = config.planning.buffer_after_event_minutes
        for ev in events:
            for wstart, wend in work:
                s, e = max(ev.start, wstart), min(ev.end, wend)
                if e > s:
                    raw.append((s, e))
                    extended.append((s, min(add_minutes(e, buffer_minutes), wend)))
        raw = _merge(raw)
        extended = _merge(extended)
        busy = sum(minutes_between(a, b) for a, b in extended)
        raw_minutes = sum(minutes_between(a, b) for a, b in raw)
        busy_total += busy
        buffer_total += max(0, busy - raw_minutes)
        free = _subtract(work, extended)
        free_minutes = sum(minutes_between(a, b) for a, b in free)
        usable = sum(minutes_between(a, b) for a, b in free if minutes_between(a, b) >= config.planning.min_block_minutes)
        day_slots[day] = [FreeSlot(day, a, b) for a, b in free]
        slots.extend(day_slots[day])
        day_capacity[day] = {
            "workMinutes": work_minutes,
            "busyMinutes": busy,
            "freeMinutes": free_minutes,
            "usableMinutes": usable,
        }
        # A day with only fragments too short for a task block is worth flagging.
        fragments = [minutes_between(a, b) for a, b in free if 0 < minutes_between(a, b) < config.planning.min_block_minutes]
        if fragments and usable == 0:
            findings.append(
                Finding(
                    "fragmented_day",
                    "warning",
                    f"{day.isoformat()} 的 {sum(fragments)} 分钟空闲都被会议切成了小于 {config.planning.min_block_minutes} 分钟的碎片，排不下一个任务块。",
                    day=day.isoformat(),
                    value=sum(fragments),
                )
            )
        if work_minutes == 0 and (config.planning.include_weekends or day.weekday() < 5):
            findings.append(Finding("no_work_hours", "warning", f"{day.isoformat()} 没有配置工作时间，这一天不排任务。", day=day.isoformat()))

    capacity = {
        "workMinutes": work_total,
        "busyMinutes": busy_total,
        "bufferMinutes": buffer_total,
        "freeMinutes": sum(d["freeMinutes"] for d in day_capacity.values()),
        "usableMinutes": sum(d["usableMinutes"] for d in day_capacity.values()),
    }

    open_tasks = [t for t in tasks if not t.completed]
    completed_count = sum(1 for t in tasks if t.completed)
    week_end_dt = local_datetime(week.end, time(0, 0), tz)
    in_scope: list[Task] = []
    out_of_scope: list[Task] = []
    for task in open_tasks:
        if task.due is None or task.due <= week_end_dt:
            in_scope.append(task)
        else:
            out_of_scope.append(task)
            findings.append(
                Finding(
                    "task_after_horizon",
                    "info",
                    f"任务「{task.title}」的截止时间 {task.due.isoformat()} 晚于本周，未计入本周需求。",
                    task_id=task.id,
                )
            )
    if not open_tasks:
        findings.append(Finding("no_tasks", "warning", f"任务文件里没有未完成任务：{config.planning.task_file}。"))
    for task in in_scope:
        if task.dst_adjusted:
            findings.append(
                Finding(
                    "dst_adjusted",
                    "warning",
                    f"任务「{task.title}」的截止时间落在时区跳变点，已按最早一次/顺延规则调整。",
                    task_id=task.id,
                )
            )
        if not task.estimated:
            findings.append(
                Finding(
                    "task_unestimated",
                    "warning",
                    f"任务「{task.title}」没有写 @estimate，按默认 {config.planning.default_estimate_minutes} 分钟计算。",
                    task_id=task.id,
                    value=config.planning.default_estimate_minutes,
                )
            )
        if task.due is not None and task.due < now:
            findings.append(
                Finding(
                    "overdue_task",
                    "warning",
                    f"任务「{task.title}」已过期：截止 {task.due.isoformat()}。",
                    task_id=task.id,
                )
            )

    demand_minutes = sum(t.estimate_minutes for t in in_scope)
    unestimated = sum(1 for t in in_scope if not t.estimated)
    gap = max(0, demand_minutes - capacity["usableMinutes"])
    overcommitted = gap > 0
    if overcommitted:
        findings.append(
            Finding(
                "overcommitted",
                "error",
                f"本周可用 {capacity['usableMinutes']} 分钟，任务需要 {demand_minutes} 分钟，缺口 {gap} 分钟。",
                value=gap,
            )
        )
        for task in in_scope:
            if task.due is not None:
                findings.append(
                    Finding(
                        "deadline_at_risk",
                        "error",
                        "本周容量不足，可能无法在截止前完成。",
                        task_id=task.id,
                    )
                )
    findings.sort(key=lambda f: f.sort_key())
    return CheckData(
        week=week,
        now=now,
        generated_at=now,
        tasks=in_scope,
        all_tasks=tasks,
        open_tasks=open_tasks,
        completed_count=completed_count,
        events=events,
        slots=slots,
        day_slots=day_slots,
        day_work_minutes={d: c["workMinutes"] for d, c in day_capacity.items()},
        day_capacity=day_capacity,
        capacity=capacity,
        demand={"taskCount": len(in_scope), "estimatedMinutes": demand_minutes, "unestimatedCount": unestimated},
        gap_minutes=gap,
        overcommitted=overcommitted,
        findings=findings,
        out_of_scope=out_of_scope,
    )


def day_capacity_dicts(check: CheckData) -> list[dict[str, object]]:
    out = []
    for offset in range(7):
        day = check.week.start + timedelta(days=offset)
        cap = check.day_capacity.get(day, {"workMinutes": 0, "busyMinutes": 0, "freeMinutes": 0, "usableMinutes": 0})
        out.append({"date": day.isoformat(), **cap})
    return out
