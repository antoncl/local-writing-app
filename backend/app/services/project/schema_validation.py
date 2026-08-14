"""Soft-validation for a prompt entry type's output disposition (ADR-0054 §1/§2,
#954, Lever 2). Split out of `schema.py`, which sits at the file-size cap; the
closed vocabularies these check against (`OUTPUT_KINDS` / `COMMIT_REVIEW_MODES` /
`INLINE_OUTPUT_KINDS`) live in `default_schema`."""

from __future__ import annotations

from app.models.schema import PromptOutput
from app.services.project.default_schema import (
    COMMIT_REVIEW_MODES,
    INLINE_OUTPUT_KINDS,
    OUTPUT_KINDS,
)


def validate_prompt_output(entry_type_id: str, output: PromptOutput | None) -> list[str]:
    """The disposition `kind` (a closed vocabulary), an optional `commit` (only
    under `chat_panel`), and an optional `on_accept` mark-stamp (only under an
    inline disposition) of one prompt type's `output`. An unset/empty kind is
    legitimate (a snippet, or a prompt with no output). Soft errors like the rest
    of schema validation — a hand-edited layer stays readable, and the save paths
    surface them."""
    if not output:
        return []
    errors: list[str] = []
    if output.kind and output.kind not in OUTPUT_KINDS:
        errors.append(
            f"Entry type {entry_type_id} declares output kind '{output.kind}', "
            f"not one of the known dispositions ({', '.join(OUTPUT_KINDS)})."
        )
    if output.commit is not None:
        if output.kind != "chat_panel":
            errors.append(
                f"Entry type {entry_type_id} declares a commit but its output kind is "
                f"'{output.kind or 'unset'}'; only chat_panel output can carry a commit."
            )
        if output.commit.review not in COMMIT_REVIEW_MODES:
            errors.append(
                f"Entry type {entry_type_id} declares commit review '{output.commit.review}', "
                f"not one of the known modes ({', '.join(COMMIT_REVIEW_MODES)})."
            )
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
