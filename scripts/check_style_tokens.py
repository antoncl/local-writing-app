#!/usr/bin/env python3
"""Style-token guard — the machine-enforced half of the design language
(docs/design/design-language.md §5, ADR-0030). Colors and type sizes come from
the token layer in frontend/src/styles.css; raw literals in component styles
are drift. Checks, per file:

  * hex color literals (#abc, #aabbcc, ...) and rgb()/rgba() literals
  * `font-size` declarations whose value is not a var(--fs-*) token

inside `<style>` blocks of frontend .svelte files and in styles.css outside
the :root / theme token-definition blocks.

Sanctioned exceptions (never flagged):
  * `color: #fff` — ink on accent-solid controls (only as the `color`
    property; `var(--x, #fff)` fallbacks are still flagged)
  * `rgba(0, 0, 0, 0.18)` / `rgba(0, 0, 0, 0.35)` — swatch-dot hairlines that
    must read against any user-picked swatch color
  * `--toolbar-*` custom-property definitions — the glass surface recipe
  * token definitions themselves (:root / [data-theme] blocks in styles.css)
  * `color-mix(... white/black ...)` chip-tint math passes naturally — the
    keywords `white`/`black` are not hex/rgb literals

FAILS (exit 1) on any violation unless the file is grandfathered below; a
grandfathered file still warns (exit 0) so the debt stays visible. Non-style
paths are ignored, so it is safe to hand this the full staged-file list
(pre-commit) or a single edited file (the Claude Code PostToolUse hook).

Usage:
    python scripts/check_style_tokens.py <file> [<file> ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Files with pre-token style debt, exempt from the hard FAIL until they are
# restyled under #125. They still warn. Remove an entry once its file is
# clean — this list only shrinks. Stored repo-relative with forward slashes;
# matched against the path tail.
GRANDFATHERED = {
    "frontend/src/components/chrome/TopBar.svelte",
    "frontend/src/components/dialogs/AssistantTagManager.svelte",
    "frontend/src/components/dialogs/ConfirmModal.svelte",
    "frontend/src/components/dialogs/DirectoryPickerModal.svelte",
    "frontend/src/components/dialogs/GroupsManagerDialog.svelte",
    "frontend/src/components/dialogs/MachineSettingsDialog.svelte",
    "frontend/src/components/dialogs/Modal.svelte",
    "frontend/src/components/dialogs/TagManagerDialog.svelte",
    "frontend/src/components/editor/BacklinksPanel.svelte",
    "frontend/src/components/editor/InputsDialog.svelte",
    "frontend/src/components/editor/MetadataPanel.svelte",
    "frontend/src/components/editor/MutationScrubber.svelte",
    "frontend/src/components/editor/NodeEditor.svelte",
    "frontend/src/components/panes/Assistants.svelte",
    "frontend/src/components/panes/Chats.svelte",
    "frontend/src/components/panes/Mutations.svelte",
    "frontend/src/components/panes/Project.svelte",
    "frontend/src/components/panes/Todo.svelte",
    "frontend/src/components/panes/Tree.svelte",
    "frontend/src/styles.css",
}

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB_RE = re.compile(r"\brgba?\([^)]*\)")
FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([^;}]+)")
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
            depth = 1
            inside.add(i)
            continue
        if depth > 0:
            inside.add(i)
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                depth = 0
    return inside


def line_violations(line: str) -> list[str]:
    found: list[str] = []
    scannable = line
    for sanctioned in SANCTIONED_RES:
        scannable = sanctioned.sub("", scannable)
    for match in HEX_RE.findall(scannable) + RGB_RE.findall(scannable):
        found.append(f"color literal `{match}` - use a color token (var(--...))")
    for match in FONT_SIZE_RE.finditer(line):
        value = match.group(1).strip()
        if "var(--fs-" in value or value in {"inherit", "unset", "0"}:
            continue
        found.append(f"font-size `{value}` - use a type token (var(--fs-*))")
    return found


def check_css(css: str, start_line: int, skip: set[int]) -> list[tuple[int, str]]:
    violations: list[tuple[int, str]] = []
    for i, line in enumerate(strip_comments(css).split("\n")):
        if i in skip:
            continue
        violations.extend((start_line + i, message) for message in line_violations(line))
    return violations


def check_file(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".css":
        css = strip_comments(text)
        return check_css(css, 1, token_block_lines(css))
    violations: list[tuple[int, str]] = []
    for block in STYLE_BLOCK_RE.finditer(text):
        start_line = text.count("\n", 0, block.start(1)) + 1
        violations.extend(check_css(block.group(1), start_line, set()))
    return violations


def is_checked(path: Path) -> bool:
    posix = path.as_posix()
    if "/frontend/src/" not in f"/{posix}":
        return False
    return path.suffix == ".svelte" or posix.endswith("frontend/src/styles.css")


def is_grandfathered(posix_path: str) -> bool:
    return any(posix_path.endswith(entry) for entry in GRANDFATHERED)


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
        if is_grandfathered(rel):
            print(f"warn  {rel}: {len(violations)} non-token style value(s) (grandfathered - clean up when you next work here).")
            continue
        failed = True
        for line_no, message in violations:
            print(f"FAIL  {rel}:{line_no}: {message}")
    if failed:
        print("Style values come from the token layer (docs/design/design-language.md).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
