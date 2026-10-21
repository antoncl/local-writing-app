#!/usr/bin/env python3
"""The frontend fitness guards, run in ONE interpreter — for the in-session
PostToolUse hook only (#2598).

The hook runs on every edit, and its wall-clock is on the session's hot path
(see `.claude/hooks/check_edited_file.py`). Spawning one Python process per
guard for the same `.ts`/`.svelte` file paid an interpreter start per guard;
this runner pays one. Each guard keeps its own script, selection rule and exit
code: pre-commit and CI call them separately, so a failure names its guard.

Exit 1 if any guard fails; every guard runs either way, so one edit reports
all its findings.

Usage:
    python scripts/check_frontend_guards.py <file> [<file> ...]
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
GUARDS = ("check_http_client", "check_ai_call_flush")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_frontend_guard_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    failed = 0
    for name in GUARDS:
        failed |= _load(name).main(argv)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
