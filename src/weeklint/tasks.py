"""Markdown task parsing.

The format is intentionally tiny: one checkbox per line, optional metadata at
the end of the line. Everything else in the file (headings, prose, comments) is
ignored. Metadata is stripped from the end in a loop so the title may contain a
literal ``@`` or parentheses as long as the suffix is not a metadata call.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from .errors import WeeklintError
from .model import PRIORITIES, Task
from .timeutil import local_datetime, parse_iso_datetime

MAX_TASK_BYTES = 1024 * 1024
MAX_OPEN_TASKS = 500
MAX_TITLE = 200
TASK_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s*(.*)$")
META_RE = re.compile(r"\s+@([A-Za-z][A-Za-z0-9_]*)\(([^()]*)\)\s*$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TAG_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
DUE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DUE_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?$")
EST_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?$")
EST_HOURS_RE = re.compile(r"^(\d+(?:\.\d+)?)h$")


def _err(code: str, message: str, line: int, **detail: object) -> WeeklintError:
    return WeeklintError(code, message, {"line": line, **detail})


def _snippet(line: str) -> str:
    return line.strip()[:80]


def parse_estimate(value: str, line: int) -> int:
    value = value.strip().lower()
    total: int | None = None
    m = EST_RE.match(value)
    if m and (m.group(1) or m.group(2)):
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        total = hours * 60 + minutes
    else:
        m2 = EST_HOURS_RE.match(value)
        if m2:
            total = int(round(float(m2.group(1)) * 60))
    if total is None or total < 5 or total > 2400:
        raise _err(
            "task_invalid_estimate",
            f"@estimate 的值 {value!r} 无效：必须是 5–2400 分钟。请改成 30m、1h 或 1h30m。",
            line,
            value=value,
        )
    return total


def parse_due(value: str, tz: ZoneInfo, line: int) -> tuple[datetime, bool]:
    original = value
    value = value.strip()
    try:
        if DUE_DATE_RE.match(value):
            day = datetime.strptime(value, "%Y-%m-%d").date()
            return local_datetime(day, time(23, 59), tz), False
        if DUE_DT_RE.match(value):
            parsed = parse_iso_datetime(value, tz)
            adjusted = False
            if not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value, re.IGNORECASE):
                naive = datetime.fromisoformat(value)
                local = local_datetime(naive.date(), naive.time(), tz)
                adjusted = local.replace(tzinfo=None) != naive
                ambiguous = naive.replace(tzinfo=tz, fold=0).utcoffset() != naive.replace(tzinfo=tz, fold=1).utcoffset()
                adjusted = adjusted or ambiguous
                return local, adjusted
            return parsed, False
    except (ValueError, OverflowError):
        pass
    raise _err(
        "task_invalid_due",
        f"@due 的值 {original!r} 无效：请写成 2026-11-04 或 2026-11-04T17:00 或 2026-11-04T17:00:00+08:00。",
        line,
        value=original,
    )

def parse_priority(value: str, line: int) -> str:
    p = value.strip().lower()
    if p not in PRIORITIES:
        raise _err(
            "task_invalid_priority",
            f"@priority 的值 {value!r} 无效：只能是 high、normal、low。",
            line,
            value=value,
        )
    return p


def parse_tag(value: str, line: int) -> str:
    t = value.strip()
    if not TAG_RE.match(t):
        raise _err(
            "task_invalid_tag",
            f"@tag 的值 {value!r} 无效：1–24 个字符，只能用英文字母、数字、下划线、连字符。",
            line,
            value=value,
        )
    return t


def parse_id(value: str, line: int) -> str:
    t = value.strip()
    if not ID_RE.match(t):
        raise _err(
            "task_invalid_id",
            f"@id 的值 {value!r} 无效：1–64 个字符，只能用英文字母、数字、下划线、连字符。",
            line,
            value=value,
        )
    return t


def derive_id(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title.strip()).casefold()
    return "t-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]


def parse_task_text(text: str, tz: ZoneInfo, default_estimate: int) -> list[Task]:
    tasks: list[Task] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        m = TASK_RE.match(raw)
        if not m:
            continue
        completed = m.group(1).lower() == "x"
        rest = m.group(2).strip()
        if not rest:
            raise _err("task_parse_error", f"第 {lineno} 行的任务没有标题。", lineno, snippet=_snippet(raw))
        metadata: list[tuple[str, str]] = []
        title = rest
        if title.startswith("@"):
            only = re.match(r"^@([A-Za-z][A-Za-z0-9_]*)\(([^()]*)\)\s*$", title)
            if only:
                metadata.append((only.group(1).lower(), only.group(2).strip()))
                title = ""
        while True:
            mm = META_RE.search(title)
            if not mm:
                break
            metadata.append((mm.group(1).lower(), mm.group(2).strip()))
            title = title[: mm.start()].rstrip()
        if not title:
            raise _err("task_parse_error", f"第 {lineno} 行的任务没有标题（只有元数据）。", lineno, snippet=_snippet(raw))
        if len(title) > MAX_TITLE:
            raise _err(
                "task_parse_error",
                f"第 {lineno} 行的任务标题有 {len(title)} 个字符，超过 200 个字符的上限。",
                lineno,
                snippet=_snippet(raw),
            )
        due = None
        dst_adjusted = False
        estimate: int | None = None
        priority = "normal"
        tags: list[str] = []
        explicit_id: str | None = None
        seen_meta: set[str] = set()
        for key, value in reversed(metadata):
            if key != "tag" and key in seen_meta:
                raise _err("task_parse_error", f"第 {lineno} 行重复写了 @{key}。", lineno, snippet=_snippet(raw))
            seen_meta.add(key)
            if key == "due":
                if due is not None:
                    raise _err("task_parse_error", f"第 {lineno} 行重复写了 @due。", lineno, snippet=_snippet(raw))
                due, dst_adjusted = parse_due(value, tz, lineno)
            elif key == "estimate":
                if estimate is not None:
                    raise _err("task_parse_error", f"第 {lineno} 行重复写了 @estimate。", lineno, snippet=_snippet(raw))
                estimate = parse_estimate(value, lineno)
            elif key == "priority":
                if priority != "normal":
                    raise _err("task_parse_error", f"第 {lineno} 行重复写了 @priority。", lineno, snippet=_snippet(raw))
                priority = parse_priority(value, lineno)
            elif key == "tag":
                tags.append(parse_tag(value, lineno))
            elif key == "id":
                if explicit_id is not None:
                    raise _err("task_parse_error", f"第 {lineno} 行重复写了 @id。", lineno, snippet=_snippet(raw))
                explicit_id = parse_id(value, lineno)
            else:
                raise _err(
                    "task_unknown_metadata",
                    f"第 {lineno} 行的 @{key} 不是支持的元数据。支持：due、estimate、priority、tag、id。",
                    lineno,
                    key=key,
                    snippet=_snippet(raw),
                )
        tags.reverse()
        if len(tags) > 8:
            raise _err("task_invalid_tag", f"第 {lineno} 行有 {len(tags)} 个 @tag，最多 8 个。", lineno, snippet=_snippet(raw))
        tasks.append(
            Task(
                id=explicit_id or derive_id(title),
                title=title,
                estimate_minutes=estimate if estimate is not None else default_estimate,
                due=due,
                priority=priority,
                tags=tags,
                line=lineno,
                completed=completed,
                estimated=estimate is not None,
                dst_adjusted=dst_adjusted,
            )
        )
    seen: dict[str, Task] = {}
    for task in tasks:
        if task.id in seen:
            other = seen[task.id]
            raise _err(
                "task_duplicate_id",
                f"任务 id {task.id!r} 重复（第 {other.line} 行和第 {task.line} 行）。给其中一个加 @id(唯一名字)。",
                task.line,
                id=task.id,
                firstLine=other.line,
                snippet=task.title[:80],
            )
        seen[task.id] = task
    open_count = sum(1 for t in tasks if not t.completed)
    if open_count > MAX_OPEN_TASKS:
        raise WeeklintError(
            "too_many_tasks",
            f"未完成任务有 {open_count} 个，超过 500 个上限。请拆成多个文件或先完成一部分。",
            {"count": open_count, "max": MAX_OPEN_TASKS},
        )
    return tasks


def load_tasks(path: Path, tz: ZoneInfo, default_estimate: int) -> list[Task]:
    if not path.exists():
        raise WeeklintError(
            "task_file_not_found",
            f"找不到任务文件：{path}。检查 planning.task_file，或先运行 weeklint init。",
            {"path": str(path)},
        )
    try:
        size = path.stat().st_size
        if size > MAX_TASK_BYTES:
            raise WeeklintError(
                "task_file_too_large",
                f"任务文件超过 1 MiB：{path}（{size} 字节）。",
                {"path": str(path), "size": size},
            )
        data = path.read_bytes()
    except OSError as exc:
        raise WeeklintError(
            "task_file_not_found",
            f"无法读取任务文件：{path}（{exc.strerror}）。",
            {"path": str(path)},
        ) from None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WeeklintError(
            "task_file_encoding",
            f"任务文件不是 UTF-8：{path}（{exc.reason}）。请另存为 UTF-8。",
            {"path": str(path)},
        ) from None
    return parse_task_text(text, tz, default_estimate)
