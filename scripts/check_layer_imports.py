#!/usr/bin/env python3
"""Layer-import guard — the service layer may not depend on the web layer
(ADR-0056, #977). This is a *fitness gate*, the fallback the ADR names for a
boundary that cannot be collapsed into a single choke point: "a `services/`
module must not import FastAPI."

The boundary it defends: routes (`backend/app/routers/*.py`, plus `main.py`)
are the web layer; they delegate to `ProjectService` and its mixins under
`backend/app/services/`. The dependency runs one way — routes import services,
never the reverse. A service that reaches back up to `fastapi`, `starlette`, or
the route modules has inverted the layering: business logic now knows about
HTTP, `HTTPException`, `Request`, routers. That rots the whole arrangement and
is invisible to an author who does not read the code — exactly the blast radius
ADR-0056 §5 says earns a gate.

Why AST, not grep: an import is a syntactic fact. Parsing sees `import fastapi`
and `from ..main import app` and nothing else — never a matching substring in a
string literal, a comment, or a docstring. Zero false positives by construction.

Relative imports are resolved to absolute before matching, so `from ..main
import app` inside `app/services/x.py` is caught as `app.main`.

FAILS (exit 1) on any forbidden import unless the file is grandfathered below.
Non-service paths are ignored, so it is safe to hand this the full staged-file
list (pre-commit), a single edited file (the Claude Code PostToolUse hook), or
the whole tree (CI).

Usage:
    python scripts/check_layer_imports.py <file> [<file> ...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Service files exempt from the boundary, matched against the path tail (repo
# -relative, forward slashes). Empty and meant to stay empty: no service
# currently imports the web layer. Add an entry only for a deliberate, PR
# -announced exception — growth is ratcheted by scripts/check_exemptions.py.
GRANDFATHERED: set[str] = set()

# The web layer, top-level: the HTTP framework and its base, plus the route
# modules themselves. A service importing any of these has inverted the layering.
# Matched as the module itself or a submodule (`fastapi`, `fastapi.responses`).
FORBIDDEN_ROOTS = ("fastapi", "starlette", "app.main", "app.routers")

# Only files under this path are the service layer this guard governs.
SERVICES_MARKER = "backend/app/services/"


def is_service_file(path: Path) -> bool:
    return path.suffix == ".py" and f"/{path.as_posix()}".find(f"/{SERVICES_MARKER}") != -1


def module_of(path: Path) -> list[str]:
    """Dotted module parts of a backend file, e.g. app.services.project.chats.

    Anchored at the `app` package so relative imports resolve correctly.
    """
    parts = path.as_posix().split("/")
    if "app" in parts:
        parts = parts[parts.index("app") :]
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][: -len(".py")]
    return parts


def resolve(module_parts: list[str], node: ast.ImportFrom) -> str | None:
    """Absolute dotted name a `from ... import` targets, or None if unresolvable.

    `module_parts` is the importing module (…, 'chats'). Its package is the
    parent (a `__init__` module is itself the package). `level` counts dots:
    level 1 anchors at the package, level 2 at its parent, and so on.
    """
    if node.level == 0:
        return node.module
    package = module_parts if module_parts[-1:] == ["__init__"] else module_parts[:-1]
    base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
    tail = node.module.split(".") if node.module else []
    resolved = base + tail
    return ".".join(resolved) if resolved else None


def is_forbidden(module: str | None) -> bool:
    if not module:
        return False
    return any(module == root or module.startswith(root + ".") for root in FORBIDDEN_ROOTS)


def check_file(path: Path) -> list[tuple[int, str]]:
    """(line, forbidden-module) for every web-layer import in a service file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []  # a broken file is ruff/pytest's problem, not this guard's
    module_parts = module_of(path)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [(node.lineno, a.name) for a in node.names if is_forbidden(a.name)]
        elif isinstance(node, ast.ImportFrom):
            resolved = resolve(module_parts, node)
            if is_forbidden(resolved):
                hits.append((node.lineno, resolved))  # type: ignore[arg-type]
    return hits


def is_grandfathered(posix_path: str) -> bool:
    return any(posix_path.endswith(entry) for entry in GRANDFATHERED)


def main(argv: list[str]) -> int:
    failed = False
    for raw in argv:
        path = Path(raw)
        if not is_service_file(path) or not path.is_file():
            continue
        hits = check_file(path)
        if not hits:
            continue
        rel = path.as_posix()
        if is_grandfathered(rel):
            print(f"warn  {rel}: {len(hits)} web-layer import(s) (grandfathered - clean up when you next work here).")
            continue
        failed = True
        for line_no, module in hits:
            print(f"FAIL  {rel}:{line_no}: service imports the web layer (`{module}`)")
    if failed:
        print("Services must not depend on FastAPI or the routers (ADR-0056: layering runs routes -> services).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
