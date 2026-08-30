#!/usr/bin/env python3
"""Style-token guard — the machine-enforced half of the design language
(docs/design/design-language.md §5, ADR-0030). Colors and type sizes come from
the token layer in frontend/src/styles.css; raw literals in component styles
are drift. Checks, per file:

  * hex color literals (#abc, #aabbcc, ...) and rgb()/rgba() literals
  * `font-size` declarations whose value is not a var(--fs-*) token
  * `font-family` declarations whose value is not var(--sans|--serif|--mono)
    (the three system-font faces, #143) — the value may span lines

inside `<style>` blocks of frontend .svelte files and in frontend .css files.
The :root / theme token-definition exemption applies only to styles.css — the
token layer is where raw values are supposed to live; every other stylesheet
is scanned in full, exactly like a component's `<style>` block. Known build
outputs (GENERATED_ROOTS) are not authored style code and are skipped; that
tuple is ratcheted by scripts/check_exemptions.py (must not grow).

Sanctioned exceptions (never flagged):
  * `color: #fff` — ink on accent-solid controls (only as the `color`
    property; `var(--x, #fff)` fallbacks are still flagged)
  * `rgba(0, 0, 0, 0.18)` / `rgba(0, 0, 0, 0.35)` — swatch-dot hairlines that
    must read against any user-picked swatch color
  * `--toolbar-*` custom-property definitions — the glass surface recipe
  * token definitions themselves (:root / [data-theme] blocks in styles.css)
  * `color-mix(... white/black ...)` chip-tint math passes naturally — the
    keywords `white`/`black` are not hex/rgb literals

FAILS (exit 1) on any violation — there is no per-file exemption (#1681).
Non-style paths are ignored, so it is safe to hand this the full staged-file
list (pre-commit) or a single edited file (the Claude Code PostToolUse hook).

Usage:
    python scripts/check_style_tokens.py <file> [<file> ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Build outputs the style guard never scans (the icon-font subset legitimately
# declares the icon face itself). Tail-anchored to specific known roots — never
# a bare directory-name convention, so authored code cannot dodge the guard by
# living in a folder named "generated". Extend deliberately, one root per build
# output; growth is ratcheted by scripts/check_exemptions.py.
GENERATED_ROOTS = ("frontend/src/lib/icons/generated/",)

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB_RE = re.compile(r"\brgba?\([^)]*\)")
FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([^;}]+)")
# font-family value runs to the ; or block brace and MAY span lines (the
# negated class matches newlines), so this is scanned over the whole block.
FONT_FAMILY_RE = re.compile(r"font-family\s*:\s*([^;{}]+)", re.IGNORECASE)
ALLOWED_FONT_FAMILY = {"var(--sans)", "var(--serif)", "var(--mono)", "inherit", "unset"}
STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
# Sanctioned constructs, deleted from a line before scanning it:
# accent-solid ink, swatch-dot hairlines, --toolbar-* glass definitions.
SANCTIONED_RES = [
    re.compile(r"(?<![-\w])color\s*:\s*#fff\b"),
    re.compile(r"rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0?\.(?:18|35)\s*\)"),
    re.compile(r"^\s*--toolbar-[\w-]*\s*:[^;]*"),
]


def strip_comments(css: str) -> str:
    """Blank out /* ... */ comments, preserving newlines so line numbers hold."""
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), css, flags=re.DOTALL)


def token_block_lines(css: str) -> set[int]:
    """0-based line numbers inside :root / [data-theme] token-definition blocks."""
    lines = css.split("\n")
    inside: set[int] = set()
    depth = 0
    for i, line in enumerate(lines):
        if depth == 0 and re.search(r"(?:^|[,\s]):root|\[data-theme", line) and "{" in line:
            inside.add(i)
            # Count the opener's own braces: a single-line `:root { ... }`
            # closes here, not never.
            depth = line.count("{") - line.count("}")
            continue
        if depth > 0:
            inside.add(i)
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                depth = 0
    return inside


def line_violations(line: str) -> list[tuple[str, str]]:
    """(category, message) pairs for color + font-size, one line at a time."""
    found: list[tuple[str, str]] = []
    scannable = line
    for sanctioned in SANCTIONED_RES:
        scannable = sanctioned.sub("", scannable)
    for match in HEX_RE.findall(scannable) + RGB_RE.findall(scannable):
        found.append(("style", f"color literal `{match}` - use a color token (var(--...))"))
    for match in FONT_SIZE_RE.finditer(line):
        value = match.group(1).strip()
        if "var(--fs-" in value or value in {"inherit", "unset", "0"}:
            continue
        found.append(("style", f"font-size `{value}` - use a type token (var(--fs-*))"))
    return found


def check_css(css: str, start_line: int, skip: set[int]) -> list[tuple[int, str, str]]:
    """(abs_line, category, message). Color/font-size scan per line; font-family
    scanned over the whole (comment-stripped) block so multi-line stacks match."""
    stripped = strip_comments(css)
    violations: list[tuple[int, str, str]] = []
    for i, line in enumerate(stripped.split("\n")):
        if i in skip:
            continue
        violations.extend((start_line + i, cat, message) for cat, message in line_violations(line))
    for match in FONT_FAMILY_RE.finditer(stripped):
        i = stripped.count("\n", 0, match.start())
        if i in skip:
            continue
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        if value in ALLOWED_FONT_FAMILY or not value:
            continue
        violations.append(
            (start_line + i, "font", f"font-family `{value}` - use a family token (var(--sans|--serif|--mono))")
        )
    return violations


def check_file(path: Path) -> list[tuple[int, str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".css":
        css = strip_comments(text)
        # Only the token layer itself may define raw values inside :root /
        # [data-theme] blocks; any other .css gets no such exemption.
        is_token_layer = path.as_posix().endswith("frontend/src/styles.css")
        return check_css(css, 1, token_block_lines(css) if is_token_layer else set())
    violations: list[tuple[int, str, str]] = []
    for block in STYLE_BLOCK_RE.finditer(text):
        start_line = text.count("\n", 0, block.start(1)) + 1
        violations.extend(check_css(block.group(1), start_line, set()))
    return violations


def is_checked(path: Path) -> bool:
    posix = path.as_posix()
    if "/frontend/src/" not in f"/{posix}":
        return False
    if any(f"/{root}" in f"/{posix}" for root in GENERATED_ROOTS):
        return False
    return path.suffix in {".svelte", ".css"}


def main(argv: list[str]) -> int:
    failed = False
    for raw in argv:
        path = Path(raw)
        if not is_checked(path) or not path.is_file():
            continue
        violations = check_file(path)
        if not violations:
            continue
        rel = path.as_posix()
        failed = True
        for line_no, _category, message in violations:
            print(f"FAIL  {rel}:{line_no}: {message}")
    if failed:
        print("Style values come from the token layer (docs/design/design-language.md).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
