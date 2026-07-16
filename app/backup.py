"""
Periodic SQLite snapshot via VACUUM INTO.

Background thread that runs every HITE_SNAPSHOT_INTERVAL_SECS seconds
(default 3600, set to 0 to disable).  The snapshot is written atomically:
  1. VACUUM INTO <snapshot_dir>/.hite.db.tmp
  2. os.replace(<tmp>, <snapshot_path>)

The puller side (ops/backup/) kubectl-exec's `cat` of HITE_SNAPSHOT_PATH;
no HTTP endpoint is needed here.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────

_SNAPSHOT_INTERVAL_SECS: int = int(os.environ.get("HITE_SNAPSHOT_INTERVAL_SECS", "3600"))
_SNAPSHOT_PATH: str = os.environ.get("HITE_SNAPSHOT_PATH", "/data/snapshots/hite.db")
_DB_PATH: str = os.environ.get("HITE_DB_PATH", "./data/hite.db")


# ── Core snapshot logic ────────────────────────────────────────────────────


def run_snapshot(db_path: str | None = None, snapshot_path: str | None = None) -> None:
    """Run a single VACUUM INTO snapshot (atomic: tmp → rename)."""
    src = db_path or _DB_PATH
    dst = Path(snapshot_path or _SNAPSHOT_PATH)
    tmp = dst.parent / f".{dst.name}.tmp"

    dst.parent.mkdir(parents=True, exist_ok=True)

    # Remove any stale tmp from a previous failed run
    if tmp.exists():
        try:
            tmp.unlink()
            log.debug("Removed stale snapshot tmp: %s", tmp)
        except OSError as exc:
            log.warning("Could not remove stale tmp %s: %s", tmp, exc)

    log.info("Starting snapshot: %s → %s", src, dst)
    try:
        conn = sqlite3.connect(src)
        try:
            conn.execute(f"VACUUM INTO '{tmp}'")
        finally:
            conn.close()

        os.replace(tmp, dst)
        log.info("Snapshot complete: %s", dst)
    except Exception as exc:
        log.error("Snapshot failed: %s", exc)
        # Clean up failed tmp if it was created
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


# ── Background thread ─────────────────────────────────────────────────────


class SnapshotWorker(threading.Thread):
    """Daemon thread that fires run_snapshot() every _interval seconds."""

    def __init__(self, interval: int) -> None:
        super().__init__(name="snapshot-worker", daemon=True)
        self._interval = interval
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        log.info(
            "Snapshot worker started — interval %ds, path %s",
            self._interval,
            _SNAPSHOT_PATH,
        )
        while not self._stop_event.wait(self._interval):
            try:
                run_snapshot()
            except Exception:
                # Logged inside run_snapshot; don't crash the worker
                pass

        log.info("Snapshot worker stopped.")


# Module-level singleton so start/stop can be called from lifespan
_worker: SnapshotWorker | None = None


def start_snapshot_worker() -> None:
    """Start the background snapshot worker. No-op if interval == 0."""
    global _worker
    if _SNAPSHOT_INTERVAL_SECS == 0:
        log.info("HITE_SNAPSHOT_INTERVAL_SECS=0 — snapshot worker disabled.")
        return
    _worker = SnapshotWorker(_SNAPSHOT_INTERVAL_SECS)
    _worker.start()


def stop_snapshot_worker() -> None:
    """Signal the worker to stop (called during app shutdown)."""
    global _worker
    if _worker is not None:
        _worker.stop()
        _worker = None
