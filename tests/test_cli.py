from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest
import yaml

from weeklint.cli import main
from weeklint.config import load_config

from conftest import config_data, local, write_ics

NOW = "2026-11-02T09:00:00-05:00"


def run(args, capsys, monkeypatch=None, cwd=None):
    if cwd and monkeypatch:
        monkeypatch.chdir(cwd)
    code = main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


def init(tmp_path, capsys):
    code, out, err = run(["init", "--dir", str(tmp_path)], capsys)
    assert code == 0, err
    return tmp_path / "weeklint.yaml"


def test_init(tmp_path, capsys):
    code, out, err = run(["init", "--dir", str(tmp_path)], capsys)
    assert code == 0
    for name in ("weeklint.yaml", "tasks.md", "calendar.ics"):
        assert (tmp_path / name).exists()
    config = load_config(tmp_path / "weeklint.yaml")
    assert config.version == 1


def test_init_json(tmp_path, capsys):
    code, out, _ = run(["init", "--dir", str(tmp_path), "--json"], capsys)
    assert code == 0
    data = json.loads(out)
    assert data["created"] == ["weeklint.yaml", "tasks.md", "calendar.ics"]


def test_init_existing(tmp_path, capsys):
    init(tmp_path, capsys)
    code, out, err = run(["init", "--dir", str(tmp_path), "--json"], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "already_initialized"


def test_config_missing(tmp_path, capsys):
    code, out, err = run(["--config", str(tmp_path / "nope.yaml"), "--json", "check"], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "config_not_found"


def test_check_json(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m) @priority(high)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "check", "--now", NOW], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["week"]["iso"] == "2026-W45"
    assert data["capacity"]["usableMinutes"] > 0
    assert data["tasks"][0]["title"] == "论文"
    assert data["tasks"][0]["atRisk"] is False
    assert data["tasks"][0]["scheduledMinutes"] == 0
    assert data["generatedAt"] == "2026-11-02T09:00:00-05:00"


def test_check_overcommitted_exit_1(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 大任务 @estimate(2400m) @due(2026-11-05)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "check", "--now", NOW], capsys)
    assert code == 1
    data = json.loads(out)
    assert data["overcommitted"] is True
    assert any(f["code"] == "overcommitted" for f in data["findings"])


def test_check_human_has_no_ansi(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    code, out, _ = run(["--config", str(workspace / "weeklint.yaml"), "--no-color", "check", "--now", NOW], capsys)
    assert code == 0
    assert "\x1b[" not in out
    assert "2026-W45" in out


def test_plan_writes_files(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m) @priority(high)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "plan", "--now", NOW], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["summary"]["scheduledMinutes"] == 90
    for key in ("planJson", "planIcs", "planMarkdown", "reportHtml"):
        assert Path(data["files"][key]).exists()
    assert (workspace / ".weeklint" / "plan.prev.json").exists() is False
    assert not (workspace / ".weeklint" / ".lock").exists()


def test_plan_json_matches_file(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "plan", "--now", NOW], capsys)
    assert code == 0, err
    payload = json.loads(out)
    on_disk = json.loads((workspace / ".weeklint" / "plan.json").read_text(encoding="utf-8"))
    assert payload == on_disk


def test_plan_no_report(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "plan", "--no-report", "--now", NOW], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["files"]["reportHtml"] is None
    assert not (workspace / ".weeklint" / "report.html").exists()


def test_plan_error_exit_1(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 大任务 @estimate(2400m) @due(2026-11-05)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "plan", "--now", NOW], capsys)
    assert code == 1
    data = json.loads(out)
    assert any(f["severity"] == "error" for f in data["findings"])


def test_plan_lock(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    (workspace / ".weeklint").mkdir()
    (workspace / ".weeklint" / ".lock").write_text("pid=1\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "plan", "--now", NOW], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "plan_locked"


def test_inputs_untouched(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    before = hashlib.sha256((workspace / "tasks.md").read_bytes()).hexdigest()
    before_ics = hashlib.sha256((workspace / "calendar.ics").read_bytes()).hexdigest()
    run(["--config", str(workspace / "weeklint.yaml"), "plan", "--now", NOW], capsys)
    assert hashlib.sha256((workspace / "tasks.md").read_bytes()).hexdigest() == before
    assert hashlib.sha256((workspace / "calendar.ics").read_bytes()).hexdigest() == before_ics


def test_plan_second_run_creates_prev(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    run(["--config", str(workspace / "weeklint.yaml"), "plan", "--now", NOW], capsys)
    run(["--config", str(workspace / "weeklint.yaml"), "plan", "--now", "2026-11-02T12:00:00-05:00"], capsys)
    assert (workspace / ".weeklint" / "plan.prev.json").exists()


def test_today(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    run(["--config", str(workspace / "weeklint.yaml"), "plan", "--now", NOW], capsys)
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "today", "--now", "2026-11-02T08:00:00-05:00"], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["planFound"] is True
    assert data["date"] == "2026-11-02"
    assert set(data) == {"version", "date", "now", "planFound", "blocks", "next", "dueTodayUnscheduled"}
    assert data["blocks"]
    assert data["next"] is not None
    assert data["dueTodayUnscheduled"] == []


def test_today_no_plan(workspace, capsys):
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "today", "--now", "2026-11-02T08:00:00-05:00"], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["planFound"] is False


def test_today_rejects_week(workspace, capsys):
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "today", "--week", "2026-W45"], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "invalid_argument"


def test_explain_by_id_and_title(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 写论文 @estimate(90m) @id(paper)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "explain", "paper", "--now", NOW], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["task"]["id"] == "paper"
    assert set(data) == {"version", "task", "blocks", "unscheduled", "reason"}
    assert data["unscheduled"] is None
    assert "截止" in data["reason"] and "优先级" in data["reason"]
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "explain", "论文", "--now", NOW], capsys)
    assert code == 0, err


def test_explain_not_found_and_ambiguous(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文一 @estimate(30m)\n- [ ] 论文二 @estimate(30m)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "explain", "论文", "--now", NOW], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "ambiguous_task"
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "explain", "没有", "--now", NOW], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "task_not_found"


def test_doctor(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "doctor", "--now", NOW], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["counts"]["tasks"] == 1
    assert data["counts"]["usableMinutes"] > 0
    assert data["configPath"].endswith("weeklint.yaml")
    assert set(data["counts"]) == {"tasks", "openTasks", "completedTasks", "unestimatedTasks", "events", "workMinutes", "freeMinutes", "usableMinutes"}
    assert set(data) == {"version", "configPath", "taskFile", "calendarFiles", "counts", "findings"}


def test_version_and_help(workspace, capsys):
    code, out, _ = run(["--version"], capsys)
    assert code == 0
    assert "weeklint 0.1.0" in out
    code, out, _ = run(["version", "--json"], capsys)
    assert code == 0
    assert json.loads(out) == {"version": "0.1.0"}
    code, out, _ = run(["--help"], capsys)
    assert code == 0
    assert "check" in out


def test_invalid_week(workspace, capsys):
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "check", "--week", "2027-W53", "--now", NOW], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "invalid_week"


def test_invalid_now(workspace, capsys):
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "check", "--now", "not-a-time"], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "invalid_now"


def test_argparse_error_is_json(workspace, capsys):
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "nope"], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "invalid_argument"


def test_no_network(workspace, monkeypatch, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")

    def no_socket(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", no_socket)
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "check", "--now", NOW], capsys)
    assert code == 0, err


def test_env_config_and_now(workspace, monkeypatch, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    monkeypatch.setenv("WEEKLINT_CONFIG", str(workspace / "weeklint.yaml"))
    monkeypatch.setenv("WEEKLINT_NOW", NOW)
    code, out, err = run(["check", "--json"], capsys)
    assert code == 0, err
    assert json.loads(out)["week"]["iso"] == "2026-W45"


def test_invalid_env_values(workspace, monkeypatch, capsys):
    for name, value in (("WEEKLINT_NO_COLOR", "yes"), ("WEEKLINT_DEBUG", "2"), ("WEEKLINT_NOW", "not-a-time")):
        monkeypatch.setenv(name, value)
        code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "check"], capsys)
        assert code == 2, (name, err)
        assert json.loads(err)["code"] == "invalid_env"
        monkeypatch.delenv(name, raising=False)


def test_version_rejects_week(workspace, capsys):
    code, out, err = run(["--json", "version", "--week", "2026-W45"], capsys)
    assert code == 2
    assert json.loads(err)["code"] == "invalid_argument"


def test_today_due_unscheduled(workspace, capsys):
    (workspace / "weeklint.yaml").write_text(
        yaml.safe_dump(
            config_data(
                max_tasks_per_day=1,
                work_hours={
                    "mon": ["09:00-12:00"],
                    "tue": [],
                    "wed": [],
                    "thu": [],
                    "fri": [],
                    "sat": [],
                    "sun": [],
                },
            ),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (workspace / "tasks.md").write_text(
        "- [ ] 今天一 @due(2026-11-02T17:00) @estimate(120m) @priority(high)\n"
        "- [ ] 今天二 @due(2026-11-02T18:00) @estimate(120m) @priority(high)\n"
        "- [ ] 今天三 @due(2026-11-02T19:00) @estimate(120m) @priority(high)\n",
        encoding="utf-8",
    )
    code, _, _ = run(["--config", str(workspace / "weeklint.yaml"), "--json", "plan", "--now", "2026-11-02T08:00:00-05:00"], capsys)
    assert code == 1
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "today", "--now", "2026-11-02T08:00:00-05:00"], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert len(data["dueTodayUnscheduled"]) == 2
    assert all(item["due"].startswith("2026-11-02") for item in data["dueTodayUnscheduled"])


def test_date_only_now(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(90m)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "check", "--now", "2026-11-02"], capsys)
    assert code == 0, err
    assert json.loads(out)["now"] == "2026-11-02T00:00:00-05:00"


def test_explain_completed(workspace, capsys):
    (workspace / "tasks.md").write_text("- [x] 已完成的任务 @estimate(30m)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--json", "explain", "已完成", "--now", NOW], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["blocks"] == []
    assert data["unscheduled"] is None
    assert "已完成" in data["reason"]


def test_today_next_when_block_in_progress(workspace, capsys):
    """next must skip the block that is running now, and work at block edges."""
    (workspace / "tasks.md").write_text(
        "- [ ] 甲 @estimate(60m) @id(a) @priority(high)\n- [ ] 乙 @estimate(60m) @id(b)\n",
        encoding="utf-8",
    )
    cfg = str(workspace / "weeklint.yaml")
    code, _, err = run(["--config", cfg, "--json", "plan", "--now", "2026-11-02T08:00:00-05:00"], capsys)
    assert code == 0, err

    # 09:15: inside 甲 (09:00–10:00); next must be 乙 at 10:10.
    code, out, err = run(["--config", cfg, "--json", "today", "--now", "2026-11-02T09:15:00-05:00"], capsys)
    assert code == 0, err
    data = json.loads(out)
    assert [(b["start"][11:16], b["title"]) for b in data["blocks"]] == [("09:00", "甲"), ("10:10", "乙")]
    assert data["next"]["title"] == "乙"
    assert data["next"]["start"][11:16] == "10:10"

    # 10:00: exactly at the end of 甲, which is half-open, so next is still 乙.
    code, out, err = run(["--config", cfg, "--json", "today", "--now", "2026-11-02T10:00:00-05:00"], capsys)
    assert code == 0, err
    assert json.loads(out)["next"]["title"] == "乙"

    # 10:30: inside 乙, so there is no next block left today.
    code, out, err = run(["--config", cfg, "--json", "today", "--now", "2026-11-02T10:30:00-05:00"], capsys)
    assert code == 0, err
    assert json.loads(out)["next"] is None

    # Human output names the next block time and the running block.
    code, out, _ = run(["--config", cfg, "--no-color", "today", "--now", "2026-11-02T09:15:00-05:00"], capsys)
    assert code == 0
    assert "09:00–10:00  甲" in out
    assert "（进行中）" in out
    assert "下一块：10:10 乙" in out


def test_debug_env_prints_traceback(workspace, monkeypatch, capsys):
    """WEEKLINT_DEBUG=1 adds a traceback for internal errors; default does not."""
    import weeklint.cli as cli

    def boom(*args, **kwargs):
        raise RuntimeError("boom for test")

    monkeypatch.setattr(cli, "_check_for", boom)
    args = ["--config", str(workspace / "weeklint.yaml"), "--json", "check"]

    monkeypatch.delenv("WEEKLINT_DEBUG", raising=False)
    code, out, err = run(args, capsys)
    assert code == 3
    assert "Traceback (most recent call last)" not in err
    assert json.loads(err.strip().splitlines()[-1])["code"] == "internal_error"
    assert "boom for test" in json.loads(err.strip().splitlines()[-1])["error"]

    monkeypatch.setenv("WEEKLINT_DEBUG", "1")
    code, out, err = run(args, capsys)
    assert code == 3
    assert "Traceback (most recent call last)" in err
    assert "RuntimeError: boom for test" in err
    assert json.loads(err.strip().splitlines()[-1])["code"] == "internal_error"


def test_help_lists_global_options(capsys):
    code, out, err = run(["--help"], capsys)
    assert code == 0
    assert "--config" in out and "--json" in out and "--now" in out and "--week" in out
    code, out, err = run(["check", "--help"], capsys)
    assert code == 0
    assert "--config" in out


def test_human_output_escapes_rich_markup(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] [/] 坏标题 @estimate(30m)\n", encoding="utf-8")
    code, out, err = run(["--config", str(workspace / "weeklint.yaml"), "--no-color", "check", "--now", NOW], capsys)
    assert code == 0, err
    assert "[/]" in out


def test_output_dir_cannot_overwrite_input(workspace, capsys):
    (workspace / "tasks.md").write_text("- [ ] 论文 @estimate(30m)\n", encoding="utf-8")
    (workspace / "plan.json").write_text("keep me\n", encoding="utf-8")
    config = workspace / "weeklint.yaml"
    data = yaml.safe_load(config.read_text())
    data["planning"]["task_file"] = "plan.json"
    data["planning"]["output_dir"] = "."
    config.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    code, out, err = run(["--config", str(config), "--json", "plan", "--now", NOW], capsys)
    assert code == 2
    assert json.loads(err.strip().splitlines()[-1])["code"] == "config_invalid_path"
    assert (workspace / "plan.json").read_text() == "keep me\n"
