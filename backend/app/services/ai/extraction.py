# The commit-side of a brainstorm chat (ADR-0051 S4 → ADR-0067 S2): a **cached
# continuation** that reads back the field set the chat's own lock render
# registered, instead of running a separately-contracted fresh pass.
#
# The old commit re-shipped a frozen, freshly-rendered `DEFAULT_EXTRACTION_TEMPLATE`
# (a hand-derived JSON contract, filtered by the schema's `commit.fields`
# allow-list) as its OWN pass (`chat_id=None`) — a small, uncached context, so
# the contract never sat far up a growing chat (ADR-0051 S4 §4). ADR-0067 moves
# the contract INTO the ordinary system prompt from turn 1 instead: the author's
# prompt loops `fields()` and registers what it commits to producing on the
# `field_contract` accumulator (`{% do field_contract.store(f) %}`, S1/S3),
# printing the same descriptors via `{{ field_contract.render }}` so the model
# already sees them at chat-start. Because the contract is never buried, the
# commit can CONTINUE the cached conversation — run with the chat's REAL
# `chat_id` so `expand_and_prepare_chat_blocks` reuses the cached system prefix
# + lore and appends only a short "commit now" turn (`render_extraction_envelope`
# below) that RE-STATES the field list read back from
# `ChatSession.field_contract_stored` — the exact set the lock render captured
# (`preview.py` → `AIPreviewResponse.field_contract_stored` →
# `SaveChatSessionRequest`/`ChatSession`, mirroring `used_node_ids`). No
# re-parse, no re-render, and no fresh-pass fallback — S2 settled
# continuation-only; the field re-assertion in the appended turn is what makes
# it reliable (ADR-0067 §"The list must not drift").
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models import (
    AIChatRequest,
    AIEntryPatch,
    ChatMessage,
    EntryPatchExtraction,
    ExtractEntryPatchRequest,
)
from app.services.ai.chat import run_chat_turn
from app.services.ai.field_contract import FieldContract
from app.services.project.errors import ProjectServiceError

if TYPE_CHECKING:
    from app.services.project_service import ProjectService

# The firmer cue for the one retry after a garbled first reply (below). Shown
# alongside the model's own failed reply so it can see what it did wrong — a
# chatty / cheap model often buries or omits the JSON on the first pass but
# complies when corrected. The field list isn't restated here — it was just
# given in the extraction turn immediately before this one.
RETRY_CUE = (
    "That reply could not be read as the required JSON object. Reply now with "
    "ONLY that JSON object — no preamble, no commentary, no code fences, and "
    "nothing before or after it."
)


def _body_description(project_service: ProjectService) -> str | None:
    """The `body` intrinsic field's author description (ADR-0059 §A) — used
    ONLY for the body clause's wording when body IS offered. Whether body is
    offered at all is the registered set's call (see `render_extraction_envelope`),
    never a type-level check here."""
    schema = project_service.read_metadata_schema()
    body_field = schema.fields.get("body")
    return getattr(body_field, "description", None) if body_field else None


def render_extraction_envelope(
    project_service: ProjectService,
    *,
    entry_type: str,
    creating: bool,
    stored: list[dict[str, Any]],
) -> str:
    """Build the "commit now" turn's text from the field set the chat's lock
    render registered (ADR-0067 S2) — no re-parse, no re-render.

    `stored` is `ChatSession.field_contract_stored`, the exact descriptor list
    the author's prompt looped and `{% do field_contract.store(f) %}`-ed — and
    it is the WHOLE write ceiling (ADR-0067 §4): the envelope offers exactly
    what's registered, nothing more. `body_allowed`/`title_allowed` are simply
    `"body"`/`"title"` membership in `stored` — no type-level gate. `title` is
    a NORMAL registered field, `creating` or not: a create-mode prompt gets no
    structural title carve-out — `revise-entry`'s create branch registers it
    via its own unfiltered `fields(draft_type) if f.proposable` loop, so it
    still gets one; a create prompt that doesn't register title gets none,
    which is the author's choice (and `validate_ai_entry_draft` will reject a
    titleless draft downstream — that's on the prompt, not this envelope). A
    prompt that wants body committed registers it like any other field (the
    revise built-ins' unfiltered loop); one that doesn't (the scene-summary
    prompt's `f.id == "summary"` loop) gets no body clause and no title clause
    at all — the registered set narrows EVERYTHING, including those two.
    `body` is excluded from the per-field "fields you may set" descriptor list
    even when registered: it commits as the envelope's own top-level `"body"`
    key, not a fields entry (mirrors the pre-S2 contract's `f.id != "body"`
    filter). Reuses `FieldContract` (`store`/`render`) for the descriptor
    formatting, so the lines here are byte-identical in shape to what the
    chat-start system message already showed the model (ADR-0067 §3).
    """
    stored_ids = {f.get("id") for f in stored if isinstance(f, dict)}
    body_allowed = "body" in stored_ids
    title_allowed = "title" in stored_ids
    body_description = _body_description(project_service) if body_allowed else None

    fc = FieldContract()
    for f in stored:
        if isinstance(f, dict) and f.get("id") == "body":
            continue
        fc.store(f)
    descriptors = fc.render

    shape = (
        '{"body": "<the markdown body>", "fields": {"<field id>": <value>}}'
        if body_allowed
        else '{"fields": {"<field id>": <value>}}'
    )
    lines = [
        "Extract the final result of the conversation above now, exactly as the "
        "instructions describe. Reply with ONLY a JSON object, with no preamble, "
        "no commentary, and no code fences, of exactly this shape:",
        "",
        shape,
        "",
    ]
    if body_allowed:
        clause = f'- "body": {body_description + " " if body_description else ""}'
        clause += (
            "Write the body for the new entry on that basis."
            if creating
            else (
                'Include the "body" key ONLY if the conversation actually revised '
                "the body; then give its complete revised text. OMIT the \"body\" "
                "key entirely if the body was not discussed or changed — never "
                "reconstruct it from nothing."
            )
        )
        lines.append(clause)
    fields_clause = '- "fields": '
    if creating:
        if title_allowed:
            fields_clause += 'ALWAYS include "title". '
        fields_clause += "Add any other field the conversation set, "
    else:
        fields_clause += "include a field ONLY when the conversation changed it, "
    fields_clause += (
        "keyed by its field id. For tags / multi_select give a JSON array of "
        "strings; for a select field use one of its listed options exactly; for "
        "an ordered-list field give the complete new list in its stated item "
        "shape (the whole list, in order); otherwise give the field's complete "
        "new value."
    )
    if not creating:
        if title_allowed:
            fields_clause += ' You may also propose a new "title".'
        fields_clause += " Use {} if nothing changed."
    lines.append(fields_clause)
    lines.append("")
    lines.append("The fields you may set:")
    lines.append(descriptors if descriptors else f"- (none{' beyond title/body' if body_allowed else ''})")
    lines.append("")
    lines.append(
        "Output only that JSON object. It is parsed, validated against the "
        "entry's schema, and reviewed against the current entry before anything "
        "is saved."
    )
    return "\n".join(lines)


def _coalesce_turns(turns: list[ChatMessage]) -> list[ChatMessage]:
    """Drop whitespace-only turns and merge consecutive same-role ones — the
    sanitization `build_chat_payload` does for rendered templates, which a raw
    transcript (or one we extend with cue / correction turns) would otherwise
    skip. Without it two same-role turns can land back to back — a transcript
    ending on a user turn plus the appended commit cue, or the assistant's
    failed reply next to a prior assistant turn — and the provider rejects
    that outright."""

    out: list[ChatMessage] = []
    for msg in turns:
        if not msg.content.strip():
            continue
        if out and out[-1].role == msg.role:
            out[-1] = ChatMessage(role=msg.role, content=f"{out[-1].content}\n\n{msg.content}")
        else:
            out.append(msg)
    return out


def _messages_with_cue(transcript: list[ChatMessage], cue: str) -> list[ChatMessage]:
    """The transcript plus a trailing user cue, sanitized for the provider —
    shared by the "commit now" envelope turn and the garbled-retry turn."""
    return _coalesce_turns([*transcript, ChatMessage(role="user", content=cue)])


def _constrain_to_registered_fields(patch: AIEntryPatch, allowed_ids: set[str]) -> AIEntryPatch:
    """Hard-enforce the write ceiling (ADR-0067 §4): the registered set isn't
    just what the envelope ASKS for, it's the only thing the commit may WRITE.

    `validate_ai_entry_patch_for_type` only checks the reply against the
    SCHEMA (legal, proposable, well-typed) — it has no notion of this
    prompt's own contract, so a model can still hand back a schema-valid
    field it was never asked for, or a body when body wasn't registered. This
    is the one choke point (called for both the first reply and the garbled
    retry, covering the revise and create routes alike) that drops anything
    off-contract before the diff-review or the eventual write ever sees it.
    Off-contract keys are folded into `dropped` alongside the schema
    validator's own drops, so the reviewer sees the whole picture of what the
    model tried and didn't survive — never a silent disappearance."""
    off_contract = [k for k in patch.fields if k not in allowed_ids]
    if patch.body is not None and "body" not in allowed_ids:
        off_contract = [*off_contract, "body"]
    if not off_contract:
        return patch
    return AIEntryPatch(
        body=patch.body if "body" in allowed_ids else None,
        fields={k: v for k, v in patch.fields.items() if k in allowed_ids},
        dropped=[*patch.dropped, *off_contract],
        garbled=patch.garbled,
    )


async def run_entry_patch_extraction(
    project: ProjectService,
    *,
    entry_type: str,
    creating: bool,
    request: ExtractEntryPatchRequest,
) -> EntryPatchExtraction:
    """Read the chat's registered field set back, run the commit as a cached
    continuation of that SAME chat, validate the reply, then HARD-ENFORCE the
    registered set against it (`_constrain_to_registered_fields`) — the
    schema validator alone would let an off-contract but schema-legal field
    through.

    Shared by the revise and create routes so the two never diverge on how the
    turn is run, costed, or constrained. `creating` selects the envelope's
    wording; the validated patch is scoped to `entry_type` either way
    (kind-neutral, ADR-0048 §5). `request.chat_id` is the chat's real id
    (ADR-0067 S2) — `expand_and_prepare_chat_blocks` reuses its cached system
    prefix + lore, so only the appended envelope + transcript are freshly
    billed. The extraction turn's cost rides back on `cost_usd` for the caller
    to attribute to the session, exactly as a streamed turn's delta is."""

    try:
        chat = project.read_chat_session(request.chat_id)
    except ProjectServiceError as exc:
        # A stale / deleted chat — surface it as a clean failure the pane
        # shows, not an unhandled 500 (mirrors how the old contract-render
        # failure was handled before it retired).
        return EntryPatchExtraction(
            patch=None,
            cost_usd=None,
            ok=False,
            error=f"Couldn't read the chat to commit: {exc.message}",
        )

    envelope = render_extraction_envelope(
        project,
        entry_type=entry_type,
        creating=creating,
        stored=chat.field_contract_stored,
    )
    # The write ceiling both the envelope's ASK and the post-validate ENFORCE
    # read from — the same `stored` set, so they can't drift (ADR-0067 §4).
    allowed_ids = {f.get("id") for f in chat.field_contract_stored if isinstance(f, dict)}
    turn_messages = _messages_with_cue(request.messages, envelope)

    chat_reply = await run_chat_turn(
        project,
        AIChatRequest(
            assistant_id=request.assistant_id,
            system_prompt=chat.system_prompt,
            messages=turn_messages,
            chat_id=request.chat_id,
        ),
    )
    if not chat_reply.ok or not (chat_reply.content or "").strip():
        return EntryPatchExtraction(
            patch=None,
            cost_usd=chat_reply.cost_usd,
            ok=False,
            error=chat_reply.error or "The model returned nothing to commit.",
        )
    patch = project.validate_ai_entry_patch_for_type(entry_type, chat_reply.content)
    patch = _constrain_to_registered_fields(patch, allowed_ids)
    cost = chat_reply.cost_usd

    # One firm retry on a garbled reply (#1036): re-run with the model's own
    # failed reply plus a stricter cue, so a chatty / cheap model that buried or
    # omitted the JSON gets a chance to correct itself. Costs one extra call, and
    # only on failure. A second garble is terminal — the caller reports it.
    if patch.garbled:
        retry = await run_chat_turn(
            project,
            AIChatRequest(
                assistant_id=request.assistant_id,
                system_prompt=chat.system_prompt,
                messages=_coalesce_turns(
                    [
                        *turn_messages,
                        ChatMessage(role="assistant", content=chat_reply.content),
                        ChatMessage(role="user", content=RETRY_CUE),
                    ]
                ),
                chat_id=request.chat_id,
            ),
        )
        cost = _sum_costs(cost, retry.cost_usd)
        if retry.ok and (retry.content or "").strip():
            patch = project.validate_ai_entry_patch_for_type(entry_type, retry.content)
            patch = _constrain_to_registered_fields(patch, allowed_ids)
    return EntryPatchExtraction(patch=patch, cost_usd=cost, ok=True)


def _sum_costs(a: float | None, b: float | None) -> float | None:
    """Add two optional per-turn costs — None means 'unknown / unpriced'."""
    if a is None:
        return b
    if b is None:
        return a
    return a + b
