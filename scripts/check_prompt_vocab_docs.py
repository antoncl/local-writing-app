#!/usr/bin/env python
"""Drift gate: the prompt Jinja vocabulary registered in code must match the
symbols documented in ``docs/prompts/reference.md`` (the ADR-0060 §8 completion
contract; #1270).

The vocabulary is hand-mirrored in several places — the reference, the editor's
"?" help, and (soon) a code-completion source. Every hand-copy drifts: the
reference itself silently lost the ADR-0067 ``field_contract`` global and the
``{% do %}`` tag until #1268/#1269 fixed it by hand. This gate enforces the
invariant at the one mechanical seam — *surfaced vocabulary ≡ registered
vocabulary* — so the "added a helper, forgot the docs" class cannot land.

Scope (MVP, #1270): the symbols registered through a single seam — ``env.globals``
and ``env.filters`` (``helpers.py``) and the custom statement tags
(``templates.py``). Render-context variables (``scene``, ``inputs``, …) are not
registered through one seam and stay out of scope until the manifest phase.

Run: ``python scripts/check_prompt_vocab_docs.py`` (no arguments — it reads the
three fixed files). Exits non-zero, naming each mismatch, on drift.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompt_vocab import load_reference, names_by_kind, parse_reference  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
HELPERS = REPO / "backend" / "app" / "services" / "ai" / "helpers.py"
TEMPLATES = REPO / "backend" / "app" / "services" / "ai" / "templates.py"

# Globals wired for the machinery and never written by a template author, so not
# part of the author-facing contract. Empty today; a home for a future internal
# global, so adding one is a deliberate one-line exemption, not a silent doc gap.
INTERNAL_GLOBALS: frozenset[str] = frozenset()

# Statement tags Jinja ships built-in: documented, but not registered here.
BUILTIN_TAGS: frozenset[str] = frozenset({"include"})

# A parser that silently returns an empty set would pass this gate vacuously, so
# each side is sanity-checked to contain these known-present symbols first.
_SANITY_HELPERS: frozenset[str] = frozenset({"entry", "fields", "use", "field_contract"})


# --- code side (the registration is the source of truth) ---------------------


def _subscript_str_key(target: ast.expr, attr: str) -> str | None:
    """``env.<attr>["x"] = …`` -> ``"x"``; anything else -> ``None``."""
    if not isinstance(target, ast.Subscript):
        return None
    owner = target.value
    if not (isinstance(owner, ast.Attribute) and owner.attr == attr):
        return None
    if not (isinstance(owner.value, ast.Name) and owner.value.id == "env"):
        return None
    key = target.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value
    return None


def _env_keys(source: str, attr: str) -> set[str]:
    """All string keys assigned to ``env.<attr>[...]`` in a module's source."""
    tree = ast.parse(source)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                key = _subscript_str_key(target, attr)
                if key is not None:
                    keys.add(key)
    return keys


def _registered_tags(templates_src: str) -> set[str]:
    """Custom statement tags: ``RoleExtension.tags`` plus ``jinja2.ext.do``."""
    tags: set[str] = set()
    for body in re.findall(r"tags\s*=\s*\{([^}]*)\}", templates_src):
        tags |= set(re.findall(r'"([^"]+)"', body))
    if '"jinja2.ext.do"' in templates_src:
        tags.add("do")
    return tags


# The doc side is parsed by scripts/prompt_vocab.py — the one reference.md parser
# both this gate and the manifest generator share (so they cannot disagree).


# --- comparison --------------------------------------------------------------


class Vocab(NamedTuple):
    """The prompt vocabulary from both sides — the code registration and the doc."""

    env_globals: set[str]
    env_filters: set[str]
    tags: set[str]
    doc_helpers: set[str]
    doc_filters: set[str]


def _sanity_problems(v: Vocab) -> list[str]:
    """A broken parse must fail loudly, not pass this gate on empty sets."""
    problems: list[str] = []
    if not _SANITY_HELPERS.issubset(v.env_globals):
        problems.append(f"parser sanity: env.globals parse looks wrong ({sorted(v.env_globals)})")
    if not _SANITY_HELPERS.issubset(v.doc_helpers):
        problems.append(f"parser sanity: reference.md Helpers parse looks wrong ({sorted(v.doc_helpers)})")
    if "json" not in v.env_filters or "role" not in v.tags:
        problems.append("parser sanity: filter/tag parse looks wrong")
    return problems


def _diff_problems(v: Vocab, md: str) -> list[str]:
    problems: list[str] = []
    author_globals = v.env_globals - INTERNAL_GLOBALS
    for name in sorted(author_globals - v.doc_helpers):
        problems.append(f"helper `{name}` is registered (helpers.py) but not documented in reference.md")
    for name in sorted(v.doc_helpers - author_globals):
        problems.append(f"helper `{name}` is documented in reference.md but not registered (renamed/retired?)")
    for name in sorted(v.env_filters - v.doc_filters):
        problems.append(f"filter `{name}` is registered but not documented in reference.md")
    for name in sorted(v.doc_filters - v.env_filters):
        problems.append(f"filter `{name}` is documented but not registered (renamed/retired?)")
    for name in sorted(v.tags - BUILTIN_TAGS):
        if not re.search(r"\{%\s*" + re.escape(name) + r"\b", md):
            problems.append(f"tag `{{% {name} %}}` is registered but not documented in reference.md")
    return problems


def _collect_problems() -> list[str]:
    helpers_src = HELPERS.read_text(encoding="utf-8")
    templates_src = TEMPLATES.read_text(encoding="utf-8")
    md = load_reference()
    documented = names_by_kind(parse_reference(md))
    vocab = Vocab(
        env_globals=_env_keys(helpers_src, "globals"),
        env_filters=_env_keys(helpers_src, "filters"),
        tags=_registered_tags(templates_src),
        doc_helpers=documented["helper"],
        doc_filters=documented["filter"],
    )
    sanity = _sanity_problems(vocab)
    if sanity:
        return sanity
    return _diff_problems(vocab, md)


def main() -> int:
    problems = _collect_problems()
    if problems:
        print("Prompt vocabulary drift — code and docs/prompts/reference.md disagree:")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\nFix: update reference.md to match the registration (the code is the source of "
            "truth), or move a retired symbol to the Retired section."
        )
        return 1
    print("prompt vocabulary: reference.md matches the registered globals/filters/tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
