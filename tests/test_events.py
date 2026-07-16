"""
Tests for the events/calendar pages (app/routers/events.py).

These tests cover:
- Upcoming page excludes past events, shows future events, respects type filter
- Calendar month grid renders correct grid and handles month boundaries
- Event detail shows results sorted fastest first, cancelled notice, postponed notice
- Event list has upcoming and past sections
- Type and distance filters work
- Empty states render correctly
- 404 for unknown event slug
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def events_app():
    """Create a fresh FastAPI app with a temp DB for events tests."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["HITE_DB_PATH"] = tmp.name

    from app.db import reset_singletons, init_db

    reset_singletons()
    init_db()

    from app.main import create_app

    application = create_app()
    yield application

    # Cleanup
    from app.db import reset_singletons as rs

    rs()
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture(scope="module")
async def events_client(events_app):
    """Async HTTP client wired to the events_app."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=events_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture(scope="module")
def events_db(events_app):
    """SQLAlchemy session for seeding / inspecting test data."""
    from app.db import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


# ── Helpers ────────────────────────────────────────────────────────────


def _make_event(
    db,
    *,
    name: str,
    slug: str,
    start: datetime,
    end: datetime | None = None,
    etype: str = "race",
    status: str = "scheduled",
    distance: float | None = None,
    distance_unit: str | None = None,
    location_name: str | None = None,
    street_address: str | None = None,
    description: str | None = None,
):
    from app.models import Event, EventType, EventStatus, DistanceUnit

    evt = Event(
        name=name,
        slug=slug,
        start_datetime=start,
        end_datetime=end,
        type=EventType(etype),
        status=EventStatus(status),
        distance=distance,
        distance_unit=DistanceUnit(distance_unit) if distance_unit else None,
        location_name=location_name,
        street_address=street_address,
        description=description,
    )
    db.add(evt)
    db.commit()
    db.refresh(evt)
    return evt


def _make_student(db, *, first: str, last: str, slug: str):
    from app.models import Student

    s = Student(first_name=first, last_name=last, slug=slug)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _make_result(db, *, student_id: int, event_id: int, time_seconds: int | None,
                 status: str = "completed", placement: int | None = None):
    from app.models import Result, ResultStatus

    r = Result(
        student_id=student_id,
        event_id=event_id,
        time_seconds=time_seconds,
        status=ResultStatus(status),
        placement=placement,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


_NOW = datetime(2026, 7, 15, 12, 0, 0)  # fixed "now" reference for seed data


# ── Upcoming page tests ────────────────────────────────────────────────


class TestUpcomingPage:
    @pytest.fixture(autouse=True, scope="class")
    def seed(self, events_db):
        """Seed past and future events once per class."""
        db = events_db
        self.future = _make_event(
            db,
            name="Future Race",
            slug="future-race-2026-08-01",
            start=_NOW + timedelta(days=17),
            etype="race",
            status="scheduled",
        )
        self.past = _make_event(
            db,
            name="Past Practice",
            slug="past-practice-2026-06-01",
            start=_NOW - timedelta(days=44),
            etype="practice",
            status="completed",
        )
        self.cancelled_future = _make_event(
            db,
            name="Cancelled Race",
            slug="cancelled-race-2026-08-10",
            start=_NOW + timedelta(days=26),
            etype="race",
            status="cancelled",
        )
        self.future_practice = _make_event(
            db,
            name="Future Practice",
            slug="future-practice-2026-08-05",
            start=_NOW + timedelta(days=21),
            etype="practice",
        )
        yield
        # cleanup
        for evt in [self.future, self.past, self.cancelled_future, self.future_practice]:
            db.delete(evt)
        db.commit()

    @pytest.mark.asyncio
    async def test_upcoming_excludes_past_events(self, events_client):
        r = await events_client.get("/upcoming")
        assert r.status_code == 200
        assert "Past Practice" not in r.text

    @pytest.mark.asyncio
    async def test_upcoming_includes_future_events(self, events_client):
        r = await events_client.get("/upcoming")
        assert r.status_code == 200
        assert "Future Race" in r.text

    @pytest.mark.asyncio
    async def test_upcoming_shows_cancelled_future_event(self, events_client):
        r = await events_client.get("/upcoming")
        assert r.status_code == 200
        assert "Cancelled Race" in r.text
        # Should show cancellation banner
        assert "cancelled" in r.text.lower()

    @pytest.mark.asyncio
    async def test_upcoming_type_filter_race(self, events_client):
        r = await events_client.get("/upcoming?type=race")
        assert r.status_code == 200
        assert "Future Race" in r.text
        assert "Future Practice" not in r.text

    @pytest.mark.asyncio
    async def test_upcoming_type_filter_practice(self, events_client):
        r = await events_client.get("/upcoming?type=practice")
        assert r.status_code == 200
        assert "Future Practice" in r.text
        assert "Future Race" not in r.text

    @pytest.mark.asyncio
    async def test_upcoming_empty_state_with_filter(self, events_client):
        r = await events_client.get("/upcoming?type=team_meeting")
        assert r.status_code == 200
        # Should show some "no events" message
        assert "no" in r.text.lower() or "empty" in r.text.lower() or "scheduled" in r.text.lower()


# ── Past cutoff: end_datetime logic ───────────────────────────────────


class TestPastCutoff:
    """Verify that end_datetime is used as the cutoff when set."""

    @pytest.fixture(autouse=True, scope="class")
    def seed(self, events_db):
        from app.util import now_local as _now_local
        db = events_db
        real_now = _now_local()
        # Started 2 hours ago but ends 2 hours in the future → still upcoming
        self.ongoing = _make_event(
            db,
            name="Ongoing Event",
            slug="ongoing-event-realtime",
            start=real_now - timedelta(hours=2),
            end=real_now + timedelta(hours=2),
            etype="other",
        )
        # Ended 1 hour ago → not upcoming
        self.ended = _make_event(
            db,
            name="Ended Event",
            slug="ended-event-realtime",
            start=real_now - timedelta(hours=4),
            end=real_now - timedelta(hours=1),
            etype="other",
        )
        yield
        db.delete(self.ongoing)
        db.delete(self.ended)
        db.commit()

    @pytest.mark.asyncio
    async def test_ongoing_event_shown_in_upcoming(self, events_client):
        r = await events_client.get("/upcoming")
        assert r.status_code == 200
        assert "Ongoing Event" in r.text

    @pytest.mark.asyncio
    async def test_ended_event_excluded_from_upcoming(self, events_client):
        r = await events_client.get("/upcoming")
        assert r.status_code == 200
        assert "Ended Event" not in r.text


# ── Calendar page tests ────────────────────────────────────────────────


class TestCalendarPage:
    @pytest.mark.asyncio
    async def test_calendar_renders(self, events_client):
        r = await events_client.get("/calendar")
        assert r.status_code == 200
        assert "Calendar" in r.text

    @pytest.mark.asyncio
    async def test_calendar_month_view(self, events_client):
        r = await events_client.get("/calendar?view=month&y=2026&m=8")
        assert r.status_code == 200
        assert "August" in r.text
        assert "2026" in r.text

    @pytest.mark.asyncio
    async def test_calendar_month_view_contains_grid_days(self, events_client):
        r = await events_client.get("/calendar?view=month&y=2026&m=8")
        assert r.status_code == 200
        # August 2026 has 31 days; at least some day numbers should appear in the grid
        assert "cal-grid" in r.text
        assert "Mon" in r.text  # day abbreviations in header

    @pytest.mark.asyncio
    async def test_calendar_handles_january_boundary(self, events_client):
        """Navigating prev from January should go to December of prior year."""
        r = await events_client.get("/calendar?view=month&y=2026&m=1")
        assert r.status_code == 200
        assert "January" in r.text
        # Prev link should point to Dec 2025
        assert "y=2025" in r.text
        assert "m=12" in r.text

    @pytest.mark.asyncio
    async def test_calendar_handles_december_boundary(self, events_client):
        """Navigating next from December should go to January of next year."""
        r = await events_client.get("/calendar?view=month&y=2026&m=12")
        assert r.status_code == 200
        assert "December" in r.text
        # Next link should point to Jan 2027
        assert "y=2027" in r.text
        assert "m=1" in r.text

    @pytest.mark.asyncio
    async def test_calendar_agenda_view(self, events_client):
        r = await events_client.get("/calendar?view=agenda")
        assert r.status_code == 200
        assert "Agenda" in r.text

    @pytest.mark.asyncio
    async def test_calendar_default_is_agenda(self, events_client):
        r = await events_client.get("/calendar")
        assert r.status_code == 200
        # Default view=agenda: agenda section has "active" chip
        assert "cal-agenda-section" in r.text

    @pytest.mark.asyncio
    async def test_calendar_event_shows_in_month_grid(self, events_db, events_client):
        """An event on a specific date should appear in the month grid cell."""
        db = events_db
        evt = _make_event(
            db,
            name="Grid Test Race",
            slug="grid-test-race-2026-09-12",
            start=datetime(2026, 9, 12, 9, 0),
            etype="race",
        )
        try:
            r = await events_client.get("/calendar?view=month&y=2026&m=9")
            assert r.status_code == 200
            assert "Grid Test Race" in r.text
        finally:
            db.delete(evt)
            db.commit()

    @pytest.mark.asyncio
    async def test_calendar_type_filter(self, events_db, events_client):
        db = events_db
        race = _make_event(
            db,
            name="Cal Filter Race",
            slug="cal-filter-race-2026-10-01",
            start=_NOW + timedelta(days=80),
            etype="race",
        )
        practice = _make_event(
            db,
            name="Cal Filter Practice",
            slug="cal-filter-practice-2026-10-02",
            start=_NOW + timedelta(days=81),
            etype="practice",
        )
        try:
            r = await events_client.get("/calendar?view=agenda&type=race")
            assert r.status_code == 200
            assert "Cal Filter Race" in r.text
            assert "Cal Filter Practice" not in r.text
        finally:
            db.delete(race)
            db.delete(practice)
            db.commit()


# ── Event list page tests ──────────────────────────────────────────────


class TestEventListPage:
    @pytest.fixture(autouse=True, scope="class")
    def seed(self, events_db):
        db = events_db
        self.future_event = _make_event(
            db,
            name="List Future Race",
            slug="list-future-race-2026-09-01",
            start=_NOW + timedelta(days=47),
            etype="race",
            distance=1.0,
            distance_unit="miles",
            location_name="Hite Park",
        )
        self.past_event = _make_event(
            db,
            name="List Past Practice",
            slug="list-past-practice-2026-05-01",
            start=_NOW - timedelta(days=75),
            etype="practice",
            status="completed",
        )
        self.past_race_2mi = _make_event(
            db,
            name="List Past 2mi Race",
            slug="list-past-race-2mi-2026-04-01",
            start=_NOW - timedelta(days=105),
            etype="race",
            status="completed",
            distance=2.0,
            distance_unit="miles",
        )
        yield
        for evt in [self.future_event, self.past_event, self.past_race_2mi]:
            db.delete(evt)
        db.commit()

    @pytest.mark.asyncio
    async def test_event_list_renders(self, events_client):
        r = await events_client.get("/events")
        assert r.status_code == 200
        assert "Events" in r.text

    @pytest.mark.asyncio
    async def test_event_list_shows_upcoming_section(self, events_client):
        r = await events_client.get("/events")
        assert "List Future Race" in r.text

    @pytest.mark.asyncio
    async def test_event_list_shows_past_section(self, events_client):
        r = await events_client.get("/events")
        assert "List Past Practice" in r.text

    @pytest.mark.asyncio
    async def test_event_list_type_filter(self, events_client):
        r = await events_client.get("/events?type=practice")
        assert r.status_code == 200
        assert "List Past Practice" in r.text
        assert "List Future Race" not in r.text

    @pytest.mark.asyncio
    async def test_event_list_distance_filter(self, events_client):
        r = await events_client.get("/events?distance=1+miles")
        assert r.status_code == 200
        assert "List Future Race" in r.text
        assert "List Past Practice" not in r.text

    @pytest.mark.asyncio
    async def test_event_list_distance_filter_2mi(self, events_client):
        r = await events_client.get("/events?distance=2+miles")
        assert r.status_code == 200
        assert "List Past 2mi Race" in r.text
        assert "List Future Race" not in r.text


# ── Event detail page tests ────────────────────────────────────────────


class TestEventDetail:
    @pytest.fixture(autouse=True, scope="class")
    def seed(self, events_db):
        db = events_db
        # Upcoming event
        self.upcoming_evt = _make_event(
            db,
            name="Detail Upcoming Race",
            slug="detail-upcoming-race-2026-09-15",
            start=_NOW + timedelta(days=62),
            etype="race",
            distance=1.5,
            distance_unit="miles",
            location_name="Hite Elementary",
            street_address="123 School Rd, Louisville KY",
            description="Wear your bib numbers!",
        )
        # Completed event with results
        self.completed_evt = _make_event(
            db,
            name="Detail Completed Race",
            slug="detail-completed-race-2026-06-10",
            start=_NOW - timedelta(days=35),
            etype="race",
            status="completed",
        )
        # Cancelled event
        self.cancelled_evt = _make_event(
            db,
            name="Detail Cancelled Race",
            slug="detail-cancelled-race-2026-07-01",
            start=_NOW + timedelta(days=14),
            etype="race",
            status="cancelled",
        )
        # Postponed event
        self.postponed_evt = _make_event(
            db,
            name="Detail Postponed Race",
            slug="detail-postponed-race-2026-07-20",
            start=_NOW + timedelta(days=33),
            etype="race",
            status="postponed",
        )
        # Students for results
        self.s1 = _make_student(db, first="Alice", last="Alpha", slug="alice-alpha-det")
        self.s2 = _make_student(db, first="Bob", last="Beta", slug="bob-beta-det")
        self.s3 = _make_student(db, first="Carl", last="Gamma", slug="carl-gamma-det")
        # Results: Alice fastest (500s), Bob middle (520s), Carl DNF
        self.r1 = _make_result(db, student_id=self.s1.id, event_id=self.completed_evt.id, time_seconds=500, placement=1)
        self.r2 = _make_result(db, student_id=self.s2.id, event_id=self.completed_evt.id, time_seconds=520, placement=2)
        self.r3 = _make_result(db, student_id=self.s3.id, event_id=self.completed_evt.id, time_seconds=None, status="did_not_finish")
        yield
        for obj in [self.r1, self.r2, self.r3, self.s1, self.s2, self.s3,
                    self.upcoming_evt, self.completed_evt,
                    self.cancelled_evt, self.postponed_evt]:
            db.delete(obj)
        db.commit()

    @pytest.mark.asyncio
    async def test_event_detail_404_for_unknown_slug(self, events_client):
        r = await events_client.get("/events/totally-nonexistent-event-2099-01-01")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_upcoming_event_detail_renders(self, events_client):
        r = await events_client.get("/events/detail-upcoming-race-2026-09-15")
        assert r.status_code == 200
        assert "Detail Upcoming Race" in r.text

    @pytest.mark.asyncio
    async def test_upcoming_event_shows_location(self, events_client):
        r = await events_client.get("/events/detail-upcoming-race-2026-09-15")
        assert "Hite Elementary" in r.text
        assert "123 School Rd" in r.text

    @pytest.mark.asyncio
    async def test_upcoming_event_shows_map_link(self, events_client):
        r = await events_client.get("/events/detail-upcoming-race-2026-09-15")
        assert "maps.google.com" in r.text or "google.com/maps" in r.text

    @pytest.mark.asyncio
    async def test_upcoming_event_shows_description(self, events_client):
        r = await events_client.get("/events/detail-upcoming-race-2026-09-15")
        assert "Wear your bib numbers!" in r.text

    @pytest.mark.asyncio
    async def test_completed_event_shows_results(self, events_client):
        r = await events_client.get("/events/detail-completed-race-2026-06-10")
        assert r.status_code == 200
        assert "Alice" in r.text
        assert "Bob" in r.text

    @pytest.mark.asyncio
    async def test_results_sorted_fastest_first(self, events_client):
        """Alice (500s = 8:20) should appear before Bob (520s = 8:40)."""
        r = await events_client.get("/events/detail-completed-race-2026-06-10")
        alice_pos = r.text.find("Alice")
        bob_pos = r.text.find("Bob")
        assert alice_pos < bob_pos, "Alice (faster) should appear before Bob"

    @pytest.mark.asyncio
    async def test_results_formatted_as_mmss(self, events_client):
        r = await events_client.get("/events/detail-completed-race-2026-06-10")
        # 500 seconds = 8:20, 520 seconds = 8:40
        assert "8:20" in r.text
        assert "8:40" in r.text

    @pytest.mark.asyncio
    async def test_dnf_result_listed_after_completed(self, events_client):
        """Carl (DNF) should appear after the completed results."""
        r = await events_client.get("/events/detail-completed-race-2026-06-10")
        alice_pos = r.text.find("Alice")
        carl_pos = r.text.find("Carl")
        assert alice_pos < carl_pos, "Completed results should precede DNF"

    @pytest.mark.asyncio
    async def test_dnf_label_shown(self, events_client):
        r = await events_client.get("/events/detail-completed-race-2026-06-10")
        assert "DNF" in r.text

    @pytest.mark.asyncio
    async def test_student_names_link_to_student_pages(self, events_client):
        r = await events_client.get("/events/detail-completed-race-2026-06-10")
        # Links should use student slugs
        assert "/students/alice-alpha-det" in r.text
        assert "/students/bob-beta-det" in r.text

    @pytest.mark.asyncio
    async def test_cancelled_event_shows_cancellation_notice(self, events_client):
        r = await events_client.get("/events/detail-cancelled-race-2026-07-01")
        assert r.status_code == 200
        # Should show the cancellation notice
        assert "cancelled" in r.text.lower()
        assert "This event has been cancelled" in r.text

    @pytest.mark.asyncio
    async def test_postponed_event_shows_postponed_notice(self, events_client):
        r = await events_client.get("/events/detail-postponed-race-2026-07-20")
        assert r.status_code == 200
        assert "postponed" in r.text.lower()

    @pytest.mark.asyncio
    async def test_completed_event_no_results_empty_state(self, events_db, events_client):
        db = events_db
        evt = _make_event(
            db,
            name="Empty Results Event",
            slug="empty-results-event-2026-05-01",
            start=_NOW - timedelta(days=70),
            etype="race",
            status="completed",
        )
        try:
            r = await events_client.get("/events/empty-results-event-2026-05-01")
            assert r.status_code == 200
            assert "Results have not been entered" in r.text
        finally:
            db.delete(evt)
            db.commit()


# ── Util helper tests ─────────────────────────────────────────────────


def test_event_cutoff_dt_uses_end_when_set():
    from datetime import datetime
    from app.util import event_cutoff_dt

    class FakeEvent:
        start_datetime = datetime(2026, 8, 1, 9, 0)
        end_datetime = datetime(2026, 8, 1, 11, 0)

    assert event_cutoff_dt(FakeEvent()) == datetime(2026, 8, 1, 11, 0)


def test_event_cutoff_dt_uses_start_when_no_end():
    from datetime import datetime
    from app.util import event_cutoff_dt

    class FakeEvent:
        start_datetime = datetime(2026, 8, 1, 9, 0)
        end_datetime = None

    assert event_cutoff_dt(FakeEvent()) == datetime(2026, 8, 1, 9, 0)


def test_prev_month_normal():
    from app.util import prev_month

    assert prev_month(2026, 6) == (2026, 5)
    assert prev_month(2026, 3) == (2026, 2)


def test_prev_month_january_wraps():
    from app.util import prev_month

    assert prev_month(2026, 1) == (2025, 12)


def test_next_month_normal():
    from app.util import next_month

    assert next_month(2026, 6) == (2026, 7)
    assert next_month(2026, 11) == (2026, 12)


def test_next_month_december_wraps():
    from app.util import next_month

    assert next_month(2026, 12) == (2027, 1)


def test_month_name():
    from app.util import month_name

    assert month_name(1) == "January"
    assert month_name(8) == "August"
    assert month_name(12) == "December"


def test_build_month_grid_structure():
    from datetime import datetime
    from app.util import build_month_grid

    # August 2026 — no events
    grid = build_month_grid(2026, 8, [])
    # Should be a list of weeks
    assert isinstance(grid, list)
    assert len(grid) >= 4
    for week in grid:
        assert len(week) == 7  # Mon–Sun
        for day, events in week:
            assert isinstance(day, int)
            assert isinstance(events, list)


def test_build_month_grid_places_events():
    from datetime import datetime
    from app.util import build_month_grid

    class FakeEvt:
        def __init__(self, day):
            self.start_datetime = datetime(2026, 8, day, 9, 0)

    events = [FakeEvt(5), FakeEvt(20)]
    grid = build_month_grid(2026, 8, events)

    # Flatten grid and find day 5 and day 20
    flat = {d: evts for week in grid for (d, evts) in week if d != 0}
    assert len(flat[5]) == 1
    assert len(flat[20]) == 1


def test_build_month_grid_excludes_other_months():
    from datetime import datetime
    from app.util import build_month_grid

    class FakeEvt:
        def __init__(self, year, month, day):
            self.start_datetime = datetime(year, month, day, 9, 0)

    events = [FakeEvt(2026, 7, 15), FakeEvt(2026, 9, 1)]  # neither in August
    grid = build_month_grid(2026, 8, events)
    flat = {d: evts for week in grid for (d, evts) in week if d != 0}
    for evts in flat.values():
        assert len(evts) == 0
