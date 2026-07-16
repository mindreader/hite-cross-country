"""
Tests for app/backup.py — snapshot logic.

These tests operate on real (temporary) SQLite files to ensure VACUUM INTO
produces a valid database and that the stale-tmp cleanup path works.
The backup worker itself is disabled in conftest.py via HITE_SNAPSHOT_INTERVAL_SECS=0.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(path: Path) -> None:
    """Create a minimal SQLite DB at *path* for testing."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items (name) VALUES ('hello')")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_snapshot_produces_valid_sqlite_db(tmp_path: Path) -> None:
    """run_snapshot must produce a readable SQLite file at the snapshot path."""
    from app.backup import run_snapshot

    src = tmp_path / "source.db"
    dst = tmp_path / "snapshots" / "hite.db"

    _make_db(src)

    # Snapshot path doesn't exist yet — the function must create the directory
    run_snapshot(db_path=str(src), snapshot_path=str(dst))

    assert dst.exists(), "snapshot file was not created"

    # Verify it's a readable SQLite database with the correct content
    conn = sqlite3.connect(str(dst))
    rows = conn.execute("SELECT name FROM items").fetchall()
    conn.close()

    assert rows == [("hello",)], f"unexpected rows in snapshot: {rows}"


def test_snapshot_replaces_stale_tmp(tmp_path: Path) -> None:
    """A leftover .tmp file from a previous failed run must be cleaned up."""
    from app.backup import run_snapshot

    src = tmp_path / "source.db"
    dst = tmp_path / "snapshots" / "hite.db"
    tmp_file = dst.parent / f".{dst.name}.tmp"

    _make_db(src)
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Plant a stale tmp file
    tmp_file.write_text("not a real sqlite file")
    assert tmp_file.exists()

    run_snapshot(db_path=str(src), snapshot_path=str(dst))

    # The real snapshot should exist and the stale tmp must be gone
    assert dst.exists(), "snapshot file was not created"
    assert not tmp_file.exists(), "stale tmp was not removed"

    # Verify it's a valid SQLite DB
    conn = sqlite3.connect(str(dst))
    rows = conn.execute("SELECT name FROM items").fetchall()
    conn.close()
    assert rows == [("hello",)]


def test_snapshot_overwrites_previous(tmp_path: Path) -> None:
    """A second snapshot must atomically replace the first."""
    from app.backup import run_snapshot

    src = tmp_path / "source.db"
    dst = tmp_path / "snapshots" / "hite.db"

    _make_db(src)
    run_snapshot(db_path=str(src), snapshot_path=str(dst))

    # Mutate the source and snapshot again
    conn = sqlite3.connect(str(src))
    conn.execute("INSERT INTO items (name) VALUES ('world')")
    conn.commit()
    conn.close()

    run_snapshot(db_path=str(src), snapshot_path=str(dst))

    conn = sqlite3.connect(str(dst))
    names = [r[0] for r in conn.execute("SELECT name FROM items ORDER BY id").fetchall()]
    conn.close()
    assert names == ["hello", "world"], f"unexpected content after second snapshot: {names}"


def test_snapshot_creates_parent_dirs(tmp_path: Path) -> None:
    """run_snapshot must create deeply nested snapshot directories."""
    from app.backup import run_snapshot

    src = tmp_path / "source.db"
    dst = tmp_path / "a" / "b" / "c" / "snap.db"

    _make_db(src)
    run_snapshot(db_path=str(src), snapshot_path=str(dst))

    assert dst.exists()
