"""Build the frozen product (ADR-0072 S3, #1344): frontend build + PyInstaller.

Run from an isolated build venv that has the project installed with the `build`
extra. Windows-first; the CI matrix (S4) will call the same two steps.

    <venv>/python -m packaging.build         # or: python packaging/build.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=_REPO, **kw)


def main() -> None:
    # 1) Build the frontend bundle the spec collects.
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    _run([npm, "run", "build", "--prefix", "frontend"])
    # 2) Freeze.
    _run([sys.executable, "-m", "PyInstaller", "packaging/local-writing-app.spec", "--noconfirm"])
    print("\nBuilt: dist/local-writing-app/local-writing-app" + (".exe" if sys.platform == "win32" else ""), flush=True)


if __name__ == "__main__":
    main()
