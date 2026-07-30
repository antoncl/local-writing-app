"""Durable, append-only error log — the app's only record that anything failed (#386).

Before this the total durable record of every error the app had ever produced was
zero bytes: a backend `500` went to a console nobody kept and a frontend failure
collapsed into one transient string, erased by the next action. If you were not
watching the screen at that moment, it did not happen.

One plain, timestamped line per error. The root is the *scope* of the failure,
and the log is always ``<root>/errors.log``:

- **project scope** — ``<project-root>/errors.log``, a sibling of ``.cache/``,
  deliberately **not** inside it, because ``.cache/`` is contractually
  always-rebuildable and a log is not.
- **machine scope** (#741) — ``<config-dir>/errors.log``, for failures with no
  project bound (a project-open failure, a landing-screen error). "Per project
  *or* per machine?" resolves to *both*: project when one is open, machine when
  not; the scope is which file the line lands in, not which origin it carries.

Two origins feed either file — ``backend`` (a genuine `500` caught by the request
middleware) and ``browser`` (a runtime failure the UI POSTs to ``/api/log``).
Richer records (level/service/correlation id), retention and any UI surface are
the questions the remaining slice-2 work settles; the node/Vite layer is its own
follow-up. Until then this stays lines, on purpose.

The one invariant: **writing the log must never break the operation it records**
(#386 acceptance). Every failure here is swallowed — a log we could not write is
strictly less bad than an edit lost because logging threw.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

LOG_FILENAME = "errors.log"

# A caught value can carry an empty message (a bare `Error()`, `throw ""`). That
# is still a failure worth a durable line, so it gets a placeholder rather than a
# blank one — the silent-failure class is exactly what this log exists to catch.
_NO_MESSAGE = "(no message)"


def _one_line(value: str) -> str:
    """Collapse any run of whitespace (incl. newlines) so one record is one line.

    A multi-line stack trace must not become many log lines — that would make one
    failure read as several and break `grep`-per-record. Whitespace is squeezed
    to single spaces; nothing else is altered.
    """
    return " ".join(value.split())


def append_error_line(
    root: Path,
    *,
    origin: str,
    message: str,
    detail: str | None = None,
    context: str | None = None,
    level: str = "error",
    ensure_dir: bool = False,
) -> None:
    """Append one timestamped line to ``<root>/errors.log``; never raise.

    Line shape (single physical line)::

        [2026-07-30T14:22:05+02:00] browser error: <message> (context: <ctx>) — <detail>

    ``context`` and ``detail`` are optional. Local time with an explicit offset is
    used so the line is unambiguous yet readable by whoever owns the machine.

    ``ensure_dir`` creates ``root`` first (parents included). It is off by default
    because a project root always exists when a project is open, and creating a
    *missing* one would resurrect a folder the user deleted mid-session. The
    machine-scope log (#741) is the opposite case: its home is the config dir,
    which may not exist yet when the very first error — a project-open failure
    before any settings were saved — is what we are trying to record.
    """
    try:
        if ensure_dir:
            root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
        parts = [f"[{stamp}]", origin, f"{level}:", _one_line(message) or _NO_MESSAGE]
        if context:
            parts.append(f"(context: {_one_line(context)})")
        if detail:
            parts.append(f"— {_one_line(detail)}")
        with (root / LOG_FILENAME).open("a", encoding="utf-8") as handle:
            handle.write(" ".join(parts) + "\n")
    except Exception:
        # #386 acceptance: the one place swallowing is correct. A log write that
        # fails (unwritable dir, gone mid-session, disk full) must not surface as
        # a failure of the save/AI-call/route it was only trying to record.
        return
