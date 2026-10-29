from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
import pytest
from icalendar import Calendar, Event

from weeklint.config import load_config

NOW = "2026-11-02T09:00:00-05:00"
TZ = "America/New_York"


def config_data(**planning):
    data = {
        "version": 1,
        "timezone": TZ,
        "planning": {
            "include_weekends": False,
            "work_hours": {
                "mon": ["09:00-12:00", "13:30-18:00"],
                "tue": ["09:00-12:00", "13:30-18:00"],
                "wed": ["09:00-12:00", "13:30-18:00"],
                "thu": ["09:00-12:00", "13:30-18:00"],
                "fri": ["09:00-12:00", "13:30-18:00"],
                "sat": [],
                "sun": [],
            },
            "buffer_after_event_minutes": 10,
            "gap_between_tasks_minutes": 10,
            "min_block_minutes": 30,
            "max_block_minutes": 120,
            "max_deep_work_minutes_per_day": 180,
            "max_tasks_per_day": 4,
            "default_estimate_minutes": 60,
            "lock_existing_plan": True,
            "block_all_day_events": True,
            "task_file": "tasks.md",
            "calendar_files": ["calendar.ics"],
            "output_dir": ".weeklint",
        },
    }
    data["planning"].update(planning)
    return data


@pytest.fixture
def workspace(tmp_path: Path):
    (tmp_path / "tasks.md").write_text("# tasks\n", encoding="utf-8")
    (tmp_path / "calendar.ics").write_text(
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Test//Test//EN\nEND:VCALENDAR\n", encoding="utf-8"
    )
    (tmp_path / "weeklint.yaml").write_text(yaml.safe_dump(config_data(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tmp_path


@pytest.fixture
def make_config(workspace: Path):
    def _make(**planning):
        if planning:
            (workspace / "weeklint.yaml").write_text(
                yaml.safe_dump(config_data(**planning), allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
        return load_config(workspace / "weeklint.yaml")
    return _make


def write_ics(path: Path, events: list[dict]) -> None:
    cal = Calendar()
    cal.add("prodid", "-//Test//Test//EN")
    cal.add("version", "2.0")
    tz = ZoneInfo(TZ)
    for item in events:
        ev = Event()
        ev.add("uid", item.get("uid", item["summary"] + "@test"))
        ev.add("summary", item["summary"])
        start = item["start"]
        if isinstance(start, datetime):
            ev.add("dtstart", start if start.tzinfo else start.replace(tzinfo=tz))
        else:
            ev.add("dtstart", start)
        if "end" in item:
            end = item["end"]
            ev.add("dtend", end if not isinstance(end, datetime) or end.tzinfo else end.replace(tzinfo=tz))
        if "duration" in item:
            ev.add("duration", item["duration"])
        if "rrule" in item:
            ev.add("rrule", item["rrule"])
        if "exdate" in item:
            ev.add("exdate", item["exdate"])
        if "status" in item:
            ev.add("status", item["status"])
        if "transp" in item:
            ev.add("transp", item["transp"])
        cal.add_component(ev)
    path.write_bytes(cal.to_ical())


def local(*args):
    return datetime(*args, tzinfo=ZoneInfo(TZ))
