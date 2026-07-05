#!/usr/bin/env python3
"""Claude Code PostToolUse hook — the in-session half of the quality gates.

Reads the PostToolUse event JSON on stdin, pulls the path of the file just
edited (`tool_input.file_path`), runs the relevant fast checks on it, and
prints any violation to stdout. PostToolUse semantics: text on stdout with
exit 0 is injected into the model's context as a reminder, so it sees the
problem and fixes it before finishing. (Exit 2 would hard-block, but the edit
has already happened, so exit 0 + stdout is the right channel here.)

Checks:
  * file-size guard  — every source file (scripts/check_file_size.py)
  * style-token guard — frontend style code (scripts/check_style_tokens.py)
  * ruff             — Python files only, via the backend venv where it lives

Always exits 0; a broken hook must never wedge the session.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SIZE_GUARD = REPO / "scripts" / "check_file_size.py"
STYLE_GUARD = REPO / "scripts" / "check_style_tokens.py"
# Advisory complexity rules — flagged, never blocking, while the existing count
# is burned down (see backend/pyproject.toml for thresholds).
COMPLEXITY_RULES = "PLR0912,PLR0913,PLR0915,C901"

# Resolve the backend venv via the shared helper so a git worktree (which has
# no local .venv) falls back to the primary worktree's — otherwise the ruff
# gate would silently skip here (issue #135). Import defensively: a broken hook
# must never wedge the session.
try:
    sys.path.insert(0, str(REPO / "scripts"))
    from venv_python import find_venv_python

    VENV_PYTHON = find_venv_python(REPO)
except Exception:
    VENV_PYTHON = None


def edited_path() -> Path | None:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return None
    raw = (event.get("tool_input") or {}).get("file_path")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    except Exception as exc:  # never wedge the session on a tooling hiccup
        return 0, f"(skipped: {exc})"
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def main() -> int:
    path = edited_path()
    if path is None:
        return 0

    messages: list[str] = []

    if SIZE_GUARD.is_file():
        _, out = run([sys.executable, str(SIZE_GUARD), str(path)])
        if out:
            messages.append(out)

    if path.suffix in {".svelte", ".css"} and STYLE_GUARD.is_file():
        _, out = run([sys.executable, str(STYLE_GUARD), str(path)])
        if out:
            messages.append(out)

    if path.suffix == ".py" and VENV_PYTHON is not None:
        code, out = run([str(VENV_PYTHON), "-m", "ruff", "check", str(path)])
        if code != 0 and out:
            messages.append("ruff:\n" + out)
        # advisory: complexity hints (non-blocking — the hook always exits 0)
        ccode, cout = run(
            [str(VENV_PYTHON), "-m", "ruff", "check", "--no-cache", "--select", COMPLEXITY_RULES, str(path)]
        )
        if ccode != 0 and cout:
            messages.append("complexity (advisory - consider simplifying):\n" + cout)

    if messages:
        print("Quality gate on the file you just edited:")
        print("\n".join(messages))
        print("Please address the above before finishing this task.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
