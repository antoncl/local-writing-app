#!/usr/bin/env python3
"""Run an npm command against the frontend, ensuring node_modules resolves.

The frontend analog of `scripts/venv_run.py` (issue #137). A linked git
worktree checks out `frontend/` but has no `node_modules` (npm installs aren't
shared into worktrees), so the pre-push `svelte-check` / `vitest` gates can't
find their binaries there and `git push` fails. When the worktree's
`frontend/node_modules` is absent, link it to the *primary* worktree's install
(directory junction on Windows — no elevation needed — else a symlink), then
run the worktree's own source against that shared install. One install, all
worktrees.

Usage:
    python scripts/npm_run.py run check
    python scripts/npm_run.py test
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree import main_worktree_root  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend"
NODE_MODULES = FRONTEND / "node_modules"


def _link_dir(link: Path, target: Path) -> None:
    """Create `link` pointing at directory `target`, portably."""
    if os.name == "nt":
        # Junction, not a symlink: works without admin / developer mode.
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


def ensure_node_modules() -> bool:
    """Ensure `frontend/node_modules` resolves; link the primary worktree's if not."""
    if NODE_MODULES.exists():
        return True
    main = main_worktree_root(REPO)
    if not main:
        return False
    src = main / "frontend" / "node_modules"
    if not src.is_dir():
        return False
    try:
        _link_dir(NODE_MODULES, src)
    except (OSError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"could not link {NODE_MODULES} -> {src}: {exc}\n")
        return False
    sys.stderr.write(f"linked {NODE_MODULES} -> {src} (worktree shares the primary install)\n")
    return True


def main() -> int:
    if not ensure_node_modules():
        sys.stderr.write(
            f"frontend/node_modules not found under {FRONTEND} "
            "(or the primary worktree's install)\n"
            "Run: npm install --prefix frontend\n"
        )
        return 1
    npm = shutil.which("npm") or "npm"  # npm.cmd on Windows — resolve via PATH
    return subprocess.run([npm, *sys.argv[1:], "--prefix", str(FRONTEND)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
