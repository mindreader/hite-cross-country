# Deployment contract

This repo is just the application. It is deliberately infrastructure-agnostic:
no cluster names, registries, node names, or operator tooling live here.
Whatever deploys it (k8s, compose, bare systemd) only needs to honor the
contract below.

## Container

- `Dockerfile` builds a non-root image (uid 1000) running a single uvicorn
  worker on port **8000**.
- SQLite is single-writer: run **exactly one replica** and use a
  Recreate-style update strategy (never two pods on the same database file).

## Environment

| Variable | Required | Meaning |
|---|---|---|
| `HITE_DB_PATH` | yes | Path of the SQLite database (persistent volume). |
| `HITE_COACH_PASSWORD_HASH` | yes | bcrypt hash of the coach password. |
| `HITE_SESSION_SECRET` | yes | ≥32 bytes of randomness for session cookies. |
| `HITE_SNAPSHOT_PATH` | no | Where the in-app snapshotter writes consistent copies. Snapshotting disabled if unset. |
| `HITE_SNAPSHOT_INTERVAL_SECS` | no | Snapshot cadence (default 3600). |

Generate values:

```sh
python -c "import bcrypt; print(bcrypt.hashpw(b'PASSWORD', bcrypt.gensalt()).decode())"
python -c "import secrets; print(secrets.token_hex(32))"
```

## Storage

Mount a persistent volume covering `HITE_DB_PATH` (and `HITE_SNAPSHOT_PATH`,
usually a subdirectory). The database is tiny (<1 GiB is generous). The app
creates the schema on first start; seed demo data with `python -m app.seed`.

## Health

`GET /healthz` returns 200 when the app and database are usable — suitable
for liveness and readiness probes.

## Backups

With `HITE_SNAPSHOT_PATH` set, a background worker periodically writes an
application-consistent snapshot via SQLite `VACUUM INTO` (atomic replace,
plus one immediately at startup). External tooling can copy that file at any
moment without coordination — it is never mid-write. Verify a pulled copy
with `sqlite3 file 'PRAGMA integrity_check;'`.

## Resource footprint

Comfortable at 64Mi memory request / 128Mi limit and a small CPU share;
it is a low-traffic school site.

## Privacy posture

- All responses carry `X-Robots-Tag: noindex` and pages include the robots
  meta tag — do not undo this at the proxy layer.
- Students are displayed as first name + last initial only.
- The public side is intentionally unauthenticated; only `/coach` is
  password-protected.
