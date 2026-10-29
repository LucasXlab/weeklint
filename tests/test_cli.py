from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

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
    run(["--config", str(workspace / "weeklint.yaml"), "plan", "--now", NOW], capsys)
    assert hashlib.sha256((workspace / "tasks.md").read_bytes()).hexdigest() == before


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
