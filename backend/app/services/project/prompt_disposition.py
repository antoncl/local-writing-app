"""The prompt disposition vocabulary and its computation (#951/#1684).

One module owns both halves of the mapping: the writer-facing shelf labels
(declared as the `disposition` computed field's options in `default_schema.py`)
and the output-handler keys the computation reads. The label vocabulary and the
handler set are pinned to `spec/prompt-disposition-labels.json`, which the
frontend suite asserts against too (promptNodes.test.ts), so neither side can
drift silently.
"""

from __future__ import annotations

from app.models.schema import PromptContextStrategy

# The five writer-facing prompt DISPOSITIONS, in shelf order — what a prompt
# does to the document, derived from its `context_strategy.output`: inline+cursor
# → Continue · inline+selection → Revise prose · conversation alone → Chat ·
# conversation with a commit → Revise entities · no invocation surface at all (a
# snippet, `finalize_scene`, or an unrecognized handler) → Snippets. The option
# order in `default_schema.py` follows this tuple and IS the shelf order: the
# default prompt view groups with `show_empty`, which renders declared options
# in this sequence. Values double as labels, matching what view predicates store.
PROMPT_DISPOSITION_CONTINUE = "Continue"
PROMPT_DISPOSITION_REVISE_PROSE = "Revise prose"
PROMPT_DISPOSITION_CHAT = "Chat"
PROMPT_DISPOSITION_REVISE_ENTITIES = "Revise entities"
PROMPT_DISPOSITION_SNIPPETS = "Snippets"
PROMPT_DISPOSITIONS: tuple[str, ...] = (
    PROMPT_DISPOSITION_CONTINUE,
    PROMPT_DISPOSITION_REVISE_PROSE,
    PROMPT_DISPOSITION_CHAT,
    PROMPT_DISPOSITION_REVISE_ENTITIES,
    PROMPT_DISPOSITION_SNIPPETS,
)

# The `runnable` computed field's single truthy value ("" when not runnable) —
# runnable = Chat disposition AND no `offer_on` anchor, i.e. launchable as a
# standalone chat (#1433). A string rather than a boolean because the view
# grammar's field ops are set ops only (`overlap`/`disjoint`/`set`/`unset` — no
# `eq`), and `isEmpty` treats `false` as non-empty, so no op could express
# "true only" over a boolean. Same shape as assistants' `listed`.
PROMPT_RUNNABLE_VALUE = "runnable"

# The closed output-handler vocabulary (ADR-0065) — the mirror of
# `OUTPUT_HANDLER_KEYS` in frontend editor-core/outputHandlers.ts, pinned by the
# shared vocabulary file. Only the `disposition` computation reads it
# backend-side; invocation itself stays a frontend registry lookup.
PROMPT_OUTPUT_HANDLER_INLINE = "inline"
PROMPT_OUTPUT_HANDLER_EXTRACT = "extract_to_node"
PROMPT_OUTPUT_HANDLER_FINALIZE = "finalize_scene"
PROMPT_OUTPUT_HANDLER_KEYS: tuple[str, ...] = (
    PROMPT_OUTPUT_HANDLER_INLINE,
    PROMPT_OUTPUT_HANDLER_EXTRACT,
    PROMPT_OUTPUT_HANDLER_FINALIZE,
)


def prompt_disposition(strategy: PromptContextStrategy | None, *, is_snippet: bool) -> str:
    """The shelf a prompt lands on (#951/#1684), from its own output contract.

    Mirrors the frontend's retired `dispositionFor` exactly (pinned by
    test_prompt_disposition + the shared vocabulary file): a snippet — by
    entry-type ancestry — has no invocation surface, whatever its config;
    `finalize_scene` is a scene action with no editor surface; an unrecognized
    handler is fail-closed uninvocable. Everything surface-less shelves under
    Snippets. A missing/empty handler is a plain conversation, which a `commit`
    capability upgrades to Revise entities.
    """
    if is_snippet:
        return PROMPT_DISPOSITION_SNIPPETS
    output = strategy.output if strategy else None
    handler = (output.handler if output else "") or ""
    if handler == PROMPT_OUTPUT_HANDLER_FINALIZE:
        return PROMPT_DISPOSITION_SNIPPETS
    if handler == PROMPT_OUTPUT_HANDLER_INLINE:
        if output is not None and output.destination == "selection":
            return PROMPT_DISPOSITION_REVISE_PROSE
        return PROMPT_DISPOSITION_CONTINUE
    if handler in ("", PROMPT_OUTPUT_HANDLER_EXTRACT):
        if output is not None and output.commit is not None:
            return PROMPT_DISPOSITION_REVISE_ENTITIES
        return PROMPT_DISPOSITION_CHAT
    return PROMPT_DISPOSITION_SNIPPETS


def prompt_runnable(disposition: str, offer_on: list[str]) -> str:
    """`runnable` iff a plain Chat with no `offer_on` anchor (#1433) — i.e.
    launchable as a standalone conversation; "" otherwise."""
    if disposition == PROMPT_DISPOSITION_CHAT and not offer_on:
        return PROMPT_RUNNABLE_VALUE
    return ""
