#!/usr/bin/env python3
"""Exemption ratchet — every escape hatch may shrink, never grow (#352).

The failure mode this exists for: faced with a red gate, the cheapest fix is
almost never fixing the code. It is adding the file to a grandfather set,
widening a lint `ignore`, dropping a rule from `select`, or marking the test
`skip`/`xfail`. Each edit is locally defensible; the aggregate is a dead gate,
and nothing in the diff announces it. That temptation is strongest for
generated code, where "make the red go away" is a well-formed instruction.

So the exemption lists are treated as ratchets: compare this checkout against a
base ref (default `origin/master`) and FAIL if any of them got weaker.

  * `scripts/check_file_size.py`      GRANDFATHERED
  * `scripts/check_style_tokens.py`   GRANDFATHERED, GRANDFATHERED_FONT_FAMILY
  * `backend/pyproject.toml`          ruff lint `ignore` (must not grow),
                                      `select` (must not shrink),
                                      `per-file-ignores` (must not grow)
  * disabled tests                    pytest skip/xfail + vitest skip/todo
                                      (counts must not grow)

Shrinking is always allowed and never announced — that is the direction we
want. Legitimate growth is not forbidden, only *silent* growth: say so in the
commit, and a reviewer decides. There is no override flag on purpose; if a new
exemption is genuinely right, the base moves once it lands and the ratchet
re-arms at the new value.

Usage:
    python scripts/check_exemptions.py [--base origin/master]
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# file -> module-level set names to compare
GUARD_SETS = {
    "scripts/check_file_size.py": ("GRANDFATHERED",),
    "scripts/check_style_tokens.py": ("GRANDFATHERED", "GRANDFATHERED_FONT_FAMILY"),
}
PYPROJECT = "backend/pyproject.toml"

# Disabled-test markers, counted over tracked test files via `git grep`.
DISABLED_PATTERNS = {
    "pytest skip/xfail": (
        r"@pytest\.mark\.(skip|skipif|xfail)|unittest\.skip",
        ("backend/tests/*.py",),
    ),
    "vitest skip/todo": (
        r"\b(it|test|describe)\.(skip|todo)\b",
        ("frontend/src/*.ts", "frontend/src/*.js"),
    ),
}


def git(*args: str) -> subprocess.CompletedProcess[str]:
    # Explicit utf-8: the default on Windows is cp1252, which dies on the first
    # em dash in a source file.
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def at_base(base: str, path: str) -> str | None:
    """File content at `base`, or None if it did not exist there."""
    proc = git("show", f"{base}:{path}")
    return proc.stdout if proc.returncode == 0 else None


def module_sets(source: str, names: tuple[str, ...]) -> dict[str, set[str]]:
    """Module-level `NAME = {...}` / `NAME: set[str] = set()` literals."""
    found: dict[str, set[str]] = {}
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        else:
            continue
        for name in targets:
            if name not in names or node.value is None:
                continue
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                value = set()  # `set()` call — an empty set, the goal state
            found[name] = set(value)
    return found


def ruff_lists(source: str) -> dict[str, set[str]]:
    """ruff's ignore / select / per-file-ignores, flattened to comparable sets."""
    lint = tomllib.loads(source).get("tool", {}).get("ruff", {}).get("lint", {})
    per_file = {
        f"{glob} {code}"
        for glob, codes in lint.get("per-file-ignores", {}).items()
        for code in codes
    }
    return {
        "ruff ignore": set(lint.get("ignore", [])),
        "ruff select": set(lint.get("select", [])),
        "ruff per-file-ignores": per_file,
    }


def disabled_counts(base: str | None) -> dict[str, int]:
    """Count disabled-test markers, in the working tree or at `base`.

    One `git grep` per pattern rather than a read per file — the same scan the
    ratchet would otherwise do with hundreds of subprocesses.
    """
    counts: dict[str, int] = {}
    for label, (pattern, pathspecs) in DISABLED_PATTERNS.items():
        args = ["grep", "--no-color", "-I", "-E", "-o", "-e", pattern]
        if base:
            args.append(base)
        proc = git(*args, "--", *pathspecs)
        # exit 1 = no matches, which is a legitimate zero.
        counts[label] = len([ln for ln in proc.stdout.split("\n") if ln.strip()])
    return counts


def compare(label: str, base: set[str], now: set[str], *, may_grow: bool) -> list[str]:
    """Failures for one ratchet. `may_grow=False` means additions are the sin."""
    added, removed = sorted(now - base), sorted(base - now)
    if not may_grow and added:
        return [f"FAIL  {label}: {len(added)} new exemption(s): {', '.join(added)}"]
    if may_grow and removed:
        return [f"FAIL  {label}: {len(removed)} rule(s) dropped: {', '.join(removed)}"]
    return []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/master", help="ref to ratchet against")
    args = parser.parse_args(argv)

    failures: list[str] = []
    shrank: list[str] = []

    for path, names in GUARD_SETS.items():
        base_src = at_base(args.base, path)
        if base_src is None:
            continue  # new file — nothing to ratchet against yet
        base_sets = module_sets(base_src, names)
        now_sets = module_sets((REPO / path).read_text(encoding="utf-8"), names)
        for name in names:
            base_set, now_set = base_sets.get(name, set()), now_sets.get(name, set())
            failures += compare(f"{path}:{name}", base_set, now_set, may_grow=False)
            if base_set - now_set:
                shrank.append(f"{path}:{name} -{len(base_set - now_set)}")

    base_src = at_base(args.base, PYPROJECT)
    if base_src is not None:
        base_lists = ruff_lists(base_src)
        now_lists = ruff_lists((REPO / PYPROJECT).read_text(encoding="utf-8"))
        for name, base_set in base_lists.items():
            now_set = now_lists[name]
            # `select` is the inverse ratchet: it may only grow.
            may_grow = name == "ruff select"
            failures += compare(name, base_set, now_set, may_grow=may_grow)

    base_counts, now_counts = disabled_counts(args.base), disabled_counts(None)
    for label, base_n in base_counts.items():
        now_n = now_counts[label]
        if now_n > base_n:
            failures.append(f"FAIL  {label}: {base_n} -> {now_n} disabled test(s)")
        elif now_n < base_n:
            shrank.append(f"{label} -{base_n - now_n}")

    for line in shrank:
        print(f"ok    ratchet tightened: {line}")
    for line in failures:
        print(line)
    if failures:
        print(
            f"\nExemptions may only shrink (base: {args.base}). If one of these is genuinely "
            "right, say so explicitly in the PR — do not let it ride along in a diff."
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
