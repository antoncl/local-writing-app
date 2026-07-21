#!/usr/bin/env python3
"""Run an npm command against the frontend, ensuring node_modules resolves.

The frontend analog of `scripts/venv_run.py` (issue #137). A linked git
worktree checks out `frontend/` but has no `node_modules` (npm installs aren't
shared into worktrees), so the pre-push `svelte-check` / `vitest` gates can't
find their binaries there and `git push` fails.

The first answer to that was a directory junction into the primary worktree's
install. It cost us the install twice: a recursive delete that does not stop at
a reparse point -- `git worktree remove -f` among them -- walks *through* the
junction and guts the primary tree's `node_modules`, silently, surfacing later
as someone else's unrelated-looking gate failure (#350, and #352 for the venv
instance of the same shape). So: **no filesystem links.** A worktree without an
install gets its own real `npm install`. ~316 MB and about a minute, once per
worktree, in exchange for a delete that can only ever reach the worktree's own
copy.

Sharing is not recoverable here by cleverness: svelte-check and vitest resolve
the project's own imports (svelte, @tiptap/*, vite plugins) by walking up from
the source file, so PATH or NODE_PATH pointing at another tree's install does
not make the worktree's sources resolve.

Usage:
    python scripts/npm_run.py run check
    python scripts/npm_run.py test
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend"
NODE_MODULES = FRONTEND / "node_modules"


def npm() -> str:
    return shutil.which("npm") or "npm"  # npm.cmd on Windows -- resolve via PATH


def ensure_node_modules() -> bool:
    """Ensure `frontend/node_modules` exists, installing it here if it does not."""
    if NODE_MODULES.exists():
        return True
    sys.stderr.write(
        f"no install at {NODE_MODULES} -- running `npm install` for this worktree.\n"
        "(A worktree gets its own install on purpose: a shared link is deletable "
        "through, see #350.)\n"
    )
    return subprocess.run([npm(), "install", "--prefix", str(FRONTEND)]).returncode == 0


def main() -> int:
    if not ensure_node_modules():
        sys.stderr.write(
            f"could not install frontend dependencies under {FRONTEND}\n"
            "Run: npm install --prefix frontend\n"
        )
        return 1
    return subprocess.run([npm(), *sys.argv[1:], "--prefix", str(FRONTEND)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
