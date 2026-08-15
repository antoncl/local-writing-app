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

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


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
        temp.write(text)
        temp.flush()
        if durable:
            os.fsync(temp.fileno())
        temp_path = Path(temp.name)
    temp_path.replace(path)
    if durable:
        _fsync_dir(path.parent)


def atomic_write_bytes(path: Path, data: bytes, *, durable: bool = True) -> None:
    """`atomic_write_text` for bytes — the snapshot restore path, which must not
    go through the text writer (encoding / newline / front-matter normalisation
    each break byte-for-byte fidelity)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", dir=path.parent, delete=False) as temp:
        temp.write(data)
        temp.flush()
        if durable:
            os.fsync(temp.fileno())
        temp_path = Path(temp.name)
    temp_path.replace(path)
    if durable:
        _fsync_dir(path.parent)
