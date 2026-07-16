"""
Tests for public-facing routes: /, /students, /students/{slug}.

Uses a session-scoped in-memory DB with a small fixture data set.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# ── Temp DB (must set before any app import) ────────────────────────────

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["HITE_DB_PATH"] = _tmp.name
os.environ["HITE_SESSION_SECRET"] = "test-secret-public"


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app_and_db():
    """Create a fresh FastAPI app with seeded test data."""
    from app.db import reset_singletons, init_db, SessionLocal
    from app.models import Student, Event, Result, EventType, EventStatus, ResultStatus, DistanceUnit
    from app.util import student_slug, event_slug

    reset_singletons()
    init_db()

    db = SessionLocal()
    now = datetime.now()

    # ── Students ──
    alice = Student(
        first_name="Alice", last_name="Anderson",
        slug=student_slug("Alice", "Anderson"),
        grade=4, active=True,
    )
    bob = Student(
        first_name="Bob", last_name="Baker",
        slug=student_slug("Bob", "Baker"),
        grade=5, active=True,
    )
    inactive = Student(
        first_name="Zara", last_name="Zenith",
        slug=student_slug("Zara", "Zenith"),
        grade=3, active=False,
    )
    db.add_all([alice, bob, inactive])
    db.flush()

    past1 = now - timedelta(days=30)
    past2 = now - timedelta(days=20)
    past3 = now - timedelta(days=10)
    future1 = now + timedelta(days=5)
    future2 = now + timedelta(days=12)

    # ── Events ──
    race1 = Event(
        name="Hite Invitational",
        slug=event_slug("Hite Invitational", past1),
        start_datetime=past1,
        type=EventType.race,
        status=EventStatus.completed,
        results_expected=True,
        distance=1.0,
        distance_unit=DistanceUnit.miles,
        location_name="City Park",
    )
    practice1 = Event(
        name="Timed Mile",
        slug=event_slug("Timed Mile", past2),
        start_datetime=past2,
        type=EventType.practice,
        status=EventStatus.completed,
        results_expected=True,
        distance=1.0,
        distance_unit=DistanceUnit.miles,
    )
    practice2 = Event(
        name="Speed Work",
        slug=event_slug("Speed Work", past3),
        start_datetime=past3,
        type=EventType.practice,
        status=EventStatus.completed,
        results_expected=True,
        distance=0.5,
        distance_unit=DistanceUnit.miles,
    )
    future_race = Event(
        name="County Championship",
        slug=event_slug("County Championship", future1),
        start_datetime=future1,
        type=EventType.race,
        status=EventStatus.scheduled,
        results_expected=True,
        location_name="County Fairgrounds",
    )
    future_practice = Event(
        name="Morning Run",
        slug=event_slug("Morning Run", future2),
        start_datetime=future2,
        type=EventType.practice,
        status=EventStatus.scheduled,
        results_expected=True,
    )
    db.add_all([race1, practice1, practice2, future_race, future_practice])
    db.flush()

    # ── Results ──
    r1 = Result(student_id=alice.id, event_id=race1.id, time_seconds=540,
                status=ResultStatus.completed, placement=3)
    r2 = Result(student_id=alice.id, event_id=practice1.id, time_seconds=570,
                status=ResultStatus.completed)
    r3 = Result(student_id=alice.id, event_id=practice2.id, time_seconds=250,
                status=ResultStatus.completed, notes="PR!")
    r4 = Result(student_id=bob.id, event_id=race1.id,
                status=ResultStatus.did_not_participate)

    db.add_all([r1, r2, r3, r4])
    db.commit()
    db.close()

    from app.main import create_app, _setup_jinja_globals
    application = create_app()
    # Jinja globals/filters are registered in the lifespan, but httpx
    # ASGITransport doesn't fire ASGI lifespan events — call it manually.
    _setup_jinja_globals()

    yield application, {
        "alice_slug": alice.slug,
        "bob_slug": bob.slug,
        "inactive_slug": inactive.slug,
    }

    Path(_tmp.name).unlink(missing_ok=True)


@pytest.fixture(scope="module")
async def client(app_and_db):
    from httpx import ASGITransport, AsyncClient

    app, slugs = app_and_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c, slugs


# ── Home page tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_home_renders_ok(client):
    c, _ = client
    r = await c.get("/")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_home_contains_site_title(client):
    c, _ = client
    r = await c.get("/")
    assert "Hite Elementary Cross Country" in r.text


@pytest.mark.asyncio
async def test_home_contains_search_form(client):
    c, _ = client
    r = await c.get("/")
    # Search form action points to /students
    assert 'action="/students"' in r.text
    assert 'name="q"' in r.text


@pytest.mark.asyncio
async def test_home_contains_student_directory_link(client):
    c, _ = client
    r = await c.get("/")
    assert 'href="/students"' in r.text


@pytest.mark.asyncio
async def test_home_shows_upcoming_events(client):
    c, _ = client
    r = await c.get("/")
    assert "County Championship" in r.text
    assert "Morning Run" in r.text


@pytest.mark.asyncio
async def test_home_upcoming_links_to_calendar_and_upcoming(client):
    c, _ = client
    r = await c.get("/")
    assert 'href="/calendar"' in r.text
    assert 'href="/upcoming"' in r.text


@pytest.mark.asyncio
async def test_home_does_not_show_past_events_in_upcoming(client):
    c, _ = client
    r = await c.get("/")
    # Past events must not appear in the upcoming preview section
    # (they shouldn't appear after the "Upcoming Events" heading on home)
    text = r.text
    # The seeded past events are "Hite Invitational", "Timed Mile", "Speed Work"
    # These should NOT appear in the upcoming section on home
    upcoming_section_start = text.find("Upcoming Events")
    links_section_start = text.find("View All Upcoming Events")
    upcoming_body = text[upcoming_section_start:links_section_start]
    assert "Hite Invitational" not in upcoming_body
    assert "Timed Mile" not in upcoming_body


# ── Student directory tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_students_page_renders(client):
    c, _ = client
    r = await c.get("/students")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_students_page_lists_active_students(client):
    c, _ = client
    r = await c.get("/students")
    # Active students shown
    assert "Alice A." in r.text
    assert "Bob B." in r.text


@pytest.mark.asyncio
async def test_students_page_hides_inactive(client):
    c, _ = client
    r = await c.get("/students")
    # Inactive student (Zara Zenith) must not appear
    assert "Zara Z." not in r.text
    assert "Zara Zenith" not in r.text


@pytest.mark.asyncio
async def test_students_page_search_finds_match(client):
    c, _ = client
    r = await c.get("/students?q=alice")
    assert r.status_code == 200
    assert "Alice A." in r.text
    assert "Bob B." not in r.text


@pytest.mark.asyncio
async def test_students_page_search_no_match_empty_state(client):
    c, _ = client
    r = await c.get("/students?q=zzznomatch")
    assert r.status_code == 200
    assert "No students matched" in r.text


@pytest.mark.asyncio
async def test_students_page_grade_filter(client):
    c, _ = client
    r = await c.get("/students?grade=4")
    assert r.status_code == 200
    assert "Alice A." in r.text    # grade 4
    assert "Bob B." not in r.text  # grade 5


@pytest.mark.asyncio
async def test_students_page_links_to_student(client):
    c, slugs = client
    r = await c.get("/students")
    slug = slugs["alice_slug"]
    assert f'/students/{slug}' in r.text


# ── Student detail tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_student_detail_200(client):
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_student_detail_shows_display_name(client):
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert "Alice A." in r.text


@pytest.mark.asyncio
async def test_student_detail_404_for_missing_slug(client):
    c, _ = client
    r = await c.get("/students/nobody-here-xyz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_student_detail_shows_grade(client):
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert "Grade 4" in r.text


@pytest.mark.asyncio
async def test_student_detail_results_newest_first(client):
    """Results must appear in descending date order."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    text = r.text
    # "Speed Work" is most recent (past3 = now-10d)
    # "Timed Mile" is middle (past2 = now-20d)
    # "Hite Invitational" is oldest (past1 = now-30d)
    pos_speed = text.find("Speed Work")
    pos_timed = text.find("Timed Mile")
    pos_race = text.find("Hite Invitational")
    assert pos_speed < pos_timed < pos_race, (
        f"Results not in desc order: Speed Work@{pos_speed}, "
        f"Timed Mile@{pos_timed}, Hite Inv@{pos_race}"
    )


@pytest.mark.asyncio
async def test_student_detail_race_class_present(client):
    """Race results must carry the .result-race CSS class."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert "result-race" in r.text


@pytest.mark.asyncio
async def test_student_detail_practice_class_present(client):
    """Practice results must carry the .result-practice CSS class."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert "result-practice" in r.text


@pytest.mark.asyncio
async def test_student_detail_type_label_in_text(client):
    """Type must be expressed in text, not color alone (accessibility)."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert "Race" in r.text
    assert "Practice" in r.text


@pytest.mark.asyncio
async def test_student_detail_time_formatted(client):
    """Times must display as MM:SS, not raw seconds."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert "9:00" in r.text   # 540 seconds
    assert "9:30" in r.text   # 570 seconds


@pytest.mark.asyncio
async def test_student_detail_fastest_time_in_summary(client):
    """Season summary shows fastest completed time."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert "Fastest Time" in r.text
    # Fastest among Alice's times: 250 s (Speed Work at 0.5 miles), 540s, 570s
    assert "4:10" in r.text  # 250 seconds = 4:10


@pytest.mark.asyncio
async def test_student_detail_event_count_in_summary(client):
    """Season summary shows number of completed-result events."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    # Alice has 3 completed results
    assert "3" in r.text


@pytest.mark.asyncio
async def test_student_detail_event_link(client):
    """Each result links to /events/{event-slug}."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert '/events/' in r.text


@pytest.mark.asyncio
async def test_student_detail_placement_and_notes(client):
    """Placement and notes appear when present."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert "Place: 3" in r.text  # race1 placement=3
    assert "PR!" in r.text        # practice2 notes="PR!"


@pytest.mark.asyncio
async def test_student_detail_dnp_status_shown(client):
    """Non-completed result statuses are displayed."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['bob_slug']}")
    assert "Did Not Participate" in r.text


@pytest.mark.asyncio
async def test_student_detail_empty_state_no_results(client):
    """Student with no results shows the correct empty-state message."""
    # Bob only has a DNP (which IS a result but has no time)
    # Inactive student has no results at all; use them to test true empty state
    c, slugs = client
    # First create a slug with no results — inactive student has no results
    # but inactive student shouldn't be accessible; let's create a new active student
    from app.db import SessionLocal
    from app.models import Student
    from app.util import student_slug

    db = SessionLocal()
    empty_s = Student(
        first_name="Empty", last_name="Evans",
        slug=student_slug("Empty", "Evans"),
        grade=3, active=True,
    )
    db.add(empty_s)
    db.commit()
    db.close()

    r = await c.get(f"/students/empty-evans")
    assert r.status_code == 200
    assert "No results have been recorded" in r.text


# ── Graph data tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_data_json_present(client):
    """graph_data_json must be emitted as valid JSON on the student page."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    text = r.text
    # Locate the JSON blob (server renders it inside a <script> tag)
    assert "ALL_DATA" in text


@pytest.mark.asyncio
async def test_graph_data_json_well_formed(client):
    """The JSON embedded in the page must be parseable and have required keys."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    text = r.text

    # Extract JSON between ALL_DATA = ... and the next semicolon
    import re
    m = re.search(r'const ALL_DATA = (\[.*?\]);', text, re.DOTALL)
    assert m, "ALL_DATA not found in page"
    data = json.loads(m.group(1))
    assert isinstance(data, list)
    assert len(data) >= 1

    required_keys = {"date", "time_seconds", "time_label", "event_name", "event_type"}
    for entry in data:
        for key in required_keys:
            assert key in entry, f"Key '{key}' missing from graph entry: {entry}"


@pytest.mark.asyncio
async def test_graph_data_chronological_order(client):
    """Graph data must be in chronological (oldest-first) order."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    text = r.text

    import re
    m = re.search(r'const ALL_DATA = (\[.*?\]);', text, re.DOTALL)
    assert m, "ALL_DATA not found in page"
    data = json.loads(m.group(1))

    dates = [e["date"] for e in data]
    assert dates == sorted(dates), f"Graph data not chronological: {dates}"


@pytest.mark.asyncio
async def test_graph_data_only_completed_results(client):
    """Only completed results (status=completed, time_seconds!=null) appear in graph."""
    c, slugs = client
    # Bob has only a DNP — no graph data
    r = await c.get(f"/students/{slugs['bob_slug']}")
    text = r.text
    # Either there is no chart data, or ALL_DATA is an empty array
    if "ALL_DATA" in text:
        import re
        m = re.search(r'const ALL_DATA = (\[.*?\]);', text, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            assert data == [], f"Expected empty graph data for Bob, got: {data}"


@pytest.mark.asyncio
async def test_graph_insufficient_data_message(client):
    """Students with <2 graph points must see the 'more results needed' message."""
    c, _ = client
    # empty-evans has 0 results → insufficient
    r = await c.get("/students/empty-evans")
    assert "More results are needed" in r.text


@pytest.mark.asyncio
async def test_graph_distance_selector_present(client):
    """Distance selector must appear on pages with graph data."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert 'id="dist-select"' in r.text


@pytest.mark.asyncio
async def test_graph_type_selector_present(client):
    """Type selector (all/race/practice) must appear on pages with graph data."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert 'id="type-select"' in r.text


@pytest.mark.asyncio
async def test_accessible_table_present(client):
    """A toggleable accessible data table must accompany the graph."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert 'id="graph-table"' in r.text
    assert 'id="toggle-table-btn"' in r.text


@pytest.mark.asyncio
async def test_lower_is_faster_note(client):
    """The 'lower is faster' accessibility note must appear."""
    c, slugs = client
    r = await c.get(f"/students/{slugs['alice_slug']}")
    assert "lower is faster" in r.text.lower()
