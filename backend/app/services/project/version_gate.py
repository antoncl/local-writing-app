"""Refuse a request whose project or tab predates the running code (#2675).

Migrations run only on `/open` (ADR-0071 §4) and a tab calls that only on a page
load, so a tab that outlives a backend upgrade would otherwise keep reading and
writing around it. A new editor reading an old-format body loses what it cannot
parse on the next save, so reads are refused along with writes.

Two checks, because each misses a case the other catches:

- The project on disk is below `CURRENT_VERSION`: the live tab across a `git
  pull` and restart, or a backup restored under a live tab.
- The tab opened under another version: the packaged update, whose relaunch opens
  a new tab that migrates the project while the old tab keeps running the old
  bundle against files that are now current.

The answer is a 409 the client turns into a re-open (`project_outdated`), and
`/open` itself never comes through here, so recovery stays reachable.
"""

from __future__ import annotations

from pathlib import Path

from app.services import migrations
from app.services.project.errors import ProjectServiceError
from app.services.project.layers import MANIFEST_FILENAME

PROJECT_OUTDATED = "project_outdated"

# Per process, per root: the manifest's (mtime_ns, size) and the version read at
# that stat. Every scoped request pays one `stat`; the file is parsed only when it
# changed, which is also what notices a restored backup. Two threads racing here
# parse the same file twice and store the same value.
_memo: dict[Path, tuple[int, int, int | None]] = {}


def _version_on_disk(root: Path) -> int | None:
    try:
        stat = (root / MANIFEST_FILENAME).stat()
        remembered = _memo.get(root)
        if remembered is not None and remembered[:2] == (stat.st_mtime_ns, stat.st_size):
            return remembered[2]
        version = migrations.stated_project_version(root)
    except OSError:
        return None
    _memo[root] = (stat.st_mtime_ns, stat.st_size, version)
    return version


def forget_version(root: Path) -> None:
    """Drop what is remembered for `root`, once its open has stamped it. On a
    coarse-mtime drive the stamp can land in the tick of a version read mid-migration,
    at the same size; the memo would then refuse the project after every open."""
    _memo.pop(root, None)


def require_current_version(root: Path, tab_version: int | None) -> None:
    """Raise the 409 when `root` or the tab is behind. A header-less client (a
    script) answers only to the disk check; a folder with no readable manifest is
    not policed here, its downstream reads fail as they always have."""
    version = _version_on_disk(root)
    outdated_on_disk = version is not None and version < migrations.CURRENT_VERSION
    if outdated_on_disk or (tab_version is not None and tab_version != migrations.CURRENT_VERSION):
        raise ProjectServiceError(
            "This project needs to be reopened by the updated app.",
            409,
            {"code": PROJECT_OUTDATED},
        )
