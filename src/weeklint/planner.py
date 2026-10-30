"""Deterministic scheduling on top of the capacity numbers."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .config import Config
from .errors import WeeklintError
from .model import Block, CheckData, Finding, PlanData, PRIORITY_RANK, Task, minutes_between
from .timeutil import add_minutes, local_datetime, parse_iso_datetime


REASON_LABELS = {
    "no_capacity": "没有足够长的空档",
    "deep_work_limit": "触发当天高优先级深度工作上限",
    "task_limit": "触发当天任务数上限",
}


def reason_label(code: str) -> str:
    return REASON_LABELS.get(code, code)


def task_sort_key(task: Task, now: datetime):
    overdue = 0 if (task.due is not None and task.due < now) else 1
    due_key = (0, task.due.timestamp()) if task.due is not None else (1, 0.0)
    return (overdue, due_key, PRIORITY_RANK.get(task.priority, 9), -task.estimate_minutes, task.id)


def split_minutes(total: int, max_block: int, min_block: int) -> list[int]:
    if total <= max_block:
        return [total]
    n = math.ceil(total / max_block)
    while n > 1 and total / n < min_block:
        n -= 1
    base, extra = divmod(total, n)
    return [base + 1] * extra + [base] * (n - extra)


def _find_slot(
    slots: list[list[datetime]], duration: int, gap: int, high: bool, min_block: int
) -> list[datetime] | None:
    """Find a slot to mutate; returns the same list object or None.

    A block may be shorter than ``min_block`` when the task itself is smaller,
    but it still must go into a free interval of at least ``min_block``.
    """
    needed = max(duration, min_block)
    candidates = [s for s in slots if minutes_between(s[0], s[1]) >= needed]
    if not candidates:
        return None
    if high:
        morning = [s for s in candidates if s[0].hour < 12]
        if morning:
            return morning[0]
    return candidates[0]


def _remove(slots: list[list[datetime]], start: datetime, end: datetime) -> list[list[datetime]]:
    out: list[list[datetime]] = []
    for s, e in slots:
        if end <= s or start >= e:
            out.append([s, e])
            continue
        if start > s:
            out.append([s, start])
        if end < e:
            out.append([end, e])
    return out


def _place(
    slots: list[list[datetime]], duration: int, gap: int, high: bool, min_block: int
) -> tuple[datetime, datetime] | None:
    slot = _find_slot(slots, duration, gap, high, min_block)
    if slot is None:
        return None
    start = slot[0]
    end = add_minutes(start, duration)
    slot[0] = add_minutes(end, gap)
    if slot[0] >= slot[1]:
        slots.remove(slot)
    return start, end


def _load_previous(config: Config) -> dict | None:
    path = config.planning.output_dir / "plan.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"__invalid__": True}
    except (OSError, ValueError):
        return {"__invalid__": True}


def _parse_plan_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _locked_blocks(config: Config, check: CheckData, previous: dict | None) -> tuple[list[Block], list[Finding]]:
    findings: list[Finding] = []
    if not previous or not config.planning.lock_existing_plan:
        return [], findings
    if previous.get("__invalid__"):
        findings.append(Finding("previous_plan_ignored", "warning", "上一次的 plan.json 无法解析，未复用旧块。"))
        return [], findings
    if previous.get("version") not in (None, "0.1.0"):
        findings.append(Finding("previous_plan_ignored", "warning", "上一次的 plan.json 版本不同，未复用旧块。"))
        return [], findings
    try:
        week = previous.get("week") or {}
        if week.get("start") != check.week.start.isoformat():
            findings.append(Finding("previous_plan_ignored", "warning", "上一次的 plan.json 不是本周的，未复用旧块。"))
            return [], findings
    except AttributeError:
        findings.append(Finding("previous_plan_ignored", "warning", "上一次的 plan.json 结构不完整，未复用旧块。"))
        return [], findings
    raw_blocks = previous.get("blocks")
    if not isinstance(raw_blocks, list):
        findings.append(Finding("previous_plan_ignored", "warning", "上一次的 plan.json 里 blocks 不是数组，未复用旧块。"))
        return [], findings
    by_id = {t.id: t for t in check.tasks}
    week_start = local_datetime(check.week.start, time(0, 0), config.tz)
    week_end = local_datetime(check.week.end, time(0, 0), config.tz)
    event_intervals = [
        (max(e.start, week_start), min(e.end + timedelta(minutes=config.planning.buffer_after_event_minutes), week_end))
        for e in check.events
    ]
    kept: list[Block] = []
    per_task: dict[str, int] = {}
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        task = by_id.get(raw.get("taskId"))
        start = _parse_plan_dt(raw.get("start"))
        end = _parse_plan_dt(raw.get("end"))
        if task is None or start is None or end is None:
            findings.append(Finding("locked_block_dropped", "warning", "旧计划里有一个块对应的任务已删除或完成，已丢弃。"))
            continue
        if start.tzinfo is None or end.tzinfo is None:
            start = start.replace(tzinfo=config.tz)
            end = end.replace(tzinfo=config.tz)
        start = start.astimezone(config.tz)
        end = end.astimezone(config.tz)
        reason = None
        if not (week_start <= start < week_end and week_start < end <= week_end and end > start):
            reason = "块不在本周范围内"
        elif any(start < e_end and end > e_start for e_start, e_end in event_intervals):
            reason = "块与日历事件冲突"
        else:
            day = start.date()
            work = _work_for_day(config, day)
            if not any(w_start <= start and end <= w_end for w_start, w_end in work):
                reason = "块不在工作时间内"
            elif per_task.get(task.id, 0) + minutes_between(start, end) > task.estimate_minutes:
                reason = "块总分钟超过任务估算"
            elif any(start < b.end and end > b.start for b in kept):
                reason = "块与旧计划里的另一个块重叠"
        if reason:
            findings.append(
                Finding("locked_block_dropped", "warning", f"旧计划里的块「{task.title}」被丢弃：{reason}。", task_id=task.id)
            )
            continue
        per_task[task.id] = per_task.get(task.id, 0) + minutes_between(start, end)
        kept.append(Block(task.id, task.title, start, end, True, block_reason(task, start), task.priority))
    kept.sort(key=lambda b: (b.start, b.task_id))
    return kept, findings


def block_reason(task: Task, start: datetime) -> str:
    due = f"截止 {task.due.isoformat(timespec='minutes')}" if task.due else "没有截止时间"
    period = "上午" if start.hour < 12 else "下午"
    return f"{due}，优先级 {task.priority}；放在 {start.strftime('%m-%d')} {period} {start.strftime('%H:%M')} 的第一个足够长空档。"

def _work_for_day(config: Config, day: date) -> list[tuple[datetime, datetime]]:
    key = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[day.weekday()]
    if not config.planning.include_weekends and day.weekday() >= 5:
        return []
    out = []
    for a, b in config.planning.work_hours.get(key, []):
        out.append((local_datetime(day, a, config.tz), local_datetime(day, b, config.tz)))
    return out


def plan_week(config: Config, check: CheckData) -> PlanData:
    previous = _load_previous(config)
    locked, locked_findings = _locked_blocks(config, check, previous)
    findings: list[Finding] = [f for f in check.findings if f.code != "deadline_at_risk" and f.code != "locked_block_dropped"]
    findings.extend(locked_findings)

    # Mutable free slots: each item is [start, end].
    slots: dict[date, list[list[datetime]]] = {}
    for offset in range(7):
        day = check.week.start + timedelta(days=offset)
        slots[day] = [[s.start, s.end] for s in check.day_slots.get(day, [])]
    day_used_tasks: dict[date, set[str]] = {d: set() for d in slots}
    day_deep: dict[date, int] = {d: 0 for d in slots}
    for block in locked:
        slots[block.start.date()] = _remove(slots[block.start.date()], block.start, block.end)
        day_used_tasks[block.start.date()].add(block.task_id)
        if block.priority == "high":
            day_deep[block.start.date()] += block.minutes

    blocks: list[Block] = list(locked)
    unscheduled: list[tuple[Task, int, str]] = []
    locked_minutes: dict[str, int] = {}
    for block in locked:
        locked_minutes[block.task_id] = locked_minutes.get(block.task_id, 0) + block.minutes

    tasks = sorted(check.tasks, key=lambda t: task_sort_key(t, check.now))
    for task in tasks:
        already = locked_minutes.get(task.id, 0)
        remaining = max(0, task.estimate_minutes - already)
        if remaining == 0:
            continue
        chunks = split_minutes(remaining, config.planning.max_block_minutes, config.planning.min_block_minutes)
        if not chunks:
            continue
        trial: list[Block] = []
        trial_slots = {d: [list(s) for s in v] for d, v in slots.items()}
        trial_tasks = {d: set(v) for d, v in day_used_tasks.items()}
        trial_deep = dict(day_deep)
        placed = 0
        reason: str | None = None
        saw_deep = False
        saw_task = False
        saw_no = False
        for chunk in chunks:
            placement: tuple[date, datetime, datetime] | None = None
            for day in sorted(trial_slots):
                if not trial_slots[day]:
                    continue
                if task.id in trial_tasks[day]:
                    continue
                if len(trial_tasks[day]) >= config.planning.max_tasks_per_day:
                    saw_task = True
                    continue
                if task.priority == "high" and config.planning.max_deep_work_minutes_per_day > 0 and trial_deep[day] + chunk > config.planning.max_deep_work_minutes_per_day:
                    saw_deep = True
                    continue
                got = _place(
                    trial_slots[day],
                    chunk,
                    config.planning.gap_between_tasks_minutes,
                    task.priority == "high",
                    config.planning.min_block_minutes,
                )
                if got:
                    placement = (day, got[0], got[1])
                    break
                saw_no = True
            if placement is None:
                if saw_no:
                    reason = "no_capacity"
                elif saw_deep and not saw_task:
                    reason = "deep_work_limit"
                elif saw_task and not saw_deep:
                    reason = "task_limit"
                else:
                    reason = "no_capacity"
                break
            day, start, end = placement
            trial.append(Block(task.id, task.title, start, end, False, block_reason(task, start), task.priority))
            trial_tasks[day].add(task.id)
            if task.priority == "high":
                trial_deep[day] += chunk
            placed += chunk
        if reason is None and placed == remaining:
            slots = trial_slots
            day_used_tasks = trial_tasks
            day_deep = trial_deep
            blocks.extend(trial)
            continue
        # Roll back only newly placed blocks; locked blocks stay.
        # The trial blocks are rolled back, so none of ``placed`` counts; the
        # whole task remains unscheduled.
        unscheduled.append((task, remaining, reason or "no_capacity"))
        findings.append(
            Finding(
                "task_unscheduled",
                "error",
                f"任务「{task.title}」还有 {remaining} 分钟没排下：{reason_label(reason or 'no_capacity')}。",
                task_id=task.id,
                value=remaining,
            )
        )

    scheduled_by_task: dict[str, int] = {}
    for block in blocks:
        scheduled_by_task[block.task_id] = scheduled_by_task.get(block.task_id, 0) + block.minutes
    for task in check.tasks:
        if task.id in scheduled_by_task and task.due is not None:
            last = max(b.end for b in blocks if b.task_id == task.id)
            if last > task.due:
                findings.append(
                    Finding(
                        "deadline_at_risk",
                        "error",
                        f"任务「{task.title}」预计排到 {last.isoformat()}，晚于截止 {task.due.isoformat()}。",
                        task_id=task.id,
                    )
                )
    for task, _remaining, reason in unscheduled:
        if task.due is not None:
            findings.append(
                Finding(
                    "deadline_at_risk",
                    "error",
                    f"任务「{task.title}」截止 {task.due.isoformat()}，但因 {reason} 未排程。",
                    task_id=task.id,
                )
            )
    findings.sort(key=lambda f: f.sort_key())
    blocks.sort(key=lambda b: (b.start, b.task_id))
    scheduled_minutes = sum(b.minutes for b in blocks)
    unscheduled_minutes = sum(r for _, r, _ in unscheduled)
    summary = {
        "scheduledMinutes": scheduled_minutes,
        "unscheduledMinutes": unscheduled_minutes,
        "tasksScheduled": len({b.task_id for b in blocks}),
        "tasksUnscheduled": len(unscheduled),
        "capacityMinutes": check.capacity["usableMinutes"],
        "gapMinutes": check.gap_minutes,
    }
    output = config.planning.output_dir
    files = {
        "planJson": str(output / "plan.json"),
        "planIcs": str(output / "plan.ics"),
        "planMarkdown": str(output / "plan.md"),
        "reportHtml": str(output / "report.html"),
    }
    return PlanData(check=check, blocks=blocks, unscheduled=unscheduled, summary=summary, findings=findings, files=files)
