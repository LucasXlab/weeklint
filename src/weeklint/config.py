"""Configuration loading and validation.

The YAML file is deliberately strict: unknown keys and wrong types are errors,
so a typo cannot silently fall back to a default. Paths are resolved relative to
the config file (``~`` is expanded; absolute paths are kept).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .errors import WeeklintError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_WORK = ["09:00-18:00"]
MAX_CONFIG_BYTES = 256 * 1024


@dataclass(frozen=True, slots=True)
class PlanningConfig:
    include_weekends: bool
    work_hours: dict[str, list[tuple[time, time]]]
    buffer_after_event_minutes: int
    gap_between_tasks_minutes: int
    min_block_minutes: int
    max_block_minutes: int
    max_deep_work_minutes_per_day: int
    max_tasks_per_day: int
    default_estimate_minutes: int
    lock_existing_plan: bool
    block_all_day_events: bool
    task_file: Path
    calendar_files: tuple[Path, ...]
    output_dir: Path
    report_title: str


@dataclass(frozen=True, slots=True)
class Config:
    path: Path
    base_dir: Path
    version: int
    timezone_name: str
    tz: ZoneInfo
    planning: PlanningConfig


def _bad_type(key: str, expected: str, value: Any) -> WeeklintError:
    return WeeklintError(
        "config_invalid_type",
        f"配置项 {key} 的类型不对：需要 {expected}，实际是 {type(value).__name__}。",
        {"key": key, "expected": expected, "actual": type(value).__name__},
    )


def _unknown(key: str) -> WeeklintError:
    return WeeklintError(
        "config_unknown_key",
        f"配置里有未知的键：{key}。请删掉它，或对照 README 的配置表检查拼写。",
        {"key": key},
    )


def _range(key: str, value: Any, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _bad_type(key, "整数", value)
    if value < low or value > high:
        raise WeeklintError(
            "config_value_out_of_range",
            f"配置项 {key} 的值 {value} 超出范围：必须是 {low}–{high}。",
            {"key": key, "value": value, "min": low, "max": high},
        )
    return value


def _bool(key: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise _bad_type(key, "布尔值 true/false", value)
    return value


def _string(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise _bad_type(key, "字符串", value)
    return value


def _parse_time(value: str, key: str) -> time:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise WeeklintError(
            "config_invalid_time_range",
            f"配置项 {key} 的时间段 {value!r} 格式不对：请写成 HH:MM-HH:MM，例如 09:00-12:00。",
            {"key": key, "value": value},
        )
    try:
        hh, mm = int(value[:2]), int(value[3:])
    except ValueError:
        raise WeeklintError(
            "config_invalid_time_range",
            f"配置项 {key} 的时间段 {value!r} 格式不对：请写成 HH:MM-HH:MM。",
            {"key": key, "value": value},
        ) from None
    if not (0 <= hh <= 23 and 0 <= mm <= 59) or mm % 5 != 0:
        raise WeeklintError(
            "config_invalid_time_range",
            f"配置项 {key} 的时间 {value!r} 无效：小时 00–23，分钟 00–59 且必须是 5 的倍数。",
            {"key": key, "value": value},
        )
    return time(hh, mm)


def _parse_work_hours(raw: Any, key: str = "planning.work_hours") -> dict[str, list[tuple[time, time]]]:
    if not isinstance(raw, dict):
        raise _bad_type(key, "映射（每天一段或多段时间）", raw)
    result: dict[str, list[tuple[time, time]]] = {d: [] for d in WEEKDAYS}
    for day, segments in raw.items():
        if day not in WEEKDAYS:
            raise _unknown(f"{key}.{day}")
        if not isinstance(segments, list):
            raise _bad_type(f"{key}.{day}", "字符串数组", segments)
        if len(segments) > 4:
            raise WeeklintError(
                "config_invalid_time_range",
                f"配置项 {key}.{day} 最多 4 段时间，实际 {len(segments)} 段。",
                {"key": f"{key}.{day}", "count": len(segments)},
            )
        parsed: list[tuple[time, time]] = []
        for seg in segments:
            if not isinstance(seg, str) or seg.count("-") != 1:
                raise WeeklintError(
                    "config_invalid_time_range",
                    f"配置项 {key}.{day} 的时间段 {seg!r} 格式不对：请写成 HH:MM-HH:MM。",
                    {"key": f"{key}.{day}", "value": seg},
                )
            a, b = seg.split("-", 1)
            start, end = _parse_time(a, f"{key}.{day}"), _parse_time(b, f"{key}.{day}")
            if end <= start:
                raise WeeklintError(
                    "config_invalid_time_range",
                    f"配置项 {key}.{day} 的时间段 {seg!r} 结束时间必须晚于开始时间。",
                    {"key": f"{key}.{day}", "value": seg},
                )
            parsed.append((start, end))
        parsed.sort()
        for (a_start, a_end), (b_start, b_end) in zip(parsed, parsed[1:]):
            if b_start < a_end:
                raise WeeklintError(
                    "config_invalid_time_range",
                    f"配置项 {key}.{day} 的时间段重叠：{a_start.strftime('%H:%M')}-{a_end.strftime('%H:%M')} 与 {b_start.strftime('%H:%M')}-{b_end.strftime('%H:%M')}。",
                    {"key": f"{key}.{day}"},
                )
        result[day] = parsed
    return result


def _resolve(base: Path, value: str, key: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise WeeklintError("config_invalid_path", f"配置项 {key} 不能为空。", {"key": key})
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def load_config(path: str | Path | None, env: Mapping[str, str] | None = None) -> Config:
    env = env or {}
    raw_path = path or env.get("WEEKLINT_CONFIG") or "weeklint.yaml"
    cfg_path = Path(raw_path).expanduser()
    if not cfg_path.is_absolute():
        cfg_path = Path.cwd() / cfg_path
    cfg_path = cfg_path.resolve()
    if not cfg_path.exists():
        raise WeeklintError(
            "config_not_found",
            f"找不到配置文件：{cfg_path}。先运行 weeklint init，或用 --config 指定路径。",
            {"path": str(cfg_path)},
        )
    if cfg_path.stat().st_size > MAX_CONFIG_BYTES:
        raise WeeklintError(
            "config_too_large",
            f"配置文件超过 256 KiB：{cfg_path}。",
            {"path": str(cfg_path), "size": cfg_path.stat().st_size},
        )
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WeeklintError(
            "config_invalid_encoding",
            f"配置文件不是 UTF-8：{cfg_path}（{exc.reason}）。请另存为 UTF-8。",
            {"path": str(cfg_path)},
        ) from None
    except OSError as exc:
        raise WeeklintError(
            "config_not_found",
            f"无法读取配置文件：{cfg_path}（{exc.strerror}）。",
            {"path": str(cfg_path)},
        ) from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = (mark.line + 1) if mark is not None else None
        raise WeeklintError(
            "config_invalid_yaml",
            f"配置文件 YAML 解析失败：{cfg_path}" + (f" 第 {line} 行。" if line else "。"),
            {"path": str(cfg_path), "line": line},
        ) from None
    if not isinstance(data, dict):
        raise WeeklintError(
            "config_invalid_yaml",
            f"配置文件必须是一个 YAML 映射（key: value），实际是 {type(data).__name__}。",
            {"path": str(cfg_path)},
        )
    allowed_top = {"version", "timezone", "planning"}
    for key in data:
        if key not in allowed_top:
            raise _unknown(str(key))
    if "version" not in data:
        raise WeeklintError("config_version_unsupported", "配置缺少 version；当前只支持 version: 1。", {"version": None})
    version = data["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise WeeklintError(
            "config_version_unsupported",
            f"不支持的配置版本：{version!r}；当前只支持 version: 1。",
            {"version": version},
        )
    tz_name = data.get("timezone", "UTC")
    if not isinstance(tz_name, str):
        raise _bad_type("timezone", "IANA 时区字符串", tz_name)
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise WeeklintError(
            "config_invalid_timezone",
            f"时区 {tz_name!r} 无效：请用 IANA 名称，例如 Asia/Shanghai、UTC、America/New_York。",
            {"timezone": tz_name},
        ) from None

    planning_raw = data.get("planning", {})
    if not isinstance(planning_raw, dict):
        raise _bad_type("planning", "映射", planning_raw)
    allowed_planning = {
        "include_weekends", "work_hours", "buffer_after_event_minutes",
        "gap_between_tasks_minutes", "min_block_minutes", "max_block_minutes",
        "max_deep_work_minutes_per_day", "max_tasks_per_day",
        "default_estimate_minutes", "lock_existing_plan", "block_all_day_events",
        "task_file", "calendar_files", "output_dir", "report",
    }
    for key in planning_raw:
        if key not in allowed_planning:
            raise _unknown(f"planning.{key}")

    if "work_hours" in planning_raw:
        work_hours = _parse_work_hours(planning_raw["work_hours"])
    else:
        work_hours = {d: ([(time(9, 0), time(18, 0))] if d in WEEKDAYS[:5] else []) for d in WEEKDAYS}

    include_weekends = _bool("planning.include_weekends", planning_raw.get("include_weekends", False))
    buffer = _range("planning.buffer_after_event_minutes", planning_raw.get("buffer_after_event_minutes", 10), 0, 120)
    gap = _range("planning.gap_between_tasks_minutes", planning_raw.get("gap_between_tasks_minutes", 10), 0, 120)
    min_block = _range("planning.min_block_minutes", planning_raw.get("min_block_minutes", 30), 15, 240)
    max_block = _range("planning.max_block_minutes", planning_raw.get("max_block_minutes", 120), 30, 480)
    if max_block < min_block:
        raise WeeklintError(
            "config_value_out_of_range",
            f"planning.max_block_minutes（{max_block}）不能小于 min_block_minutes（{min_block}）。",
            {"key": "planning.max_block_minutes", "value": max_block, "min": min_block},
        )
    deep = _range("planning.max_deep_work_minutes_per_day", planning_raw.get("max_deep_work_minutes_per_day", 180), 0, 720)
    max_tasks = _range("planning.max_tasks_per_day", planning_raw.get("max_tasks_per_day", 4), 1, 12)
    default_est = _range("planning.default_estimate_minutes", planning_raw.get("default_estimate_minutes", 60), 5, 480)
    lock = _bool("planning.lock_existing_plan", planning_raw.get("lock_existing_plan", True))
    block_all = _bool("planning.block_all_day_events", planning_raw.get("block_all_day_events", True))

    base = cfg_path.parent
    task_file = _resolve(base, _string("planning.task_file", planning_raw.get("task_file", "tasks.md")), "planning.task_file")
    cals_raw = planning_raw.get("calendar_files", ["calendar.ics"])
    if not isinstance(cals_raw, list):
        raise _bad_type("planning.calendar_files", "字符串数组", cals_raw)
    if len(cals_raw) > 20:
        raise WeeklintError(
            "config_too_many_calendars",
            f"calendar_files 最多 20 个，实际 {len(cals_raw)} 个。",
            {"count": len(cals_raw)},
        )
    calendar_files = tuple(_resolve(base, _string(f"planning.calendar_files[{i}]", c), f"planning.calendar_files[{i}]") for i, c in enumerate(cals_raw))
    output_dir = _resolve(base, _string("planning.output_dir", planning_raw.get("output_dir", ".weeklint")), "planning.output_dir")
    if output_dir.exists() and not output_dir.is_dir():
        raise WeeklintError(
            "config_invalid_path",
            f"planning.output_dir 已存在且不是目录：{output_dir}。请换一个目录名。",
            {"path": str(output_dir)},
        )

    report_raw = planning_raw.get("report", {})
    if not isinstance(report_raw, dict):
        raise _bad_type("planning.report", "映射", report_raw)
    for key in report_raw:
        if key != "title":
            raise _unknown(f"planning.report.{key}")
    title = report_raw.get("title", "本周计划")
    if not isinstance(title, str) or not title.strip() or len(title) > 80 or "\n" in title or "\r" in title:
        raise WeeklintError(
            "config_invalid_value",
            "planning.report.title 必须是 1–80 个字符、且不能含换行。",
            {"key": "planning.report.title"},
        )

    planning = PlanningConfig(
        include_weekends=include_weekends,
        work_hours=work_hours,
        buffer_after_event_minutes=buffer,
        gap_between_tasks_minutes=gap,
        min_block_minutes=min_block,
        max_block_minutes=max_block,
        max_deep_work_minutes_per_day=deep,
        max_tasks_per_day=max_tasks,
        default_estimate_minutes=default_est,
        lock_existing_plan=lock,
        block_all_day_events=block_all,
        task_file=task_file,
        calendar_files=calendar_files,
        output_dir=output_dir,
        report_title=title,
    )
    return Config(
        path=cfg_path,
        base_dir=base,
        version=version,
        timezone_name=tz_name,
        tz=tz,
        planning=planning,
    )


def init_config_dict() -> dict[str, Any]:
    return {
        "version": 1,
        "timezone": "Asia/Shanghai",
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
            "report": {"title": "本周计划"},
        },
    }


INIT_CONFIG_TEMPLATE = """version: 1
timezone: Asia/Shanghai
planning:
  include_weekends: false
  work_hours:
    mon: ["09:00-12:00", "13:30-18:00"]
    tue: ["09:00-12:00", "13:30-18:00"]
    wed: ["09:00-12:00", "13:30-18:00"]
    thu: ["09:00-12:00", "13:30-18:00"]
    fri: ["09:00-12:00", "13:30-18:00"]
    sat: []
    sun: []
  buffer_after_event_minutes: 10
  gap_between_tasks_minutes: 10
  min_block_minutes: 30
  max_block_minutes: 120
  max_deep_work_minutes_per_day: 180
  max_tasks_per_day: 4
  default_estimate_minutes: 60
  lock_existing_plan: true
  block_all_day_events: true
  task_file: tasks.md
  calendar_files: ["calendar.ics"]
  output_dir: .weeklint
  report:
    title: 本周计划
"""


def dump_init_config() -> str:
    return INIT_CONFIG_TEMPLATE
