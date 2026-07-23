#!/usr/bin/env python3
"""Claude Code SessionEnd hook — stop the dev servers this session started.

CLAUDE.md tells a worktree session to start the dev servers by hand, because
`preview_start` by config name would run the primary tree's code (#360). It has
never had a corresponding stop step, and prose alone did not supply one: a Vite
server started by a session on 2026-07-22 was still running twenty hours later,
holding port 5173 and — because Windows will not unlink a running executable —
holding `esbuild.exe` inside its worktree, which left 23,413 files undeletable
behind an access-denied error that looks like a permissions problem (#452).

Two safety invariants, because sessions run concurrently and the primary tree
holds Anton's WIP *and his live projects*:

1. **Never act outside a linked worktree.** In the primary tree this exits
   immediately: those servers are Anton's, not a session's.
2. **Only kill a process whose command line names this worktree's own path.**
   That is what makes it impossible to reach a sibling worktree or the primary
   tree, even when several sessions are running at once.

Kills the process *tree*, never the bare process — #364: `uvicorn --reload` and
`vite` both spawn children that outlive the parent and keep holding the port,
and the PID the OS reports against the socket is usually the dead reloader.

Always exits 0. A broken cleanup hook must never wedge a session's exit.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

# ASCII only, and forced UTF-8: this prints to a Windows cp1252 console, where
# a stray non-ASCII byte would raise mid-print and swallow the report.
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A process is only a candidate if its command line looks like one of the dev
# servers CLAUDE.md tells a session to start. Path containment is the security
# boundary; this is just to avoid killing an unrelated tool that happens to run
# from inside the worktree (an editor, a test runner, a language server).
SERVER_MARKERS = (
    "--mode claude",
    "dev_backend.py",
    "dev_backend_app",
    "vite",
    "uvicorn",
)

# Never kill a shell, whatever its arguments look like. A shell's command line
# contains the command it was asked to run, so `bash -c "... vite --mode claude
# ..."` matches every content test a real server does. The first version of this
# hook killed the shell that was running its own test for exactly that reason —
# and in a session, that shell is the session's tooling.
#
# This costs nothing: the incident tree was cmd.exe -> node -> esbuild.exe, and
# killing node with /T takes esbuild with it while cmd exits on its own once its
# child is gone. Servers are what we want; shells are what we must not touch.
SHELLS = {
    "bash.exe", "sh.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "conhost.exe",
    "bash", "sh", "zsh", "fish",
}

# Never kill ourselves or our own parent, whatever the command line looks like.
SELF_PIDS = {os.getpid(), os.getppid()}


def is_linked_worktree(root: Path) -> bool:
    """True only if `root` is a linked worktree; False for the primary tree.

    Asks about `root` explicitly rather than the process's own cwd: the hook is
    invoked as `${CLAUDE_PROJECT_DIR}/.claude/hooks/...`, which resolves to the
    PRIMARY tree, so "wherever this script happens to be running" is exactly the
    wrong thing to ask about (#360 is the same mistake in another guise).

    Fails closed: if git cannot answer, nothing is killed.
    """
    try:
        common = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=8,
        )
        own = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=8,
        )
    except Exception:
        return False
    if common.returncode != 0 or own.returncode != 0:
        return False
    try:
        # `--git-dir` may come back relative to `root`, so resolve against it.
        return (root / common.stdout.strip()).resolve() != (root / own.stdout.strip()).resolve()
    except Exception:
        return False


def normalise(text: str) -> str:
    """Compare paths case- and separator-insensitively (Windows)."""
    return text.replace("\\", "/").casefold()


def owned_by(root: Path, processes: list[tuple[int, str, str]]) -> list[int]:
    """PIDs of `processes` that are dev servers belonging to `root`.

    A pure function over (pid, executable name, command line) triples so the
    decision can be tested without spawning anything. All four must hold: not
    ourselves, not a shell, the worktree path appears in the command line, and
    the command line looks like a dev server.
    """
    needle = normalise(str(root))
    # Refuse a root so short it would match most of the filesystem. A bare drive
    # or "/" here would turn this hook into a machine-wide killer.
    if len(needle.strip("/")) < 8:
        return []
    owned = []
    for pid, name, cmdline in processes:
        if pid in SELF_PIDS or not cmdline:
            continue
        if name.casefold() in SHELLS:
            continue
        low = normalise(cmdline)
        if needle in low and any(marker in low for marker in SERVER_MARKERS):
            owned.append(pid)
    return owned


def list_processes() -> list[tuple[int, str, str]]:
    """(pid, executable name, command line) for every process; [] if unknown."""
    if sys.platform == "win32":
        script = (
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
        )
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    else:
        cmd = ["ps", "-eo", "pid=,comm=,args="]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception:
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []

    parse = _parse_powershell if sys.platform == "win32" else _parse_ps
    return parse(proc.stdout)


def _parse_ps(stdout: str) -> list[tuple[int, str, str]]:
    """Parse `ps -eo pid=,comm=,args=` output."""
    rows: list[tuple[int, str, str]] = []
    for line in stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        with contextlib.suppress(ValueError):
            rows.append((int(parts[0]), Path(parts[1]).name, parts[2]))
    return rows


def _parse_powershell(stdout: str) -> list[tuple[int, str, str]]:
    """Parse the ConvertTo-Json output of a Win32_Process query."""
    try:
        data = json.loads(stdout)
    except Exception:
        return []
    if isinstance(data, dict):  # a single process serialises as an object
        data = [data]
    rows: list[tuple[int, str, str]] = []
    for item in data:
        pid, name, cmdline = item.get("ProcessId"), item.get("Name"), item.get("CommandLine")
        if isinstance(pid, int) and cmdline:
            rows.append((pid, name or "", cmdline))
    return rows


def kill_tree(pid: int) -> bool:
    """Kill `pid` and its descendants. The children are the point (#364)."""
    if sys.platform == "win32":
        cmd = ["taskkill", "/F", "/T", "/PID", str(pid)]
    else:
        cmd = ["pkill", "-TERM", "-P", str(pid)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except Exception:
        return False
    if sys.platform != "win32":  # pkill -P leaves the parent itself
        with contextlib.suppress(Exception):
            os.kill(pid, 15)
    return True


def session_root() -> Path:
    """Where this session was working. The event's cwd wins; ours is the fallback."""
    try:
        event = json.load(sys.stdin)
    except Exception:
        event = {}
    raw = (event or {}).get("cwd")
    try:
        return Path(raw).resolve() if raw else Path.cwd().resolve()
    except Exception:
        return Path.cwd().resolve()


def main() -> int:
    root = session_root()

    # Invariant 1: the primary tree's servers are Anton's. Fails closed.
    if not is_linked_worktree(root):
        return 0

    # Invariant 2: only what names this worktree.
    owned = owned_by(root, list_processes())
    if not owned:
        return 0

    killed = [pid for pid in owned if kill_tree(pid)]
    if killed:
        print(
            f"SessionEnd: stopped {len(killed)} dev server process tree(s) started "
            f"in this worktree (pids {', '.join(str(p) for p in killed)}). "
            "They would otherwise keep holding the port and, on Windows, lock the "
            "worktree's node_modules against deletion."
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0) from None
