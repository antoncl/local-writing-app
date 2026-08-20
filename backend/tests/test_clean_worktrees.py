"""Safety tests for `scripts/clean_worktrees.py` (#359).

The one that matters is `find_reparse_points`: it is the gate that stops a
worktree cleanup from walking a `node_modules` junction into the primary tree
and deleting it (#350). The rest pin the decision table so a future edit cannot
quietly let an unmerged or dirty worktree be classified STALE.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest


def _load_script(name: str):
    """Import a module from `scripts/`, which is not a package (the gate-test idiom)."""
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec: `@dataclass` resolves `__module__` via sys.modules
    # (Python 3.14), which is None for an unregistered spec-loaded module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


clean = _load_script("clean_worktrees")
Worktree = clean.Worktree


def _make_dir_link(link: Path, target: Path) -> None:
    """A directory reparse point: a junction on Windows, a symlink elsewhere."""
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


def _proc(stdout: str = "", returncode: int = 0, stderr: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def _git_sequence(*results):
    """A fake `_git` that returns each canned result in turn (status, then rev-list)."""
    it = iter(results)

    def fake(args, cwd=None):
        return next(it)

    return fake


# ── the reparse-point safety scan ───────────────────────────────────────────


def test_find_reparse_points_flags_a_link_and_never_descends_through_it(tmp_path: Path):
    # A worktree with a node_modules junction pointing at a "primary" tree that
    # itself holds a nested link — if the scan descended THROUGH the junction it
    # would surface the nested link too. It must not.
    primary = tmp_path / "primary"
    primary.mkdir()
    (primary / "keepme.txt").write_text("primary install")
    nested_target = tmp_path / "nested"
    nested_target.mkdir()
    _make_dir_link(primary / "nested_link", nested_target)

    wt = tmp_path / "wt"
    (wt / "frontend").mkdir(parents=True)
    (wt / "frontend" / "real.ts").write_text("ok")
    _make_dir_link(wt / "frontend" / "node_modules", primary)

    found = clean.find_reparse_points(wt)
    names = {p.name for p in found}
    assert "node_modules" in names  # the junction is flagged
    assert "nested_link" not in names  # proof the walk did not step through it


def test_find_reparse_points_returns_empty_for_a_plain_tree(tmp_path: Path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f.txt").write_text("x")
    assert clean.find_reparse_points(tmp_path) == []


# ── porcelain parsing ───────────────────────────────────────────────────────


def test_list_worktrees_marks_the_first_record_main_and_strips_branch(monkeypatch):
    porcelain = (
        "worktree D:/repo\nHEAD aaa\nbranch refs/heads/master\n\n"
        "worktree D:/repo/.claude/worktrees/feat\nHEAD bbb\nbranch refs/heads/worktree-feat\n\n"
        "worktree D:/repo/.claude/worktrees/detached\nHEAD ccc\ndetached\n\n"
    )
    monkeypatch.setattr(clean, "_git", lambda args, cwd=None: _proc(stdout=porcelain))
    trees = clean.list_worktrees(Path("D:/repo"))
    assert [t.is_main for t in trees] == [True, False, False]
    assert trees[0].branch == "master"
    assert trees[1].branch == "worktree-feat"
    assert trees[1].name == "feat"
    assert trees[2].branch is None  # detached carries no branch


# ── the decision table ──────────────────────────────────────────────────────


def test_assess_skips_the_primary_worktree(tmp_path: Path):
    wt = Worktree(path=tmp_path, branch=None, head="h", is_main=True)
    assert clean.assess(wt, running_from=Path("D:/elsewhere")).status == clean.STATUS_SKIP


def test_assess_skips_the_worktree_it_runs_from(tmp_path: Path):
    wt = Worktree(path=tmp_path, branch="b", head="h")
    assert clean.assess(wt, running_from=tmp_path).status == clean.STATUS_SKIP


def test_assess_blocks_on_a_reparse_point_before_touching_git(monkeypatch, tmp_path: Path):
    wt = Worktree(path=tmp_path, branch="b", head="h")
    monkeypatch.setattr(clean, "find_reparse_points", lambda p: [tmp_path / "node_modules"])
    monkeypatch.setattr(clean, "_git", lambda *a, **k: pytest.fail("git must not run on a BLOCKED worktree"))
    result = clean.assess(wt, running_from=Path("D:/elsewhere"))
    assert result.status == clean.STATUS_BLOCKED
    assert result.reparse_points


def test_assess_keeps_a_dirty_worktree(monkeypatch, tmp_path: Path):
    wt = Worktree(path=tmp_path, branch="b", head="h")
    monkeypatch.setattr(clean, "find_reparse_points", lambda p: [])
    monkeypatch.setattr(clean, "_git", lambda args, cwd=None: _proc(stdout=" M file.py\n"))
    result = clean.assess(wt, running_from=Path("D:/elsewhere"))
    assert result.status == clean.STATUS_KEEP
    assert "uncommitted" in result.reason


def test_assess_keeps_a_clean_but_unmerged_worktree(monkeypatch, tmp_path: Path):
    wt = Worktree(path=tmp_path, branch="b", head="h")
    monkeypatch.setattr(clean, "find_reparse_points", lambda p: [])
    monkeypatch.setattr(clean, "_git", _git_sequence(_proc(stdout=""), _proc(stdout="3\n")))
    result = clean.assess(wt, running_from=Path("D:/elsewhere"))
    assert result.status == clean.STATUS_KEEP
    assert "unmerged" in result.reason


def test_assess_marks_a_clean_merged_worktree_stale(monkeypatch, tmp_path: Path):
    wt = Worktree(path=tmp_path, branch="b", head="h")
    monkeypatch.setattr(clean, "find_reparse_points", lambda p: [])
    monkeypatch.setattr(clean, "_git", _git_sequence(_proc(stdout=""), _proc(stdout="0\n")))
    result = clean.assess(wt, running_from=Path("D:/elsewhere"))
    assert result.status == clean.STATUS_STALE
