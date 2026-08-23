"""What commit this binary was built from (ADR-0072 S6, #1362).

The version string (`importlib.metadata.version`) answers "which release", but
every **nightly** reports the same `0.9.x` — the version is bumped only at a
stable tag, so a run built from master last night and one built a week ago are
indistinguishable by version alone. The auto-update check needs a finer key on
the nightly channel: the exact commit the build was frozen at.

The packaging spec bakes `GITHUB_SHA` into a data file at freeze time (where the
build env knows the commit); a frozen run reads it back here. A source run has no
baked stamp and returns `None` — honest, because a `python -m app` run is not a
release anyone can compare against.

Unlike the node-index build identity (which *raises* when a frozen build ships
without its stamp, because a wrong answer there corrupts a user's project), a
missing stamp here is not a correctness hazard — it only means "can't tell if a
newer nightly exists". So this degrades to `None` and the update check reports
itself unable to compare, rather than crashing the app.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The bundled file a frozen build reads its commit stamp from. The spec writes
# `os.environ["GITHUB_SHA"]` (empty in a local freeze) into a file of this name.
BUILD_STAMP_FILENAME = "build_stamp.txt"


def build_stamp() -> str | None:
    """The full commit SHA this binary was frozen at, or `None`.

    `None` for a source run (no bundle), for a frozen build that shipped without
    the stamp (a packaging defect, but not a crash-worthy one here), and for a
    frozen local build where `GITHUB_SHA` was unset (baked as an empty string).
    """
    if not (getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")):
        return None
    stamp = Path(sys._MEIPASS) / BUILD_STAMP_FILENAME
    if not stamp.is_file():
        return None
    value = stamp.read_text(encoding="utf-8").strip()
    return value or None
