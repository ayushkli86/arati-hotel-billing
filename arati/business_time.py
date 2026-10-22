"""Business-day arithmetic for the hotel's reporting timezone.

Every date boundary in the app is defined by the hotel's business timezone,
defaulting to ``Asia/Kathmandu`` (UTC+05:45). A reporting day runs from local
midnight to the next local midnight, so a transaction recorded at 23:59
belongs to that day and one recorded at 00:00 belongs to the next.

The module never depends on the machine's local timezone: the offset is
applied explicitly, so the same result is produced on a server in Frankfurt
and on the till in Khandbari.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Kathmandu"

# A day boundary is a wall-clock time in the business timezone.
MIDNIGHT = time(0, 0, 0)


def get_zone(name: str | None = None) -> ZoneInfo:
    """Return the business timezone, falling back to Kathmandu if unknown."""
    for candidate in (name, DEFAULT_TIMEZONE):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo(DEFAULT_TIMEZONE)


def business_timezone(conn: sqlite3.Connection | None = None) -> ZoneInfo:
    """The timezone the hotel trades in, from settings when available."""
    if conn is None:
        return get_zone()
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'business_timezone'"
        ).fetchone()
    except sqlite3.Error:
        row = None
    return get_zone(row[0] if row else None)


def now(tz: ZoneInfo | None = None) -> datetime:
    """Current time in the business timezone."""
    zone = tz or get_zone()
    return datetime.now(zone)


def today(tz: ZoneInfo | None = None) -> date:
    """Today's business date."""
    return now(tz).date()


def to_business(moment: datetime, tz: ZoneInfo | None = None) -> datetime:
    """Convert any datetime (naive = already business-local) to business time."""
    zone = tz or get_zone()
    if moment.tzinfo is None:
        return moment.replace(tzinfo=zone)
    return moment.astimezone(zone)


def business_date_of(moment: datetime, tz: ZoneInfo | None = None) -> str:
    """The business date (``YYYY-MM-DD``) a moment belongs to."""
    return to_business(moment, tz).date().isoformat()


def day_start(day: date | str, tz: ZoneInfo | None = None) -> datetime:
    """First instant of a business day."""
    zone = tz or get_zone()
    parsed = _as_date(day)
    return datetime.combine(parsed, MIDNIGHT, tzinfo=zone)


def day_end(day: date | str, tz: ZoneInfo | None = None) -> datetime:
    """First instant of the *next* business day (exclusive upper bound)."""
    return day_start(day, tz) + timedelta(days=1)


def previous_day(day: date | str) -> str:
    """The calendar day before ``day``."""
    return (_as_date(day) - timedelta(days=1)).isoformat()


def next_day(day: date | str) -> str:
    """The calendar day after ``day``."""
    return (_as_date(day) + timedelta(days=1)).isoformat()


def date_range(start: str, end: str) -> list[str]:
    """Every business date from ``start`` to ``end`` inclusive."""
    first, last = _as_date(start), _as_date(end)
    if last < first:
        return []
    days = []
    current = first
    while current <= last:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def seconds_until_midnight(tz: ZoneInfo | None = None) -> float:
    """How long until the next business midnight, in seconds.

    Used by the scheduler to sleep exactly until closing time instead of
    polling every few seconds.
    """
    zone = tz or get_zone()
    current = datetime.now(zone)
    upcoming = datetime.combine(current.date() + timedelta(days=1), MIDNIGHT, tzinfo=zone)
    return max(1.0, (upcoming - current).total_seconds())


def parse_timestamp(value: str | None, tz: ZoneInfo | None = None) -> datetime | None:
    """Parse a stored timestamp string into an aware business-time datetime.

    Timestamps are written as ``YYYY-MM-DD HH:MM:SS`` in business time, so a
    naive string is read as business-local rather than machine-local.
    """
    if not value:
        return None
    zone = tz or get_zone()
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=zone)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return to_business(parsed, zone)


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
