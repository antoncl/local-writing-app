#!/usr/bin/env python
"""Generate the bundled prompt-vocabulary manifest from ``docs/prompts/reference.md``.

Writes ``frontend/src/lib/generated/promptVocab.json`` — the single vocabulary
source the editor's code-completion (#30) and the "?" help (#1273) consume, so
neither hand-copies the reference. ``reference.md`` stays the one human-authored
source; this is a derived artifact, kept honest by two gates: the symbol set is
held to the code registration by ``check_prompt_vocab_docs.py``, and this file is
held to the reference by ``--check`` (the regen-clean gate).

    python scripts/gen_prompt_vocab.py          # regenerate the manifest
    python scripts/gen_prompt_vocab.py --check   # fail if the committed file is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompt_vocab import REPO, load_reference, parse_reference  # noqa: E402

OUT = REPO / "frontend" / "src" / "lib" / "generated" / "promptVocab.json"
_NOTE = (
    "GENERATED from docs/prompts/reference.md by scripts/gen_prompt_vocab.py — do not edit by hand. "
    "Run `python scripts/gen_prompt_vocab.py` after changing the reference."
)


def render() -> str:
    """The manifest's exact on-disk text (trailing newline, LF, unicode kept)."""
    symbols = [symbol._asdict() for symbol in parse_reference(load_reference())]
    payload = {"_generated": _NOTE, "symbols": symbols}
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = parser.parse_args(argv)

    content = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print(f"{OUT.relative_to(REPO)} is stale — run: python scripts/gen_prompt_vocab.py")
            return 1
        print(f"{OUT.relative_to(REPO)} is up to date")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
