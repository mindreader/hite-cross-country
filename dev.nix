# Local development shell for the Hite XC website.
#
#   nix-shell dev.nix          # drop into a shell with everything on PATH
#   hite-seed                  # create + seed ./data/hite.db (guarded; --force to reseed)
#   hite-dev                   # run the site at http://127.0.0.1:8000 (auto-reload)
#   pytest                     # run the test suite
#
# No venv, no pip: all dependencies come from nixpkgs' python312Packages.
# Coach login in dev mode (no HITE_COACH_PASSWORD_HASH set) is password
# "devcoach" — the app logs a loud warning to that effect.

{ pkgs ? import <nixpkgs> { } }:

let
  python = pkgs.python312.withPackages (ps: with ps; [
    # runtime (mirrors pyproject.toml [project.dependencies])
    fastapi
    uvicorn
    sqlalchemy
    jinja2
    python-multipart
    itsdangerous
    bcrypt
    python-dateutil

    # dev/test (mirrors [project.optional-dependencies].dev)
    pytest
    httpx
    pytest-asyncio
  ]);

  hite-dev = pkgs.writeShellScriptBin "hite-dev" ''
    set -euo pipefail
    cd "$(git rev-parse --show-toplevel)"
    [ -f "''${HITE_DB_PATH:-data/hite.db}" ] || {
      echo "no database yet — seeding sample data first"; python scripts/seed.py; }
    exec python -m uvicorn app.main:app --reload --host 127.0.0.1 --port "''${PORT:-8000}"
  '';

  hite-seed = pkgs.writeShellScriptBin "hite-seed" ''
    set -euo pipefail
    cd "$(git rev-parse --show-toplevel)"
    exec python scripts/seed.py "$@"
  '';

in pkgs.mkShell {
  buildInputs = [
    python
    hite-dev
    hite-seed
    pkgs.sqlite # handy for poking at data/hite.db
  ];

  shellHook = ''
    export PYTHONPATH="$(git rev-parse --show-toplevel):''${PYTHONPATH:-}"
    echo "hite dev shell — commands: hite-seed | hite-dev | pytest"
  '';
}
