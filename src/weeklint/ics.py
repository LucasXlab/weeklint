"""ICS parsing and generation.

v0.1 supports the common Google/Outlook/Apple export shape: VEVENT, single or
recurring, with TZID/UTC/floating times and all-day events. Unsupported pieces
(RECURRENCE-ID overrides, exotic RRULE parts) are skipped with a warning rather
than silently producing wrong busy time.
"""

from __future__ import annotations

import hashlib
import itertools
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from icalendar import Calendar

from .errors import WeeklintError
from .model import CalendarEvent, Finding
from .timeutil import local_datetime, normalize_datetime

MAX_ICS_BYTES = 5 * 1024 * 1024
MAX_TOTAL_ICS_BYTES = 20 * 1024 * 1024
MAX_EVENTS_PER_FILE = 5000
MAX_EXPANDED_EVENTS = 20000
MAX_OCCURRENCES = 1000


def _err(code: str, message: str, **detail: object) -> WeeklintError:
    return WeeklintError(code, message, detail)


def _exdates(value: object) -> list[datetime | date]:
    out: list[datetime | date] = []
    if value is None:
        return out
    values = value if isinstance(value, list) else [value]
    for item in values:
        dts = getattr(item, "dts", None)
        if dts is not None:
            for dt_item in dts:
                out.append(dt_item.dt)
        elif hasattr(item, "dt"):
            out.append(item.dt)  # type: ignore[attr-defined]
    return out


def _as_local(value: datetime | date, tz: ZoneInfo) -> tuple[datetime, bool]:
    """Return a local datetime and whether the source was a DATE."""
    if isinstance(value, datetime):
        return normalize_datetime(value, tz), False
    return local_datetime(value, time(0, 0), tz), True


def _event_end(ev: object, start: datetime, tz: ZoneInfo) -> datetime | None:
    dtend = ev.get("DTEND")  # type: ignore[attr-defined]
    if dtend is not None:
        try:
            end_value = ev.decoded("DTEND")  # type: ignore[attr-defined]
        except Exception:
            return None
        end, _ = _as_local(end_value, tz)
        return end
    duration = ev.get("DURATION")  # type: ignore[attr-defined]
    if duration is not None:
        try:
            delta = ev.decoded("DURATION")  # type: ignore[attr-defined]
        except Exception:
            return None
        if isinstance(delta, timedelta):
            return start + delta
    return None


def _rrule_dtstart(start: datetime, all_day: bool) -> datetime:
    return start if not all_day else start.replace(hour=0, minute=0, second=0, microsecond=0)


def _occurrences(ev: object, start: datetime, all_day: bool, horizon_start: datetime, horizon_end: datetime) -> tuple[list[datetime], bool]:
    """Expand a VEVENT into local start datetimes within the horizon.

    Returns (starts, truncated). Only occurrences that start before the horizon
    end are generated; the loop stops as soon as an occurrence is past the
    horizon (RRULEs are monotonically increasing).
    """
    rrule_prop = ev.get("RRULE")  # type: ignore[attr-defined]
    if rrule_prop is None:
        return [start], False
    try:
        rule_text = rrule_prop.to_ical().decode("utf-8")  # type: ignore[attr-defined]
        rule = rrulestr(rule_text, dtstart=_rrule_dtstart(start, all_day))
    except Exception as exc:
        raise _err(
            "ics_invalid_event",
            f"事件 {ev.get('SUMMARY', '')!r} 的 RRULE 无法展开：{exc}。",
            uid=str(ev.get("UID", "")),
        ) from None
    starts: list[datetime] = []
    truncated = False
    for idx, occ in enumerate(itertools.islice(rule, MAX_OCCURRENCES + 1)):
        if idx >= MAX_OCCURRENCES:
            truncated = True
            break
        occ_local = normalize_datetime(occ, start.tzinfo) if occ.tzinfo else local_datetime(occ.date(), occ.time(), start.tzinfo)  # type: ignore[arg-type]
        if occ_local >= horizon_end:
            break
        starts.append(occ_local)
    return starts, truncated


def load_events(config, horizon_start: datetime, horizon_end: datetime) -> tuple[list[CalendarEvent], list[Finding]]:
    findings: list[Finding] = []
    events: list[CalendarEvent] = []
    tz = config.tz
    paths: tuple[Path, ...] = config.planning.calendar_files
    if not paths:
        findings.append(Finding("no_calendar_files", "warning", "没有配置日历文件，本周按全空闲计算。"))
        return events, findings
    total_size = 0
    seen: dict[tuple[str, str, str], str] = {}
    for path in paths:
        if not path.exists():
            raise _err("calendar_file_not_found", f"找不到日历文件：{path}。检查 planning.calendar_files。", path=str(path))
        try:
            size = path.stat().st_size
            if size > MAX_ICS_BYTES:
                raise _err("calendar_file_too_large", f"日历文件超过 5 MiB：{path}（{size} 字节）。", path=str(path), size=size)
            total_size += size
            if total_size > MAX_TOTAL_ICS_BYTES:
                raise _err("calendar_too_large", f"日历文件总大小超过 20 MiB。", total=total_size)
            data = path.read_bytes()
        except OSError as exc:
            raise _err("calendar_file_unreadable", f"无法读取日历文件：{path}（{exc.strerror}）。", path=str(path)) from None
        try:
            cal = Calendar.from_ical(data)
        except Exception as exc:
            raise _err("ics_parse_error", f"日历文件无法解析：{path}（{exc}）。", path=str(path)) from None
        raw_events = list(cal.walk("VEVENT"))
        if len(raw_events) > MAX_EVENTS_PER_FILE:
            raise _err(
                "too_many_events",
                f"日历文件 {path.name} 有 {len(raw_events)} 个事件，超过 5000 个上限。",
                path=str(path),
                count=len(raw_events),
            )
        for index, ev in enumerate(raw_events):
            status = str(ev.get("STATUS", "")).upper()
            transp = str(ev.get("TRANSP", "")).upper()
            if status == "CANCELLED" or transp == "TRANSPARENT":
                continue
            summary = str(ev.get("SUMMARY", "")).strip()
            if ev.get("RECURRENCE-ID") is not None:
                findings.append(
                    Finding(
                        "recurrence_override_ignored",
                        "warning",
                        f"事件 {summary or '(无标题)'} 是重复事件的单次修改，v0.1 不合并这条修改，已跳过。",
                    )
                )
                continue
            dtstart = ev.get("DTSTART")
            if dtstart is None:
                findings.append(
                    Finding(
                        "event_missing_start",
                        "warning",
                        f"日历 {path.name} 里有一个事件没有开始时间，已跳过。",
                    )
                )
                continue
            try:
                start_raw = ev.decoded("DTSTART")
            except Exception as exc:
                raise _err(
                    "ics_invalid_event",
                    f"日历 {path.name} 里事件 {summary!r} 的 DTSTART 无效：{exc}。",
                    path=str(path),
                    uid=str(ev.get("UID", "")),
                ) from None
            start, all_day = _as_local(start_raw, tz)
            if all_day and not config.planning.block_all_day_events:
                findings.append(
                    Finding(
                        "all_day_ignored",
                        "warning",
                        f"全天事件 {summary or '(无标题)'}（{start.date()}）未计入忙时：配置里 block_all_day_events=false。",
                    )
                )
                continue
            if all_day:
                dtend_prop = ev.get("DTEND")
                if dtend_prop is None:
                    end = start + timedelta(days=1)
                else:
                    try:
                        end_raw = ev.decoded("DTEND")
                    except Exception:
                        end_raw = None
                    end = _as_local(end_raw, tz)[0] if end_raw is not None else start + timedelta(days=1)
                duration = end - start
            else:
                end = _event_end(ev, start, tz)
                if end is None:
                    findings.append(
                        Finding(
                            "event_missing_end",
                            "warning",
                            f"事件 {summary or '(无标题)'} 没有结束时间，已跳过。",
                        )
                    )
                    continue
                duration = end - start
            if duration <= timedelta(0):
                raise _err(
                    "ics_invalid_event",
                    f"日历 {path.name} 里事件 {summary!r} 的结束时间不晚于开始时间。",
                    path=str(path),
                    uid=str(ev.get("UID", "")),
                )
            uid = str(ev.get("UID", "")).strip()
            if not uid:
                uid = hashlib.sha1(f"{path.name}:{index}:{summary}:{start.isoformat()}".encode("utf-8")).hexdigest()[:12]
            starts, truncated = _occurrences(ev, start, all_day, horizon_start, horizon_end)
            if truncated:
                findings.append(
                    Finding("recurrence_truncated", "warning", f"重复事件 {summary or uid} 本周实例超过 1000 个，已截断。")
                )
            exdates = set()
            for ex in _exdates(ev.get("EXDATE")):
                ex_local, _ = _as_local(ex, tz)
                exdates.add(ex_local)
            rdates = set()
            for rd in _exdates(ev.get("RDATE")):
                rd_local, _ = _as_local(rd, tz)
                rdates.add(rd_local)
            all_starts = sorted(set(starts) | rdates)
            for occ_start in all_starts:
                if occ_start in exdates:
                    continue
                occ_end = occ_start + duration
                if occ_end <= horizon_start or occ_start >= horizon_end:
                    continue
                clipped_start = max(occ_start, horizon_start)
                clipped_end = min(occ_end, horizon_end)
                key = (uid, clipped_start.isoformat(), clipped_end.isoformat())
                if key in seen:
                    findings.append(
                        Finding(
                            "duplicate_event",
                            "warning",
                            f"事件 {summary or uid} 在 {seen[key]} 和 {path.name} 里重复，保留第一条。",
                        )
                    )
                    continue
                seen[key] = path.name
                events.append(
                    CalendarEvent(
                        uid=uid,
                        summary=summary,
                        start=clipped_start,
                        end=clipped_end,
                        all_day=all_day,
                        source_file=path.name,
                    )
                )
    if len(events) > MAX_EXPANDED_EVENTS:
        raise _err(
            "too_many_events",
            f"展开后本周有 {len(events)} 个事件，超过 20000 个上限。",
            count=len(events),
        )
    events.sort(key=lambda e: (e.start, e.end, e.uid))
    return events, findings


def _escape_ics(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def blocks_to_ics(blocks: list, tz: ZoneInfo, generated_at: datetime, version: str) -> str:
    from icalendar import Calendar as ICalendar, Event

    cal = ICalendar()
    cal.add("prodid", f"-//Weeklint//Weeklint {version}//ZH")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    for n, block in enumerate(sorted(blocks, key=lambda b: (b.start, b.task_id)), start=1):
        ev = Event()
        ev.add("uid", f"weeklint-{block.task_id}-{block.start.strftime('%Y%m%dT%H%M')}-{n}@weeklint.local")
        ev.add("dtstamp", generated_at.astimezone(timezone.utc))
        ev.add("dtstart", block.start.astimezone(timezone.utc))
        ev.add("dtend", block.end.astimezone(timezone.utc))
        ev.add("summary", f"[Weeklint] {block.title}")
        ev.add("description", f"taskId={block.task_id}; minutes={block.minutes}; locked={'true' if block.locked else 'false'}")
        ev.add("transp", "OPAQUE")
        cal.add_component(ev)
    return cal.to_ical().decode("utf-8")
