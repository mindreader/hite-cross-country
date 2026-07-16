"""
Smoke tests for the Hite XC scaffold.

These verify the skeleton boots correctly, routes exist, auth gates work,
and utility helpers round-trip properly.
"""

from __future__ import annotations

import pytest


# ── App boot & healthz ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_healthz_returns_200(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_robots_header_on_every_response(client):
    r = await client.get("/healthz")
    assert "noindex" in r.headers.get("x-robots-tag", "")


# ── Public routes exist ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_home_page(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "Hite Elementary" in r.text


@pytest.mark.asyncio
async def test_students_page(client):
    r = await client.get("/students")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_student_detail_page(client):
    r = await client.get("/students/robert-watson")
    assert r.status_code == 200


# ── Event routes exist ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_events_page(client):
    r = await client.get("/events")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_event_detail_page(client):
    r = await client.get("/events/some-event-2026-01-01")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_upcoming_page(client):
    r = await client.get("/upcoming")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_calendar_page(client):
    r = await client.get("/calendar")
    assert r.status_code == 200


# ── Coach auth: login required ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_coach_dashboard_redirects_to_login(client):
    r = await client.get("/coach", follow_redirects=False)
    # Should be a 303 redirect to /coach/login
    assert r.status_code == 303
    assert "/coach/login" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_coach_students_requires_auth(client):
    r = await client.get("/coach/students", follow_redirects=False)
    assert r.status_code == 303


@pytest.mark.asyncio
async def test_coach_events_requires_auth(client):
    r = await client.get("/coach/events", follow_redirects=False)
    assert r.status_code == 303


@pytest.mark.asyncio
async def test_login_form_renders(client):
    r = await client.get("/coach/login")
    assert r.status_code == 200
    assert "password" in r.text.lower()


@pytest.mark.asyncio
async def test_login_with_bad_password(client):
    r = await client.post(
        "/coach/login",
        data={"password": "wrong"},
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_with_dev_password(client):
    r = await client.post(
        "/coach/login",
        data={"password": "devcoach"},
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/coach" in r.headers.get("location", "")
    assert "hite_session" in r.headers.get("set-cookie", "")


# ── Utility: seconds ↔ MM:SS round-trip ────────────────────────────────


def test_seconds_to_mmss():
    from app.util import seconds_to_mmss
    assert seconds_to_mmss(540) == "9:00"
    assert seconds_to_mmss(605) == "10:05"
    assert seconds_to_mmss(510) == "8:30"
    assert seconds_to_mmss(0) == "0:00"
    assert seconds_to_mmss(None) == ""


def test_mmss_to_seconds():
    from app.util import mmss_to_seconds
    assert mmss_to_seconds("9:00") == 540
    assert mmss_to_seconds("10:05") == 605
    assert mmss_to_seconds("8:30") == 510
    assert mmss_to_seconds("0:00") == 0


def test_seconds_round_trip():
    from app.util import seconds_to_mmss, mmss_to_seconds
    for secs in [0, 59, 60, 120, 540, 605, 999]:
        assert mmss_to_seconds(seconds_to_mmss(secs)) == secs


def test_mmss_rejects_bad_input():
    from app.util import mmss_to_seconds
    with pytest.raises(ValueError):
        mmss_to_seconds("abc")
    with pytest.raises(ValueError):
        mmss_to_seconds("9:60")


# ── Utility: slug generation ───────────────────────────────────────────


def test_student_slug():
    from app.util import student_slug
    assert student_slug("Robert", "Watson") == "robert-watson"
    assert student_slug("Jane", "Smith") == "jane-smith"


def test_event_slug():
    from datetime import datetime
    from app.util import event_slug
    dt = datetime(2026, 8, 30, 9, 0)
    assert event_slug("Hite Invitational", dt) == "hite-invitational-2026-08-30"


# ── Utility: display name ─────────────────────────────────────────────


def test_public_display_name():
    from app.util import public_display_name
    assert public_display_name("Robert", "Watson") == "Robert W."
    assert public_display_name("Jane", "Smith") == "Jane S."


# ── Utility: is_upcoming / is_past ─────────────────────────────────────


def test_is_upcoming_and_past():
    from datetime import timedelta
    from app.util import is_upcoming, is_past, now_local

    future = now_local() + timedelta(days=1)
    past = now_local() - timedelta(days=1)

    assert is_upcoming(future) is True
    assert is_past(future) is False
    assert is_upcoming(past) is False
    assert is_past(past) is True
