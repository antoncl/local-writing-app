"""Durable atomic file replacement (#480).

The temp-file-then-rename pattern gives a reader a file that is never *torn*,
but by itself it guarantees only that the bytes reached the OS page cache — not
that they reached stable storage. `flush()` pushes Python's buffer to the OS; it
does not push the OS's write-back cache to the disk. On a power loss or hard kill
inside the OS write-back window (seconds), a save the app already acknowledged to
the user as "saved" can be lost, or the file left at its old/empty state.

`fsync` closes that window in two places: the temp file's contents *before* the
rename, and the parent directory *after* it (so the rename itself — the entry
that now points at the new inode — is durable, not just the inode's bytes).

Directory fsync is POSIX-only. On Windows a directory has no descriptor to
`fsync`, and `os.replace` is itself atomic, so `_fsync_dir` is a no-op there.
(Local gates run on Windows — see docs/development — so the directory path is
first exercised by CI's Linux backend job; keep it correct by construction.)

The two service-level chokes (`project_service`, `tree_structure`) and the
snapshot byte-writer (`scene_snapshots`) delegate here so the durability
guarantee lives in one place, not three drifting copies.

`durable=False` is the one deliberate opt-out: the node-index snapshot is
rebuildable cache (#476), so paying an fsync on every index write-back would be
wasted work on a file that a crash may simply discard and rebuild. Every *user*
file — the prose a crash cannot reconstruct — is written `durable=True`.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

# #2350: on Windows `os.replace` fails with "Access denied" while ANOTHER process
# briefly holds the target open — a sync client (OneDrive/Dropbox), an antivirus
# scan, the search indexer, an editor. That lock is transient, so the replace is
# retried with a short backoff (~1 s in all) before the save is given up on.
_REPLACE_BACKOFF_S = (0.02, 0.05, 0.1, 0.15, 0.2, 0.2, 0.3)


def _discard(temp_path: Path) -> None:
    """Remove a temp file a failed write leaves behind — never litter the
    project folder with `tmpXXXX` files (#2350)."""
    with contextlib.suppress(OSError):
        temp_path.unlink(missing_ok=True)


def _replace(temp_path: Path, path: Path) -> None:
    """`temp_path.replace(path)`, retrying a transient lock (#2350). If the
    target stays locked, the temp file is removed and the error names the file
    and the likely cause instead of a bare `[WinError 5]`."""
    for delay in (*_REPLACE_BACKOFF_S, None):
        try:
            temp_path.replace(path)
            return
        except PermissionError as exc:
            if delay is None:
                _discard(temp_path)
                raise PermissionError(
                    f"Couldn't save {path.name}: another program is holding it open "
                    "(a sync client, an antivirus scan, the search indexer or an editor). "
                    "Try again in a moment."
                ) from exc
            time.sleep(delay)
        except BaseException:
            _discard(temp_path)
            raise


def _fsync_dir(directory: Path) -> None:
    """fsync a directory so a rename into it is durable. POSIX-only: Windows
    has no directory descriptor to sync, and its `os.replace` is atomic."""
    if os.name != "posix":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_text(path: Path, text: str, *, durable: bool = True) -> None:
    """Write `text` to `path` atomically. When `durable`, fsync the contents to
    stable storage before the rename and the parent directory after it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
        try:
            temp.write(text)
            temp.flush()
            if durable:
                os.fsync(temp.fileno())
        except BaseException:
            temp.close()
            _discard(temp_path)
            raise
    _replace(temp_path, path)
    if durable:
        _fsync_dir(path.parent)


def atomic_write_bytes(path: Path, data: bytes, *, durable: bool = True) -> None:
    """`atomic_write_text` for bytes — the snapshot restore path, which must not
    go through the text writer (encoding / newline / front-matter normalisation
    each break byte-for-byte fidelity)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
        try:
            temp.write(data)
            temp.flush()
            if durable:
                os.fsync(temp.fileno())
        except BaseException:
            temp.close()
            _discard(temp_path)
            raise
    _replace(temp_path, path)
    if durable:
        _fsync_dir(path.parent)
