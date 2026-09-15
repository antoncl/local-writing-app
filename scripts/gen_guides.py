#!/usr/bin/env python
"""Bundle the in-app user guides from ``docs/`` into a generated frontend module.

The guide viewer (#1271) renders these guides in a pane. ``docs/`` stays the
single source — a human edits the doc, never a frontend copy — and the bundle is
generated from it and held regen-clean by ``--check`` (pre-commit + CI), the same
drift-safe pattern as the vocabulary manifest (#1270).

    python scripts/gen_guides.py           # regenerate the bundle
    python scripts/gen_guides.py --check    # fail if the committed file is stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "frontend" / "src" / "lib" / "generated" / "guides.ts"
PRECOMMIT = REPO / ".pre-commit-config.yaml"

# The guides surfaced in-app, in display order. Each is {id, title, source doc}
# plus an optional `kind`: "guide" (narrative, the default) or "reference" (a
# terse lookup contract). GuideView groups references under their own picker
# heading so a dense contract doesn't read as a learning guide (#1296).
# Getting started is first, so it is the viewer's default landing guide (#172).
# The prompt editor's "?" no longer relies on order — it asks the viewer for the
# "writing-prompts" guide by id (see GuideView / guideTarget, #1295).
# Narrative order is a reading flow: intro, then world-building (lore, its fields,
# mid-scene changes), then organizing (views) and plotting, then turning AI on and
# the AI guides (prompts, context, roleplay); references last.
GUIDES = [
    {"id": "getting-started", "title": "Getting started", "source": "docs/getting-started.md"},
    {"id": "lore", "title": "Lore", "source": "docs/lore.md"},
    {"id": "custom-fields", "title": "Custom fields", "source": "docs/custom-fields.md"},
    {"id": "mutations", "title": "Mutations", "source": "docs/mutations.md"},
    {"id": "views", "title": "Views", "source": "docs/views.md"},
    {"id": "plotting", "title": "Plotting", "source": "docs/plotting.md"},
    {"id": "ai-setup", "title": "Turning on AI", "source": "docs/ai-setup.md"},
    {"id": "ollama-context", "title": "Ollama context", "source": "docs/ollama-context.md"},
    {"id": "writing-prompts", "title": "Writing prompts", "source": "docs/prompts/guide.md"},
    {"id": "context-picker", "title": "Context picker", "source": "docs/context-picker.md"},
    {"id": "roleplay", "title": "Roleplay", "source": "docs/roleplay.md"},
    {"id": "reference", "title": "Prompt reference", "source": "docs/prompts/reference.md", "kind": "reference"},
]

_HEADER = (
    "// GENERATED from docs/ by scripts/gen_guides.py — do not edit by hand.\n"
    "// Run `python scripts/gen_guides.py` after changing a source guide.\n"
)

# A markdown image whose target is a local `.svg`, alone on its line. Diagrams
# live as committed `.svg` files that GitHub renders as images; the in-app viewer
# can't load images (the bundle copies no assets), so these refs are spliced
# inline at bundle time. One source of truth per diagram, both surfaces (#1967).
_SVG_IMG = re.compile(r"(?m)^!\[[^\]]*\]\((?P<path>[^)]+\.svg)\)[ \t]*$")


def _svg_paths(markdown: str, source: Path) -> list[Path]:
    """Absolute paths of every `![alt](*.svg)` the markdown references."""
    return [(source.parent / m.group("path")).resolve() for m in _SVG_IMG.finditer(markdown)]


def _inline_svgs(markdown: str, source: Path) -> str:
    """Splice each `![alt](*.svg)` reference's file contents inline.

    GuideView renders with a plain ``new Marked()`` and no sanitiser, so a raw
    ``<svg>`` survives only wrapped in a ``<div>`` with the opening tag alone on
    its line and no blank lines inside — the shape Marked passes through as HTML
    instead of escaping (GuideView.svg.test.ts pins this). The committed ``.svg``
    files are authored in exactly that no-blank-line shape.
    """

    def repl(match: re.Match[str]) -> str:
        svg = (source.parent / match.group("path")).resolve().read_text(encoding="utf-8").strip()
        return f"<div>\n{svg}\n</div>"

    return _SVG_IMG.sub(repl, markdown)


def _referenced_svgs() -> list[str]:
    """Repo-relative POSIX paths of every SVG the guides inline, de-duplicated.

    Skips a source that doesn't exist: discovery has nothing to read there, and a
    genuinely missing bundled file fails loudly at ``render()`` while the
    string-based filter check still flags it.
    """
    seen: dict[str, None] = {}
    for guide in GUIDES:
        src = REPO / guide["source"]
        if not src.exists():
            continue
        for svg in _svg_paths(src.read_text(encoding="utf-8"), src):
            seen[svg.relative_to(REPO).as_posix()] = None
    return list(seen)


def render() -> str:
    """The bundle's exact on-disk text (a typed TS module, LF, unicode kept)."""
    bundle = [
        {
            "id": guide["id"],
            "title": guide["title"],
            "kind": guide.get("kind", "guide"),
            "markdown": _inline_svgs(
                (REPO / guide["source"]).read_text(encoding="utf-8"),
                REPO / guide["source"],
            ),
        }
        for guide in GUIDES
    ]
    body = json.dumps(bundle, ensure_ascii=False, indent=2)
    return (
        _HEADER
        + '\nexport type Guide = { id: string; title: string; kind: "guide" | "reference"; markdown: string };\n\n'
        + f"export const guides: Guide[] = {body};\n"
    )


def _guides_filter_pattern() -> str | None:
    """The `files:` regex of the guides-bundle pre-commit hook, or None.

    Stdlib-only (no PyYAML) so this stays runnable under any Python: isolate the
    hook block from its `- id:` line to the next hook, then read its `files:`.
    """
    text = PRECOMMIT.read_text(encoding="utf-8")
    anchor = re.search(r"^ *- id: guides-bundle$", text, re.MULTILINE)
    if anchor is None:
        return None
    tail = text[anchor.end() :]
    nxt = re.search(r"^ *- id: ", tail, re.MULTILINE)
    block = tail if nxt is None else tail[: nxt.start()]
    files = re.search(r"^ *files: (.+)$", block, re.MULTILINE)
    return files.group(1).strip() if files else None


def coverage_errors() -> list[str]:
    """Every bundled source the guides-bundle `files:` filter fails to match.

    Keeps two lists honest: `GUIDES` here and the pre-commit trigger filter. The
    hook only runs locally on files the filter matches, so a bundled source
    missing from it silently skips the local regen-clean gate — drift only CI
    would catch (#1537). Adding a source without widening the filter fails here.
    """
    pattern = _guides_filter_pattern()
    if pattern is None:
        return [f"could not find the guides-bundle `files:` pattern in {PRECOMMIT.name}"]
    try:
        matches = re.compile(pattern)
    except re.error as exc:
        return [f"guides-bundle `files:` is not valid regex: {exc}"]
    errors = [
        f"guides-bundle `files:` filter misses bundled source {guide['source']} — "
        f"add it to the filter in {PRECOMMIT.name}"
        for guide in GUIDES
        if not matches.search(guide["source"])
    ]
    # SVGs are inputs too: editing one must retrigger the hook, or the regen only
    # trips CI (#1537). An inlined SVG missing from the filter fails here.
    errors += [
        f"guides-bundle `files:` filter misses inlined SVG {svg} — "
        f"add it to the filter in {PRECOMMIT.name}"
        for svg in _referenced_svgs()
        if not matches.search(svg)
    ]
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = parser.parse_args(argv)

    content = render()
    if args.check:
        errors: list[str] = []
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            errors.append(f"{OUT.relative_to(REPO)} is stale — run: python scripts/gen_guides.py")
        errors.extend(coverage_errors())
        if errors:
            print("\n".join(errors))
            return 1
        print(f"{OUT.relative_to(REPO)} is up to date; guides-bundle filter covers all sources")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)} ({len(GUIDES)} guides)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
