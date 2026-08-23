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
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "frontend" / "src" / "lib" / "generated" / "guides.ts"

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
    {"id": "writing-prompts", "title": "Writing prompts", "source": "docs/prompts/guide.md"},
    {"id": "context-picker", "title": "Context picker", "source": "docs/context-picker.md"},
    {"id": "roleplay", "title": "Roleplay", "source": "docs/roleplay.md"},
    {"id": "reference", "title": "Prompt reference", "source": "docs/prompts/reference.md", "kind": "reference"},
]

_HEADER = (
    "// GENERATED from docs/ by scripts/gen_guides.py — do not edit by hand.\n"
    "// Run `python scripts/gen_guides.py` after changing a source guide.\n"
)


def render() -> str:
    """The bundle's exact on-disk text (a typed TS module, LF, unicode kept)."""
    bundle = [
        {
            "id": guide["id"],
            "title": guide["title"],
            "kind": guide.get("kind", "guide"),
            "markdown": (REPO / guide["source"]).read_text(encoding="utf-8"),
        }
        for guide in GUIDES
    ]
    body = json.dumps(bundle, ensure_ascii=False, indent=2)
    return (
        _HEADER
        + '\nexport type Guide = { id: string; title: string; kind: "guide" | "reference"; markdown: string };\n\n'
        + f"export const guides: Guide[] = {body};\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = parser.parse_args(argv)

    content = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print(f"{OUT.relative_to(REPO)} is stale — run: python scripts/gen_guides.py")
            return 1
        print(f"{OUT.relative_to(REPO)} is up to date")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)} ({len(GUIDES)} guides)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
