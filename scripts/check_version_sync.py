#!/usr/bin/env python3
"""Version-sync gate — the backend and frontend release versions must agree.

The app ships as two packages that each legitimately own their version literal:
`backend/pyproject.toml` (`[project].version`) and `frontend/package.json`
(`version`). They are released together, so a bump must move both. Nothing else
enforces that: bump one, forget the other, and the two halves report different
versions with no gate to catch it.

This holds the two literals equal. It is the whole anti-drift story for the app
version now that `backend/app/main.py` derives its `FastAPI(version=...)` from
package metadata instead of hand-copying it (#1299) — one backend literal, one
frontend literal, held equal here.

Whole-invariant check over two fixed files, so it ignores any argv (safe to hand
the staged list from pre-commit) and reads the files directly. Sanity guards
fail loud if either version is missing or unparseable, so a broken read can't
pass vacuously.

FAILS (exit 1) on a mismatch or an unreadable version.

Usage:
    python scripts/check_version_sync.py
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = _ROOT / "backend" / "pyproject.toml"
PACKAGE_JSON = _ROOT / "frontend" / "package.json"


def _backend_version() -> str | None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    return version if isinstance(version, str) and version else None


def _frontend_version() -> str | None:
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    version = data.get("version")
    return version if isinstance(version, str) and version else None


def main() -> int:
    backend = _backend_version()
    frontend = _frontend_version()

    problems: list[str] = []
    if backend is None:
        problems.append(f"could not read [project].version from {PYPROJECT.as_posix()}")
    if frontend is None:
        problems.append(f"could not read version from {PACKAGE_JSON.as_posix()}")
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        print("The version-sync gate cannot verify an unreadable version.")
        return 1

    if backend != frontend:
        print(f"FAIL  version mismatch: backend {backend!r} != frontend {frontend!r}")
        print(
            "Bump both together: backend/pyproject.toml [project].version and "
            "frontend/package.json version (then regenerate package-lock.json)."
        )
        return 1

    print(f"ok    backend and frontend agree at {backend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
