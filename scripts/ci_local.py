#!/usr/bin/env python3
"""Run the local equivalent of `.github/workflows/gates.yml`.

Use this before pushing a PR branch when you want the same blocking checks CI
will run, without installing slow pre-push hooks.

Usage:
    python scripts/ci_local.py
    python scripts/ci_local.py --base origin/plotting
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def command_text(args: list[str | Path]) -> str:
    display_args = args
    if len(args) > 18:
        display_args = [*args[:14], f"... ({len(args) - 14} more args)"]
    return " ".join(shlex.quote(str(arg)) for arg in display_args)


def run(label: str, args: list[str | Path]) -> None:
    print(f"\n==> {label}", flush=True)
    print(command_text(args), flush=True)
    result = subprocess.run([str(arg) for arg in args], cwd=REPO)
    if result.returncode:
        raise SystemExit(result.returncode)


def git_ls_files(patterns: list[str]) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={REPO.as_posix()}",
            "ls-files",
            *patterns,
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return [line for line in result.stdout.splitlines() if line]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        help="Run the PR-only exemption ratchet against this base ref, for example origin/plotting.",
    )
    parser.add_argument(
        "--pytest-basetemp",
        help="Pass a writable temp directory outside the repo when the default system temp is unavailable.",
    )
    args = parser.parse_args(argv)

    run(
        "ruff",
        [
            sys.executable,
            SCRIPTS / "venv_run.py",
            "-m",
            "ruff",
            "check",
            "backend",
            "scripts",
            ".claude/hooks",
        ],
    )

    source_files = git_ls_files(["*.py", "*.svelte", "*.ts", "*.tsx"])
    if source_files:
        run("file-size guard", [sys.executable, SCRIPTS / "check_file_size.py", *source_files])

    style_files = git_ls_files(["frontend/src/**/*.svelte", "frontend/src/styles.css"])
    if style_files:
        run("style-token guard", [sys.executable, SCRIPTS / "check_style_tokens.py", *style_files])

    if args.base:
        run("exemption ratchet", [sys.executable, SCRIPTS / "check_exemptions.py", "--base", args.base])

    pytest_basetemp = None
    if args.pytest_basetemp:
        raw_basetemp = Path(args.pytest_basetemp)
        pytest_basetemp = (raw_basetemp if raw_basetemp.is_absolute() else REPO / raw_basetemp).resolve()
        try:
            pytest_basetemp.relative_to(REPO)
        except ValueError:
            pass
        else:
            parser.error("--pytest-basetemp must be outside the repo; paths inside linked worktrees change test behavior.")

    pytest_args: list[str | Path] = [
        sys.executable,
        SCRIPTS / "venv_run.py",
        "-m",
        "pytest",
        "backend/tests",
        "-q",
        "--timeout=120",
        "--timeout-method=thread",
    ]
    if pytest_basetemp:
        pytest_args.extend(["--basetemp", pytest_basetemp])
    run("pytest", pytest_args)

    run("svelte-check", [sys.executable, SCRIPTS / "npm_run.py", "run", "check"])
    run("vitest", [sys.executable, SCRIPTS / "npm_run.py", "test"])

    print("\nLocal CI gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
