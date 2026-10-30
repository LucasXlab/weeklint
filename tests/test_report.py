from __future__ import annotations

import json
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar

from weeklint import report
from weeklint.budget import build_check, parse_week_arg
from weeklint.errors import WeeklintError
from weeklint.ics import blocks_to_ics, load_events
from weeklint.planner import plan_week
from weeklint.report import fmt_minutes, render_plan_markdown, render_report_html, write_plan_files
from weeklint.tasks import parse_task_text
from weeklint.timeutil import local_datetime, parse_iso_datetime

from conftest import TZ, write_ics

TZINFO = ZoneInfo(TZ)


def make_plan(workspace, make_config, title="<script>alert(1)</script>", task_title="论文 <b>x</b>"):
    write_ics(workspace / "calendar.ics", [])
    config = make_config(report={"title": title})
    wr = parse_week_arg("2026-W45", config.tz)
    evs, findings = load_events(config, local_datetime(wr.start, time(0, 0), config.tz), local_datetime(wr.end, time(0, 0), config.tz))
    tasks = parse_task_text(f"- [ ] {task_title} @estimate(90m) @priority(high)\n", config.tz, 60)
    check = build_check(config, tasks, evs, parse_iso_datetime("2026-11-02T09:00:00-05:00", config.tz), wr, findings)
    return config, check, plan_week(config, check)


def test_fmt_minutes():
    assert fmt_minutes(0) == "0m"
    assert fmt_minutes(30) == "30m"
    assert fmt_minutes(60) == "1h"
    assert fmt_minutes(90) == "1h30m"
    assert fmt_minutes(150) == "2h30m"


def test_markdown(workspace, make_config):
    config, check, plan = make_plan(workspace, make_config)
    text = render_plan_markdown(plan, config)
    assert "## 周一 11-02" in text
    assert "| 时间 | 任务 | 分钟 |" in text
    assert "## 未排程" in text
    assert "论文 <b>x</b>" in text


def test_html_standalone_and_tokens(workspace, make_config):
    config, check, plan = make_plan(workspace, make_config)
    html = render_report_html(plan, config)
    assert html.startswith("<!DOCTYPE html>")
    assert 'lang="zh-CN"' in html
    assert 'name="viewport"' in html
    assert "<script" not in html.lower()
    assert "http://" not in html and "https://" not in html
    assert "url(" not in html
    assert "@media (max-width: 639px)" in html
    assert "prefers-color-scheme: dark" in html
    for token in (
        "--bg", "--surface", "--surface-subtle", "--border", "--border-strong", "--text", "--text-muted",
        "--accent", "--accent-weak", "--danger", "--danger-weak", "--warning", "--warning-weak",
        "--ok", "--ok-weak", "--text-base", "--text-sm", "--text-xs", "--text-md", "--text-lg",
        "--text-metric", "--text-metric-sm", "--text-print", "--radius-sm", "--radius-md", "--radius-lg",
    ):
        assert token in html


def test_html_escapes_user_data(workspace, make_config):
    config, check, plan = make_plan(workspace, make_config)
    html = render_report_html(plan, config)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>x</b>" not in html


def test_plan_json_shape(workspace, make_config):
    config, check, plan = make_plan(workspace, make_config)
    from weeklint.report import _plan_json

    payload = _plan_json(plan, True)
    assert payload["version"] == "0.1.0"
    assert payload["week"]["iso"] == "2026-W45"
    assert len(payload["days"]) == 7
    assert payload["blocks"][0]["taskId"].startswith("t-")
    assert set(payload["summary"]) == {
        "scheduledMinutes", "unscheduledMinutes", "tasksScheduled", "tasksUnscheduled",
        "capacityMinutes", "gapMinutes",
    }
    assert payload["files"]["reportHtml"].endswith("report.html")
    assert _plan_json(plan, False)["files"]["reportHtml"] is None


def test_write_files_and_ics(workspace, make_config):
    config, check, plan = make_plan(workspace, make_config)
    files = write_plan_files(plan, config)
    assert Path(files["planJson"]).exists()
    assert Path(files["planIcs"]).exists()
    assert Path(files["reportHtml"]).exists()
    data = json.loads(Path(files["planJson"]).read_text(encoding="utf-8"))
    assert data["files"]["reportHtml"] == files["reportHtml"]
    cal = Calendar.from_ical(Path(files["planIcs"]).read_bytes())
    events = list(cal.walk("VEVENT"))
    assert len(events) == 1
    assert str(events[0].get("SUMMARY")) == "[Weeklint] 论文 <b>x</b>"
    assert events[0].get("DTSTART").to_ical().decode().endswith("Z")


def test_ics_escaping(workspace, make_config):
    config, check, plan = make_plan(workspace, make_config, task_title="论文, 第二部分; 修订")
    text = blocks_to_ics(plan.blocks, config.tz, check.generated_at, "0.1.0")
    cal = Calendar.from_ical(text)
    ev = list(cal.walk("VEVENT"))[0]
    assert str(ev.get("SUMMARY")) == "[Weeklint] 论文, 第二部分; 修订"


def test_write_failure_cleans_temp(workspace, make_config, monkeypatch):
    config, check, plan = make_plan(workspace, make_config)

    def boom(*args, **kwargs):
        raise OSError("no replace")

    monkeypatch.setattr(report.os, "replace", boom)
    with pytest.raises(WeeklintError) as exc:
        write_plan_files(plan, config)
    assert exc.value.code == "write_failed"
    left = list(config.planning.output_dir.glob("*.tmp"))
    assert left == []


def test_write_failure_keeps_old_plan(workspace, make_config, monkeypatch):
    config, check, plan = make_plan(workspace, make_config)
    write_plan_files(plan, config)
    old = (config.planning.output_dir / "plan.json").read_bytes()

    def boom(*args, **kwargs):
        raise OSError("no replace")

    monkeypatch.setattr(report.os, "replace", boom)
    with pytest.raises(WeeklintError):
        write_plan_files(plan, config)
    assert (config.planning.output_dir / "plan.json").read_bytes() == old


def test_empty_report_does_not_claim_it_fits(workspace, make_config):
    write_ics(workspace / "calendar.ics", [])
    config = make_config()
    wr = parse_week_arg("2026-W45", config.tz)
    evs, findings = load_events(config, local_datetime(wr.start, time(0, 0), config.tz), local_datetime(wr.end, time(0, 0), config.tz))
    check = build_check(config, [], evs, parse_iso_datetime("2026-11-02T09:00:00-05:00", config.tz), wr, findings)
    html = render_report_html(plan_week(config, check), config)
    assert "还没有任务" in html
    assert "这周装得下" not in html


def test_report_bar_shows_demand_when_nothing_is_scheduled(workspace, make_config):
    write_ics(workspace / "calendar.ics", [])
    config = make_config(
        work_hours={"mon": ["09:00-10:00"], "tue": [], "wed": [], "thu": [], "fri": [], "sat": [], "sun": []},
        max_deep_work_minutes_per_day=0,
        max_tasks_per_day=12,
    )
    wr = parse_week_arg("2026-W45", config.tz)
    evs, findings = load_events(config, local_datetime(wr.start, time(0, 0), config.tz), local_datetime(wr.end, time(0, 0), config.tz))
    tasks = parse_task_text("- [ ] 大任务 @estimate(600m)\n", config.tz, 60)
    check = build_check(config, tasks, evs, parse_iso_datetime("2026-11-02T09:00:00-05:00", config.tz), wr, findings)
    plan = plan_week(config, check)
    html = render_report_html(plan, config)
    assert plan.summary["scheduledMinutes"] == 0
    assert 'width: 100.0%' in html
    assert "需求 10h" in html


def test_print_uses_light_tokens(workspace, make_config):
    config, check, plan = make_plan(workspace, make_config)
    html = render_report_html(plan, config)
    print_block = html.split("@media print", 1)[1]
    assert "color-scheme: light" in print_block
    assert "--bg: #fbfbfa" in print_block
