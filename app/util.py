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
