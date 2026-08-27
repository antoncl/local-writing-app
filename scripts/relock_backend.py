#!/usr/bin/env python3
"""Regenerate backend/requirements.lock from backend/pyproject.toml (#1393).

`pyproject.toml` declares dependency *intent* (floors, and caps where a line is
deliberately held back); the versions every install actually gets come from
`backend/requirements.lock`. This script is the one place that knows how the
lock is produced, so regenerating it is a deliberate, repeatable act rather
than an incantation.

Why `uv pip compile --universal` and not pip-tools or a plain freeze: the same
lock must install on the dev machine (Windows), the CI gates (ubuntu, and a
Windows pytest job), and the release freeze matrix (Windows/ubuntu/mac, and a
different Python minor). A freeze or a pip-tools compile captures *one*
platform's resolve — it would hard-pin Windows-only wheels like `colorama` and
miss POSIX-only ones like `uvloop` (pulled in by `uvicorn[standard]` on
non-Windows). Universal mode emits one file with environment markers that
resolves correctly on all of them, and the output is a plain requirements.txt
that vanilla pip installs — only *this script* needs uv.

By default a relock is minimal: pins already in the lock are kept if they
still satisfy `pyproject.toml`, so editing one dependency does not drag the
whole graph forward. Moving everything to current is `--upgrade`; moving one
package is `--upgrade-package NAME` (repeatable). Either way, the full gates
on the resulting diff are what validate the new set.

Usage (any Python 3.11+ with `uv` installed — `pip install uv`):
    python scripts/relock_backend.py [--upgrade] [--upgrade-package NAME]...
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
LOCK_NAME = "requirements.lock"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="resolve the whole graph to current versions instead of keeping existing pins",
    )
    parser.add_argument(
        "--upgrade-package",
        action="append",
        default=[],
        metavar="NAME",
        help="resolve one package (and what it forces) to current; repeatable",
    )
    args = parser.parse_args()

    probe = subprocess.run(
        [sys.executable, "-m", "uv", "--version"], capture_output=True, text=True
    )
    if probe.returncode != 0:
        print("uv is not importable from this interpreter.", file=sys.stderr)
        print(f"Install it first:  {sys.executable} -m pip install uv", file=sys.stderr)
        return 1

    cmd = [
        sys.executable,
        "-m",
        "uv",
        "pip",
        "compile",
        "pyproject.toml",
        # One lock for every environment — see the module docstring.
        "--universal",
        # One superset lock: dev tools and the PyInstaller build extra ride
        # along. PyInstaller bundles what the app imports, not what the venv
        # holds, so the extras never reach the shipped artifact.
        "--extra",
        "dev",
        "--extra",
        "build",
        "--output-file",
        LOCK_NAME,
        # The lock's header should tell a reader how to regenerate it, not
        # which uv flags happened to produce it.
        "--custom-compile-command",
        "python scripts/relock_backend.py",
    ]
    if args.upgrade:
        cmd.append("--upgrade")
    for name in args.upgrade_package:
        cmd.extend(["--upgrade-package", name])

    # cwd=backend so the lock's self-references ("via pyproject.toml") stay
    # relative and the file lands next to the pyproject it was compiled from.
    result = subprocess.run(cmd, cwd=BACKEND)
    if result.returncode == 0:
        print(f"Wrote {BACKEND / LOCK_NAME}")
        print("Now sync your venv and run the gates:")
        print(f"  backend/.venv/Scripts/python -m pip install -r backend/{LOCK_NAME}")
        print("  backend/.venv/Scripts/python -m pip install -e backend --no-deps")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
