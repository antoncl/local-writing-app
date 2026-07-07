"""Node-file rename is resilient to transient Windows locks (#164).

`_maybe_rename_node_file` canonicalizes a node's on-disk filename to its title
*after* the content is already saved. On Windows the just-written file is
briefly locked (Defender / the search indexer scans it), so the rename can raise
`PermissionError` (WinError 32). Because the filename is cosmetic — the
front-matter `id` is the canonical identity, and reads resolve by id — a rename
failure must retry, then degrade gracefully rather than fail the save.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.runtime import service as svc


@pytest.fixture
def service(monkeypatch):
    svc.__init__()
    # Never actually sleep between rename retries.
    monkeypatch.setattr("app.services.project_service.time.sleep", lambda _: None)
    return svc


def test_rename_with_retry_recovers_from_transient_lock(service, monkeypatch, tmp_path):
    real_rename = Path.rename
    calls = {"n": 0}

    def flaky_rename(self: Path, target):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(32, "locked by another process")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)

    src = tmp_path / "src.md"
    src.write_text("x", encoding="utf-8")
    dst = tmp_path / "dst.md"

    service._rename_with_retry(src, dst)

    assert calls["n"] == 3
    assert dst.exists() and not src.exists()


def test_rename_with_retry_reraises_when_lock_never_clears(service, monkeypatch, tmp_path):
    def always_locked(self: Path, target):
        raise PermissionError(32, "locked by another process")

    monkeypatch.setattr(Path, "rename", always_locked)

    src = tmp_path / "src.md"
    src.write_text("x", encoding="utf-8")

    with pytest.raises(PermissionError):
        service._rename_with_retry(src, tmp_path / "dst.md")


def test_no_rename_when_filename_already_represents_title(service, tmp_path):
    # "New Entry (2).md" is a name the file legitimately owns for title
    # "New Entry"; even though "New Entry.md" is free, a save must not churn it.
    src = tmp_path / "New Entry (2).md"
    src.write_text("x", encoding="utf-8")

    result = service._maybe_rename_node_file(src, "New Entry")

    assert result == src
    assert src.exists()
    assert not (tmp_path / "New Entry.md").exists()


def test_rename_on_real_title_change(service, tmp_path):
    src = tmp_path / "Old Name.md"
    src.write_text("x", encoding="utf-8")

    result = service._maybe_rename_node_file(src, "Brand New")

    assert result == tmp_path / "Brand New.md"
    assert result.exists() and not src.exists()


def test_maybe_rename_is_non_fatal_when_lock_persists(service, monkeypatch, tmp_path):
    def always_locked(self: Path, target):
        raise PermissionError(32, "locked by another process")

    monkeypatch.setattr(Path, "rename", always_locked)

    src = tmp_path / "Old Name.md"
    src.write_text("---\nid: x\n---\n", encoding="utf-8")

    # The save has already persisted the content; a persistent lock on the
    # cosmetic rename must not propagate.
    result = service._maybe_rename_node_file(src, "New Name")

    assert result == src
    assert src.exists()
    assert not (tmp_path / "New Name.md").exists()
