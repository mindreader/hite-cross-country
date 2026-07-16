"""
Utility helpers shared across the application.

Timezone convention: all datetimes in the database and templates are
**naive local time** in America/Kentucky/Louisville (US Eastern, with DST).
The ``now_local()`` function is the single source of "current time".
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

# ── Timezone ───────────────────────────────────────────────────────────

TZ = ZoneInfo("America/Kentucky/Louisville")


def now_local() -> datetime:
    """Return the current wall-clock time as a naive datetime in TZ."""
    return datetime.now(TZ).replace(tzinfo=None)


# ── Time formatting ────────────────────────────────────────────────────


def seconds_to_mmss(total_seconds: int | None) -> str:
    """Convert integer seconds to 'MM:SS' string.

    >>> seconds_to_mmss(540)
    '9:00'
    >>> seconds_to_mmss(605)
    '10:05'
    >>> seconds_to_mmss(None)
    ''
    """
    if total_seconds is None:
        return ""
    minutes, secs = divmod(int(total_seconds), 60)
    return f"{minutes}:{secs:02d}"


def mmss_to_seconds(mmss: str) -> int:
    """Parse 'MM:SS' or 'M:SS' into integer seconds.

    Also accepts separate minutes/seconds ints via ``minutes_seconds_to_int``.

    >>> mmss_to_seconds('9:00')
    540
    >>> mmss_to_seconds('10:05')
    605

    Raises ValueError on bad input.
    """
    mmss = mmss.strip()
    m = re.fullmatch(r"(\d+):(\d{1,2})", mmss)
    if not m:
        raise ValueError(f"Invalid time format: {mmss!r} – expected MM:SS")
    minutes, seconds = int(m.group(1)), int(m.group(2))
    if seconds > 59:
        raise ValueError(f"Seconds out of range: {seconds}")
    return minutes * 60 + seconds


def minutes_seconds_to_int(minutes: int, seconds: int) -> int:
    """Convert separate minute/second integers to total seconds.

    Raises ValueError if seconds not in 0..59 or values negative.
    """
    if not (0 <= seconds <= 59):
        raise ValueError(f"Seconds must be 0–59, got {seconds}")
    if minutes < 0:
        raise ValueError(f"Minutes must be non-negative, got {minutes}")
    return minutes * 60 + seconds


# ── Slug generation ────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    """Lowercase ASCII slug: 'Hite Invitational' → 'hite-invitational'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def student_slug(first_name: str, last_name: str) -> str:
    """Generate a URL slug for a student.

    Pattern: ``first-last`` e.g. ``robert-watson`` (PRD 5.3).
    """
    return _slugify(f"{first_name} {last_name}")


def event_slug(name: str, date: datetime) -> str:
    """Generate a URL slug for an event.

    Pattern: ``name-YYYY-MM-DD`` e.g. ``hite-invitational-2026-08-30`` (PRD 5.8).
    """
    return _slugify(f"{name} {date.strftime('%Y-%m-%d')}")


# ── Display helpers ────────────────────────────────────────────────────


def public_display_name(first_name: str, last_name: str) -> str:
    """First name + last initial: 'Robert Watson' → 'Robert W.'"""
    initial = last_name[0].upper() if last_name else ""
    return f"{first_name} {initial}."


# ── Date helpers ───────────────────────────────────────────────────────


def is_upcoming(dt: datetime) -> bool:
    """True if the (naive-local) datetime is in the future."""
    return dt > now_local()


def is_past(dt: datetime) -> bool:
    """True if the (naive-local) datetime is in the past."""
    return dt <= now_local()


# ── Event helpers ──────────────────────────────────────────────────────


def event_cutoff_dt(event) -> datetime:
    """Return the datetime used to decide if an event is in the past.

    An event is considered *past* once its ``end_datetime`` (if set) has
    passed; otherwise its ``start_datetime`` is the cutoff.  This means
    an in-progress event (started but not yet ended) is still treated as
    upcoming/present.  Use ``now_local()`` to compare.
    """
    return event.end_datetime if event.end_datetime else event.start_datetime


# ── Calendar helpers ───────────────────────────────────────────────────

import calendar as _cal_module  # noqa: E402 — stdlib, fine at module level

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

_DAY_ABBREVS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def build_month_grid(year: int, month: int, events: list) -> list:
    """Build a calendar grid for ``year``/``month`` with events.

    Returns a list of weeks; each week is a list of
    ``(day_number, events_list)`` tuples where ``day_number == 0``
    indicates padding (days outside the current month).

    Only events whose ``start_datetime`` falls in ``year``/``month``
    are included in the grid cells.
    """
    raw_grid = _cal_module.monthcalendar(year, month)
    day_map: dict[int, list] = {}
    for evt in events:
        dt = evt.start_datetime
        if dt.year == year and dt.month == month:
            day_map.setdefault(dt.day, []).append(evt)

    return [
        [(d, day_map.get(d, [])) for d in week]
        for week in raw_grid
    ]


def prev_month(year: int, month: int) -> tuple:
    """Return ``(year, month)`` for the month before the given one."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def next_month(year: int, month: int) -> tuple:
    """Return ``(year, month)`` for the month after the given one."""
    if month == 12:
        return year + 1, 1
    return year, month + 1


def month_name(month: int) -> str:
    """Return the full English name for a month number (1–12)."""
    return _MONTH_NAMES[month]


def calendar_day_abbrevs() -> list:
    """Return the list of day abbreviations starting Monday."""
    return _DAY_ABBREVS
# ── Slug collision helper (new) ────────────────────────────────────────


def unique_slug(base_slug: str, exists_fn) -> str:
    """Return *base_slug*, appending -2, -3, … until *exists_fn(slug)* is False.

    *exists_fn* is a callable that returns True when the candidate slug is
    already taken (e.g. a DB query).
    """
    slug = base_slug
    n = 2
    while exists_fn(slug):
        slug = f"{base_slug}-{n}"
        n += 1
    return slug


# ── Form / datetime helpers (new) ─────────────────────────────────────


def parse_date_time(date_str: str, time_str: str) -> "datetime | None":
    """Combine a 'YYYY-MM-DD' date string and 'HH:MM' time string into a naive datetime.

    Returns None if either string is empty or invalid.
    """
    if not date_str or not time_str:
        return None
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def parse_datetime_local(dt_str: str) -> "datetime | None":
    """Parse an HTML datetime-local string ('YYYY-MM-DDTHH:MM') to a naive datetime.

    Returns None if the string is empty or invalid.
    """
    if not dt_str:
        return None
    try:
        return datetime.strptime(dt_str.strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def format_date(dt: "datetime | None") -> str:
    """Format a datetime to 'YYYY-MM-DD' for date inputs.  Returns '' if None."""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d")


def format_time_hhmm(dt: "datetime | None") -> str:
    """Format a datetime to 'HH:MM' for time inputs.  Returns '' if None."""
    if dt is None:
        return ""
    return dt.strftime("%H:%M")


def format_datetime_local(dt: "datetime | None") -> str:
    """Format a datetime to 'YYYY-MM-DDTHH:MM' for datetime-local inputs.  Returns '' if None."""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M")
