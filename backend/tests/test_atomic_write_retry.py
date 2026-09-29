"""A transient file lock must not fail a save or litter the project (#2350).

On Windows, `os.replace` raises "Access denied" while another process briefly
holds the target open (a sync client, an antivirus scan, the search indexer, an
editor). The atomic writer retries that, and when it finally gives up (or the
write itself fails) it removes its temp file instead of leaving `tmpXXXX` behind.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import atomic_io
from app.services.atomic_io import atomic_write_bytes, atomic_write_text


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(atomic_io.time, "sleep", lambda _s: None)


def _locked_for(monkeypatch, failures: int) -> list[int]:
    """Make `Path.replace` raise PermissionError for the first `failures` calls."""
    real_replace = Path.replace
    calls = [0]

    def flaky(self, target):
        calls[0] += 1
        if calls[0] <= failures:
            raise PermissionError(5, "Access denied")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    return calls


def _temp_files(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if p.name.startswith("tmp")]


def test_a_transient_lock_is_retried_and_the_save_lands(tmp_path, monkeypatch) -> None:
    target = tmp_path / "Card 1.md"
    target.write_text("old", encoding="utf-8")
    calls = _locked_for(monkeypatch, failures=3)
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert calls[0] == 4
    assert _temp_files(tmp_path) == []


def test_a_lock_that_never_clears_fails_clearly_and_leaves_no_temp_file(tmp_path, monkeypatch) -> None:
    target = tmp_path / "Card 1.md"
    target.write_text("old", encoding="utf-8")
    _locked_for(monkeypatch, failures=10_000)
    with pytest.raises(PermissionError, match="Couldn't save Card 1.md: another program is holding it open"):
        atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old"  # untouched
    assert _temp_files(tmp_path) == []


def test_the_bytes_writer_retries_too(tmp_path, monkeypatch) -> None:
    target = tmp_path / "snap.bin"
    _locked_for(monkeypatch, failures=2)
    atomic_write_bytes(target, b"\x00\x01")
    assert target.read_bytes() == b"\x00\x01"
    assert _temp_files(tmp_path) == []


def test_a_failed_write_removes_its_temp_file(tmp_path, monkeypatch) -> None:
    def boom(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(atomic_io.os, "fsync", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write_text(tmp_path / "x.md", "text")
    assert _temp_files(tmp_path) == []
