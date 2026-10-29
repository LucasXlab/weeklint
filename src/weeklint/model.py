"""Small immutable data objects shared by the parser, budget and planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

PRIORITIES = ("high", "normal", "low")
PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}
SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def iso(dt: datetime) -> str:
    """ISO 8601 with the offset, seconds always present."""
    return dt.isoformat(timespec="seconds")


def hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def minutes_between(start: datetime, end: datetime) -> int:
    return int(round((end - start).total_seconds() / 60))


@dataclass(slots=True)
class Task:
    id: str
    title: str
    estimate_minutes: int
    due: datetime | None
    priority: str
    tags: list[str]
    line: int
    completed: bool
    estimated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "estimateMinutes": self.estimate_minutes,
            "due": iso(self.due) if self.due else None,
            "priority": self.priority,
            "tags": list(self.tags),
            "line": self.line,
            "completed": self.completed,
            "estimated": self.estimated,
        }


@dataclass(slots=True)
class CalendarEvent:
    uid: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool
    source_file: str

    @property
    def minutes(self) -> int:
        return minutes_between(self.start, self.end)


@dataclass(slots=True, frozen=True)
class FreeSlot:
    date: date
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return minutes_between(self.start, self.end)


@dataclass(slots=True)
class Block:
    task_id: str
    title: str
    start: datetime
    end: datetime
    locked: bool
    reason: str
    priority: str = "normal"

    @property
    def minutes(self) -> int:
        return minutes_between(self.start, self.end)

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "title": self.title,
            "start": iso(self.start),
            "end": iso(self.end),
            "minutes": self.minutes,
            "locked": self.locked,
            "reason": self.reason,
        }


@dataclass(slots=True)
class Finding:
    code: str
    severity: str
    message: str
    task_id: str | None = None
    day: str | None = None
    value: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "taskId": self.task_id,
            "day": self.day,
            "value": self.value,
        }

    def sort_key(self) -> tuple[int, str, str, str]:
        return (
            SEVERITY_RANK.get(self.severity, 9),
            self.code,
            self.task_id or "",
            self.day or "",
        )


@dataclass(slots=True)
class WeekRange:
    iso: str
    start: date
    end: date
    timezone: str

    def to_dict(self) -> dict[str, str]:
        return {
            "iso": self.iso,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "timezone": self.timezone,
        }


@dataclass(slots=True)
class CheckData:
    """Everything computed before scheduling."""

    week: WeekRange
    now: datetime
    generated_at: datetime
    tasks: list[Task]
    all_tasks: list[Task]
    open_tasks: list[Task]
    completed_count: int
    events: list[CalendarEvent]
    slots: list[FreeSlot]
    day_slots: dict[date, list[FreeSlot]]
    day_work_minutes: dict[date, int]
    day_capacity: dict[date, dict[str, int]]
    capacity: dict[str, int]
    demand: dict[str, int]
    gap_minutes: int
    overcommitted: bool
    findings: list[Finding]
    warnings_seen: set[str] = field(default_factory=set)
    out_of_scope: list[Task] = field(default_factory=list)

    def capacity_dict(self) -> dict[str, int]:
        return dict(self.capacity)

    def demand_dict(self) -> dict[str, int]:
        return dict(self.demand)


@dataclass(slots=True)
class PlanData:
    check: CheckData
    blocks: list[Block]
    unscheduled: list[tuple[Task, int, str]]
    summary: dict[str, int]
    findings: list[Finding]
    files: dict[str, str | None]

    def blocks_sorted(self) -> list[Block]:
        return sorted(self.blocks, key=lambda b: (b.start, b.task_id))
