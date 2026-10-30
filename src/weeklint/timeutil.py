"""Local-time helpers with explicit DST behavior.

Python's zoneinfo follows the PEP 495 rule: for an ambiguous local time,
``fold=0`` is the first occurrence; for a non-existent local time, the
``datetime`` keeps the pre-transition offset until it is converted to UTC and
back. We make both cases explicit here so callers don't have to guess.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def add_minutes(value: datetime, minutes: int) -> datetime:
    """Add elapsed minutes, not wall-clock minutes.

    On DST days an aware local datetime plus ``timedelta`` follows the wall
    clock (01:00 + 2h may be only one real hour). Task and buffer durations
    are elapsed time, so add in UTC and convert back.
    """
    if value.tzinfo is None:
        return value + timedelta(minutes=minutes)
    return (value.astimezone(timezone.utc) + timedelta(minutes=minutes)).astimezone(value.tzinfo)


def local_datetime(day: date, clock: time, tz: ZoneInfo) -> datetime:
    """Combine a date and wall-clock time, shifting non-existent times forward."""
    naive = datetime.combine(day, clock)
    dt = naive.replace(tzinfo=tz, fold=0)
    # Round-trip through UTC exposes a non-existent wall time: the local hour
    # comes back different from the requested one.
    roundtrip = dt.astimezone(timezone.utc).astimezone(tz)
    if roundtrip.replace(tzinfo=None) != naive:
        return roundtrip.replace(fold=0)
    return dt


def normalize_datetime(dt: datetime, tz: ZoneInfo) -> datetime:
    """Attach the configured zone to a naive value, or convert an aware one."""
    if dt.tzinfo is None:
        return local_datetime(dt.date(), dt.time().replace(tzinfo=None), tz)
    return dt.astimezone(tz).replace(fold=0)


def parse_iso_datetime(text: str, tz: ZoneInfo) -> datetime:
    """Parse the subset of ISO 8601 used by the CLI/config/tasks.

    Accepts ``YYYY-MM-DDTHH:MM[:SS]`` with optional ``Z`` or ``±HH:MM``.
    A trailing ``Z`` is normalized to ``+00:00`` for older Python versions.
    """
    value = text.strip()
    if value.endswith("Z") or value.endswith("z"):
        value = value[:-1] + "+00:00"
    # datetime.fromisoformat accepts a space separator too; the spec does not.
    if " " in value:
        raise ValueError("use T between date and time")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return local_datetime(dt.date(), dt.time(), tz)
    return dt.astimezone(tz).replace(fold=0)
