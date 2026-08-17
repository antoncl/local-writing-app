"""Soft-validation for a prompt entry type's output disposition (ADR-0054 §1/§2,
#954, Lever 2). Split out of `schema.py`, which sits at the file-size cap; the
closed vocabularies these check against (`OUTPUT_KINDS` / `COMMIT_REVIEW_MODES` /
`INLINE_OUTPUT_KINDS`) live in `default_schema`."""

from __future__ import annotations

import re

from app.models.schema import PromptOutput
from app.services.project.default_schema import (
    COMMIT_REVIEW_MODES,
    INLINE_OUTPUT_KINDS,
    OUTPUT_KINDS,
)

# Entry-type identity is the kind-qualified FQN `kind:key` (#77). The key may nest
# (`kind:seg:seg…`, e.g. `prompt:revise:scene`) — the extra colons are a pure naming
# separator with no tie to the `parent:` chain (#600). The kind is always the first
# segment (group 1); each segment starts with a letter, then letters/digits/underscores.
# Shared by the entry-type write path (`schema.py`) and the definition validator
# (`schema_definition_validation.py`).
ENTRY_TYPE_FQN_RE = re.compile(r"([a-z][a-z0-9_]*):([A-Za-z][A-Za-z0-9_]*(?::[A-Za-z][A-Za-z0-9_]*)*)")


def _commit_output_errors(
    entry_type_id: str,
    output: PromptOutput,
    known_entry_types: set[str] | None,
) -> list[str]:
    """The optional `commit` block of a prompt's output (ADR-0054 §2 / ADR-0063):
    it rides only on `chat_panel`, its `review` is a closed vocabulary, and its
    `target` (the entry_type the commit creates) is a well-formed FQN that — when
    the caller threads `known_entry_types` — names a defined type."""
    commit = output.commit
    if commit is None:
        return []
    errors: list[str] = []
    if output.kind != "chat_panel":
        errors.append(
            f"Entry type {entry_type_id} declares a commit but its output kind is "
            f"'{output.kind or 'unset'}'; only chat_panel output can carry a commit."
        )
    if commit.review not in COMMIT_REVIEW_MODES:
        errors.append(
            f"Entry type {entry_type_id} declares commit review '{commit.review}', "
            f"not one of the known modes ({', '.join(COMMIT_REVIEW_MODES)})."
        )
    # `commit.target` (ADR-0063 S1) names the entry_type the commit CREATES. Shape
    # is checked always (a malformed FQN is a typo); existence only when the caller
    # threads the schema's known ids.
    target = (commit.target or "").strip()
    if target and not ENTRY_TYPE_FQN_RE.fullmatch(target):
        errors.append(
            f"Entry type {entry_type_id} declares commit target '{target}', "
            f"which is not a valid entry-type id (kind:key)."
        )
    elif target and known_entry_types is not None and target not in known_entry_types:
        errors.append(
            f"Entry type {entry_type_id} declares commit target '{target}', "
            f"which is not a defined entry type."
        )
    return errors


def validate_prompt_output(
    entry_type_id: str,
    output: PromptOutput | None,
    known_entry_types: set[str] | None = None,
) -> list[str]:
    """The disposition `kind` (a closed vocabulary), an optional `commit` (only
    under `chat_panel`), and an optional `on_accept` mark-stamp (only under an
    inline disposition) of one prompt type's `output`. An unset/empty kind is
    legitimate (a snippet, or a prompt with no output). Soft errors like the rest
    of schema validation — a hand-edited layer stays readable, and the save paths
    surface them.

    `known_entry_types`, when passed, is the merged schema's defined entry-type
    ids; a `commit.target` (ADR-0063 S1) is then checked to exist. Omit it (the
    default) to validate `target` shape only — the extractor degrades an unknown
    target to a body-only contract, so existence is a lint, not a safety gate."""
    if not output:
        return []
    errors: list[str] = []
    if output.kind and output.kind not in OUTPUT_KINDS:
        errors.append(
            f"Entry type {entry_type_id} declares output kind '{output.kind}', "
            f"not one of the known dispositions ({', '.join(OUTPUT_KINDS)})."
        )
    errors.extend(_commit_output_errors(entry_type_id, output, known_entry_types))
    # `on_accept` stamps a mark on an accepted INLINE suggestion, so it rides only on
    # an inline disposition (never chat_panel, which has no accept gesture) and must
    # name both the mark and the input it reads.
    if output.on_accept is not None:
        if output.kind not in INLINE_OUTPUT_KINDS:
            errors.append(
                f"Entry type {entry_type_id} declares an on_accept mark but its output kind is "
                f"'{output.kind or 'unset'}'; only an inline disposition "
                f"({', '.join(INLINE_OUTPUT_KINDS)}) stamps a mark on accept."
            )
        if not output.on_accept.mark or not output.on_accept.from_input:
            errors.append(
                f"Entry type {entry_type_id} declares an on_accept but is missing 'mark' or 'from_input'."
            )
    return errors
