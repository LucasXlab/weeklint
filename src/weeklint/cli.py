"""Command line interface.

All user-facing errors go through the same envelope. ``--json`` makes stdout a
single JSON object; human output uses rich, but degrades to plain text when not
a TTY or when ``--no-color``/``WEEKLINT_NO_COLOR`` is set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import date, datetime, time, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import __version__
from .budget import build_check, parse_week_arg, resolve_now, week_for_now
from .config import Config, dump_init_config, load_config
from .errors import WeeklintError
from .ics import load_events
from .model import CheckData, Finding, PlanData, Task, iso
from .timeutil import local_datetime
from .planner import plan_week
from .report import acquire_lock, fmt_minutes, release_lock, write_plan_files
from .tasks import load_tasks

TASKS_TEMPLATE = """# Weeklint 任务
# 每行一个任务：- [ ] 标题 @due(2026-11-04T17:00) @estimate(90m) @priority(high) @tag(course)
# 元数据可省略；省略 estimate 时使用配置里的 default_estimate_minutes。
"""
CALENDAR_TEMPLATE = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Weeklint//Weeklint {__version__}//ZH
CALSCALE:GREGORIAN
END:VCALENDAR
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise WeeklintError("invalid_argument", f"参数错误：{message}", {"usage": self.format_usage().strip()})


def _system_timezone() -> str:
    try:
        name = os.environ.get("TZ")
        if name:
            return name
        link = Path("/etc/localtime")
        if link.exists():
            resolved = link.resolve()
            parts = resolved.parts
            if "zoneinfo" in parts:
                return "/".join(parts[parts.index("zoneinfo") + 1 :])
    except OSError:
        pass
    return "UTC"


def _init_config_text() -> str:
    # Keep the documented example readable and deterministic, but use the
    # machine's zone when it can be discovered.
    text = dump_init_config()
    import re

    return re.sub(r"^timezone: .*$", f"timezone: {_system_timezone()}", text, count=1, flags=re.MULTILINE)


def _write_new(path: Path, data: str) -> None:
    fd = -1
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.write(fd, data.encode("utf-8"))
        os.close(fd)
        fd = -1
    except FileExistsError:
        raise WeeklintError("already_initialized", f"文件已存在：{path}。不覆盖已有文件。", {"path": str(path)}) from None
    except OSError as exc:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        raise WeeklintError("init_failed", f"创建文件失败：{path}（{exc.strerror or exc}）。", {"path": str(path)}) from None


def cmd_init(args, opts) -> int:
    target = Path(args.dir or ".").expanduser().resolve()
    files = [("weeklint.yaml", _init_config_text()), ("tasks.md", TASKS_TEMPLATE), ("calendar.ics", CALENDAR_TEMPLATE)]
    existing = [str(target / name) for name, _ in files if (target / name).exists()]
    if existing:
        raise WeeklintError(
            "already_initialized",
            f"已经初始化过：{existing[0]} 已存在。不会覆盖已有文件。",
            {"path": existing[0]},
        )
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WeeklintError("init_failed", f"无法创建目录：{target}（{exc.strerror}）。", {"path": str(target)}) from None
    created: list[str] = []
    try:
        for name, data in files:
            _write_new(target / name, data)
            created.append(name)
    except WeeklintError:
        for name in created:
            try:
                (target / name).unlink()
            except OSError:
                pass
        raise
    if opts["json"]:
        _emit_json({"version": __version__, "created": created, "dir": str(target)})
    else:
        _console(opts).print(f"已创建 weeklint.yaml、tasks.md、calendar.ics。下一步：导出日历到 calendar.ics，再运行 weeklint check。")
        _console(opts).print(f"目录：{target}")
    return 0


def _check_for(config: Config, now: datetime, week_arg: str | None) -> CheckData:
    week = parse_week_arg(week_arg, config.tz) if week_arg else week_for_now(now, config.tz)
    tasks = load_tasks(config.planning.task_file, config.tz, config.planning.default_estimate_minutes)
    horizon_start = local_datetime(week.start, time(0, 0), config.tz)
    horizon_end = local_datetime(week.end, time(0, 0), config.tz)
    events, event_findings = load_events(config, horizon_start, horizon_end)
    return build_check(config, tasks, events, now, week, event_findings)


def _task_status(task: Task, check: CheckData, planned_ids: set[str] | None, unscheduled_ids: set[str] | None) -> str:
    if planned_ids is not None and task.id in unscheduled_ids:
        return "未排"
    if planned_ids is not None and task.id in planned_ids:
        return "已排"
    if task.due is not None and task.due < check.now:
        return "过期"
    return "待排"


def _check_json(check: CheckData, config: Config) -> dict:
    task_rows = []
    for task in check.tasks:
        at_risk = check.overcommitted and task.due is not None and task.due <= local_datetime(check.week.end, time(0, 0), config.tz)
        row = task.to_dict()
        row["scheduledMinutes"] = 0
        row["atRisk"] = at_risk
        task_rows.append(row)
    return {
        "version": __version__,
        "week": check.week.to_dict(),
        "generatedAt": iso(check.generated_at),
        "now": iso(check.now),
        "days": [
            {"date": d.isoformat(), **check.day_capacity[d]}
            for d in sorted(check.day_capacity)
        ],
        "capacity": dict(check.capacity),
        "demand": dict(check.demand),
        "gapMinutes": check.gap_minutes,
        "overcommitted": check.overcommitted,
        "tasks": task_rows,
        "findings": [f.to_dict() for f in check.findings],
    }


def _print_findings(check, opts) -> None:
    c = _console(opts)
    if not check.findings:
        c.print("没有问题。")
        return
    for severity in ("error", "warning", "info"):
        for finding in check.findings:
            if finding.severity == severity:
                c.print(f"[{severity}] {finding.message}")


def cmd_check(args, opts) -> int:
    config = _load_config(opts)
    now = resolve_now(opts["now"], os.environ, config.tz)
    check = _check_for(config, now, opts["week"])
    if opts["json"]:
        _emit_json(_check_json(check, config))
    else:
        c = _console(opts)
        c.print(f"{check.week.iso} · {check.week.start.isoformat()} 至 {(check.week.end - timedelta(days=1)).isoformat()}")
        c.print(
            f"可支配 {fmt_minutes(check.capacity['usableMinutes'])} · 任务需要 {fmt_minutes(check.demand['estimatedMinutes'])} · 缺口 {fmt_minutes(check.gap_minutes)}"
        )
        _print_findings(check, opts)
        table = Table(show_header=True, header_style="bold")
        for col in ("id", "标题", "估算", "截止", "优先级", "状态", "风险"):
            table.add_column(col)
        week_end = local_datetime(check.week.end, time(0, 0), config.tz)
        for task in check.tasks:
            at_risk = check.overcommitted and task.due is not None and task.due <= week_end
            table.add_row(
                task.id,
                task.title,
                fmt_minutes(task.estimate_minutes),
                iso(task.due) if task.due else "—",
                task.priority,
                _task_status(task, check, None, None),
                "是" if at_risk else "—",
            )
        c.print(table)
    return 1 if any(f.severity == "error" for f in check.findings) else 0


def _summary_block(check: CheckData) -> str:
    return (
        f"可支配 {fmt_minutes(check.capacity['usableMinutes'])} · "
        f"任务需要 {fmt_minutes(check.demand['estimatedMinutes'])} · 缺口 {fmt_minutes(check.gap_minutes)}"
    )


def cmd_plan(args, opts) -> int:
    config = _load_config(opts)
    now = resolve_now(opts["now"], os.environ, config.tz)
    check = _check_for(config, now, opts["week"])
    lock, stale = acquire_lock(config.planning.output_dir)
    try:
        plan = plan_week(config, check)
        if stale:
            plan.findings.append(Finding("stale_lock_removed", "warning", "发现超过 10 分钟的旧锁文件，已删除并继续。"))
            plan.findings.sort(key=lambda f: f.sort_key())
        files = write_plan_files(plan, config, include_report=not args.no_report)
    finally:
        release_lock(lock)
    if opts["json"]:
        payload = _plan_json(plan, include_report=not args.no_report)
        payload["files"] = files
        _emit_json(payload)
    else:
        c = _console(opts)
        c.print(f"{check.week.iso} · {check.week.start.isoformat()} 至 {(check.week.end - timedelta(days=1)).isoformat()}")
        c.print(_summary_block(check))
        c.print(f"已排 {fmt_minutes(plan.summary['scheduledMinutes'])} · 未排 {plan.summary['tasksUnscheduled']} 个任务")
        for name in ("planJson", "planIcs", "planMarkdown", "reportHtml"):
            if files.get(name):
                c.print(f"{name}: {files[name]}")
        _print_findings(plan, opts)
    return 1 if any(f.severity == "error" for f in plan.findings) else 0


def _plan_json(plan: PlanData, include_report: bool) -> dict:
    from .report import _plan_json as build

    return build(plan, include_report)


def _read_plan(config: Config) -> dict | None:
    path = config.planning.output_dir / "plan.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _today_plan(config: Config, now: datetime) -> tuple[dict, bool]:
    current = week_for_now(now, config.tz)
    raw = _read_plan(config)
    if raw and isinstance(raw.get("week"), dict) and raw["week"].get("iso") == current.iso:
        return raw, True
    check = _check_for(config, now, None)
    plan = plan_week(config, check)
    from .report import _plan_json as build

    return build(plan, False), False


def cmd_today(args, opts) -> int:
    if opts["week"]:
        raise WeeklintError("invalid_argument", "today 不接受 --week；它只看今天。", {"option": "--week"})
    config = _load_config(opts)
    now = resolve_now(opts["now"], os.environ, config.tz)
    data, found = _today_plan(config, now)
    today = now.date()
    blocks = [b for b in data.get("blocks", []) if isinstance(b, dict) and str(b.get("start", "")).startswith(today.isoformat())]
    blocks.sort(key=lambda b: b.get("start", ""))
    upcoming = None
    for block in data.get("blocks", []):
        if isinstance(block, dict) and block.get("start", "") > iso(now):
            upcoming = block
            break
    task_map = {t.id: t for t in load_tasks(config.planning.task_file, config.tz, config.planning.default_estimate_minutes)}
    due_unscheduled = []
    for item in data.get("unscheduled", []):
        if not isinstance(item, dict):
            continue
        task = task_map.get(item.get("taskId"))
        if task is not None and task.due is not None and task.due.date() == today:
            due_unscheduled.append({"title": task.title, "taskId": task.id, "due": iso(task.due)})
    if opts["json"]:
        _emit_json(
            {
                "version": __version__,
                "date": today.isoformat(),
                "now": iso(now),
                "planFound": found,
                "blocks": blocks,
                "next": upcoming,
                "dueTodayUnscheduled": due_unscheduled,
            }
        )
    else:
        c = _console(opts)
        c.print(f"今天 · {today.month}月{today.day}日 " + "周" + "一二三四五六日"[today.weekday()])
        if not blocks:
            c.print("今天没有安排。")
        else:
            for block in blocks:
                start = block.get("start", "")
                end = block.get("end", "")
                c.print(f"{start[11:16]}–{end[11:16]}  {block.get('title', '')}" + ("（已锁定）" if block.get("locked") else ""))
        if upcoming:
            c.print(f"下一块：{upcoming.get('start', '')[11:16]} {upcoming.get('title', '')}")
        if due_unscheduled:
            c.print("今天到期但未排程：")
            for item in due_unscheduled:
                c.print(f"  {item.get('title', '')}（截止 {item.get('due', '')}）")
        if not found:
            c.print("（plan.json 不是本周的，本次结果在内存中生成，未写文件。）")
    return 0


def _explain_reason(task: Task, block, reason: str) -> str:
    due = f"截止 {iso(task.due)}，" if task.due else "没有截止时间，"
    ordering = f"{due}优先级 {task.priority}"
    if reason == "scheduled" and block is not None:
        period = "上午" if block.start.hour < 12 else "下午"
        return f"{ordering}；放在{block.start.strftime('%m-%d')} {period} {block.start.strftime('%H:%M')} 的第一个足够长空档。"
    labels = {
        "no_capacity": "所有空档都不够长",
        "deep_work_limit": "高优先级每日深度工作上限已满",
        "task_limit": "每日任务数上限已满",
        "completed": "任务已完成",
    }
    return f"{ordering}；未排程：{labels.get(reason, reason)}。"

def cmd_explain(args, opts) -> int:
    config = _load_config(opts)
    now = resolve_now(opts["now"], os.environ, config.tz)
    tasks = load_tasks(config.planning.task_file, config.tz, config.planning.default_estimate_minutes)
    query = args.query.strip()
    exact = [t for t in tasks if t.id == query]
    matches = exact or [t for t in tasks if query.casefold() in t.title.casefold()]
    if not matches:
        raise WeeklintError("task_not_found", f"没有找到任务：{query!r}。可以用任务 id 或标题的一部分。", {"query": query})
    if len(matches) > 1 and not exact:
        raise WeeklintError(
            "ambiguous_task",
            f"有 {len(matches)} 个任务匹配 {query!r}，请写得更具体或直接用 id。",
            {"matches": [{"id": t.id, "title": t.title, "line": t.line} for t in matches[:10]]},
        )
    task = matches[0]
    check = _check_for(config, now, opts["week"])
    plan = plan_week(config, check)
    blocks = [b for b in plan.blocks_sorted() if b.task_id == task.id]
    if blocks:
        status = "scheduled"
        reason_text = blocks[0].reason
        unscheduled_obj = None
    elif any(t.id == task.id for t, _, _ in plan.unscheduled):
        status = "unscheduled"
        remaining, reason = next((r, why) for t, r, why in plan.unscheduled if t.id == task.id)
        reason_text = _explain_reason(task, None, reason)
        unscheduled_obj = {"remainingMinutes": remaining, "reason": reason}
    else:
        status = "completed" if task.completed else "not_in_scope"
        reason_text = "任务已完成，不参与本周排程。" if task.completed else "截止晚于本周，未计入本周排程。"
        unscheduled_obj = None
    payload = {
        "version": __version__,
        "task": task.to_dict(),
        "blocks": [b.to_dict() for b in blocks],
        "unscheduled": unscheduled_obj,
        "reason": reason_text,
    }
    if opts["json"]:
        _emit_json(payload)
    else:
        c = _console(opts)
        c.print(f"{task.title}")
        c.print(f"id={task.id} · 估算 {fmt_minutes(task.estimate_minutes)} · 截止 {iso(task.due) if task.due else '—'} · 优先级 {task.priority}")
        c.print(f"状态：{status} · {reason_text}")
        for block in blocks:
            c.print(f"  {block.start.strftime('%m-%d %H:%M')}–{block.end.strftime('%H:%M')}  已锁定={block.locked}")
    return 0


def cmd_doctor(args, opts) -> int:
    if opts["week"]:
        raise WeeklintError("invalid_argument", "doctor 不接受 --week；它只检查本周。", {"option": "--week"})
    config = _load_config(opts)
    now = resolve_now(opts["now"], os.environ, config.tz)
    tasks = load_tasks(config.planning.task_file, config.tz, config.planning.default_estimate_minutes)
    week = week_for_now(now, config.tz)
    horizon_start = local_datetime(week.start, time(0, 0), config.tz)
    horizon_end = local_datetime(week.end, time(0, 0), config.tz)
    events, findings = load_events(config, horizon_start, horizon_end)
    check = build_check(config, tasks, events, now, week, findings)
    if not os.access(config.planning.output_dir, os.W_OK) and config.planning.output_dir.exists():
        check.findings.append(Finding("output_dir_unverified", "warning", "输出目录可能不可写。"))
    payload = {
        "version": __version__,
        "configPath": str(config.path),
        "taskFile": str(config.planning.task_file),
        "calendarFiles": [str(p) for p in config.planning.calendar_files],
        "counts": {
            "tasks": len(tasks),
            "openTasks": sum(1 for t in tasks if not t.completed),
            "completedTasks": sum(1 for t in tasks if t.completed),
            "unestimatedTasks": sum(1 for t in tasks if not t.estimated),
            "events": len(events),
            "workMinutes": check.capacity["workMinutes"],
            "freeMinutes": check.capacity["freeMinutes"],
            "usableMinutes": check.capacity["usableMinutes"],
        },
        "findings": [f.to_dict() for f in check.findings if f.severity != "error"],
    }
    if opts["json"]:
        _emit_json(payload)
    else:
        c = _console(opts)
        c.print(f"配置：{config.path}")
        c.print(f"时区：{config.timezone_name}")
        c.print(f"任务：{payload['counts']['tasks']} 个（未完成 {payload['counts']['openTasks']}，已完成 {payload['counts']['completedTasks']}，未估算 {payload['counts']['unestimatedTasks']}）")
        c.print(f"日历事件（本周）：{len(events)}")
        c.print(f"本周可用：{fmt_minutes(check.capacity['usableMinutes'])}")
        for finding in payload["findings"]:
            c.print(f"[{finding['severity']}] {finding['message']}")
    return 0


def cmd_version(args, opts) -> int:
    if opts["week"]:
        raise WeeklintError("invalid_argument", "version 不接受 --week。", {"option": "--week"})
    if opts["json"]:
        _emit_json({"version": __version__})
    else:
        _console(opts).print(f"weeklint {__version__}")
    return 0


def _console(opts) -> Console:
    no_color = bool(opts.get("no_color")) or os.environ.get("WEEKLINT_NO_COLOR") == "1"
    return Console(no_color=no_color, force_terminal=None, highlight=False)


def _emit_json(payload) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()


def _load_config(opts) -> Config:
    return load_config(opts.get("config"), os.environ)


def _validate_env() -> None:
    raw_now = os.environ.get("WEEKLINT_NOW")
    if raw_now and raw_now.strip():
        value = raw_now.strip()
        try:
            if " " in value:
                raise ValueError("space separator")
            if len(value) == 10 and value[4] == "-" and value[7] == "-":
                date.fromisoformat(value)
            else:
                datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value)
        except (ValueError, OverflowError):
            raise WeeklintError(
                "invalid_env",
                f"WEEKLINT_NOW 的值 {raw_now!r} 不是合法的 ISO 8601 时间。例：2026-11-02T09:00:00+08:00。",
                {"variable": "WEEKLINT_NOW", "value": raw_now},
            ) from None
    for name in ("WEEKLINT_NO_COLOR", "WEEKLINT_DEBUG"):
        value = os.environ.get(name)
        if value is not None and value not in ("", "0", "1"):
            raise WeeklintError(
                "invalid_env",
                f"{name} 的值 {value!r} 无效：只能是 0 或 1。",
                {"variable": name, "value": value},
            )


def _extract_globals(argv: list[str]) -> tuple[dict, list[str]]:
    opts = {"config": None, "json": False, "now": None, "week": None, "no_color": False, "debug": False}
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--config", "--now", "--week"):
            if i + 1 >= len(argv):
                raise WeeklintError("invalid_argument", f"{arg} 需要一个值。", {"option": arg})
            opts[arg[2:]] = argv[i + 1]
            i += 2
        elif arg.startswith("--config="):
            opts["config"] = arg.split("=", 1)[1]
            i += 1
        elif arg.startswith("--now="):
            opts["now"] = arg.split("=", 1)[1]
            i += 1
        elif arg.startswith("--week="):
            opts["week"] = arg.split("=", 1)[1]
            i += 1
        elif arg == "--json":
            opts["json"] = True
            i += 1
        elif arg == "--no-color":
            opts["no_color"] = True
            i += 1
        elif arg == "--debug":
            opts["debug"] = True
            i += 1
        else:
            rest.append(arg)
            i += 1
    return opts, rest


def _build_parser() -> _Parser:
    parser = _Parser(prog="weeklint", add_help=True)
    parser.add_argument("--version", action="version", version=f"weeklint {__version__}")
    sub = parser.add_subparsers(dest="command", parser_class=_Parser)
    p = sub.add_parser("init")
    p.add_argument("--dir", default=None)
    p = sub.add_parser("check")
    p = sub.add_parser("plan")
    p.add_argument("--no-report", action="store_true")
    p = sub.add_parser("today")
    p = sub.add_parser("explain")
    p.add_argument("query")
    p = sub.add_parser("doctor")
    p = sub.add_parser("version")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in argv
    debug = os.environ.get("WEEKLINT_DEBUG") == "1"
    try:
        _validate_env()
        opts, rest = _extract_globals(argv)
        json_mode = bool(opts["json"])
        debug = debug or bool(opts["debug"])
        parser = _build_parser()
        args = parser.parse_args(rest)
        if args.command is None:
            parser.print_help()
            return 0
        if opts["week"] and args.command not in ("check", "plan", "explain"):
            raise WeeklintError("invalid_argument", f"{args.command} 不接受 --week。", {"option": "--week"})
        if args.command == "init":
            return cmd_init(args, opts)
        if args.command == "check":
            return cmd_check(args, opts)
        if args.command == "plan":
            return cmd_plan(args, opts)
        if args.command == "today":
            return cmd_today(args, opts)
        if args.command == "explain":
            return cmd_explain(args, opts)
        if args.command == "doctor":
            return cmd_doctor(args, opts)
        if args.command == "version":
            return cmd_version(args, opts)
        raise WeeklintError("invalid_argument", f"未知命令：{args.command}", {"command": args.command})
    except WeeklintError as exc:
        _report_error(exc, json_mode)
        return exc.exit_code
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001 - top-level guard
        if debug:
            traceback.print_exc()
        _report_error(WeeklintError("internal_error", f"内部错误：{type(exc).__name__}: {exc}"), json_mode, exit_code=3)
        return 3


def _report_error(exc: WeeklintError, json_mode: bool, exit_code: int | None = None) -> None:
    payload = {"error": exc.message, "code": exc.code, "detail": exc.detail}
    if json_mode:
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
    else:
        sys.stderr.write(f"{exc.message}（{exc.code}）\n")
        if exc.detail:
            sys.stderr.write(json.dumps(exc.detail, ensure_ascii=False) + "\n")
    sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())
