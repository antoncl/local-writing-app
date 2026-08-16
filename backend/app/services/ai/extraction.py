# The commit-side of a brainstorm chat (ADR-0051 S4): a **fresh, self-instructed
# extraction** that replaces the old finalize-replay.
#
# The old commit re-shipped the frozen seed system prompt (which carried the JSON
# format contract) plus the whole transcript plus a terse "finalize" cue — so the
# contract sat far up a growing context and got less reliable the longer the chat
# ran (ADR §4). Here the contract is rebuilt from the schema every time and run as
# its own pass: the transcript is pure input, the format lives at the top of a
# small fresh context. Length-independent by construction.
#
# The contract is a Jinja template rendered through the ordinary preview pipeline,
# so it reuses `field_catalog` and the entry helpers rather than re-deriving the
# field descriptors in Python (the seed templates' item-shape logic is non-trivial
# — one source of it, not two). `DEFAULT_EXTRACTION_TEMPLATE` is the ONE generated
# contract (body + all proposable fields); a prompt that needs a narrower shape sets
# `commit.fields`, an allow-list that filters which descriptors the template
# enumerates (ADR-0054 §2). `body` is just another field in that list, so its absence
# makes the contract fields-only (e.g. the scene-summary prompt, `["summary"]`). This
# replaces ADR-0051 S4's arbitrary-Jinja `output.extract` override — one contract, a
# declarative filter, no escape hatch.
from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import (
    AIChatRequest,
    ChatMessage,
    EntryPatchExtraction,
    ExtractEntryPatchRequest,
)
from app.services.ai.chat import run_chat_turn
from app.services.ai.preview import PreviewError, build_chat_payload, build_preview

if TYPE_CHECKING:
    from app.services.project_service import ProjectService

# The user turn that triggers the extraction. The format contract is the system
# prompt (rendered below); this only says "do it now". Mirrors the intent of the
# old FINALIZE_INSTRUCTION, but the contract no longer rides the seed prompt.
EXTRACT_CUE = (
    "Extract the final result of the conversation above now, exactly as the "
    "instructions describe — reply with ONLY the JSON, no preamble, no commentary, "
    "no code fences."
)

# The firmer cue for the one retry after a garbled first reply (below). Shown
# alongside the model's own failed reply so it can see what it did wrong — a
# chatty / cheap model often buries or omits the JSON on the first pass but
# complies when corrected.
RETRY_CUE = (
    "That reply could not be read as the required JSON object. Reply now with "
    "ONLY that JSON object — no preamble, no commentary, no code fences, and "
    "nothing before or after it."
)

# The generated contract (ADR-0051 S4; filtered by ADR-0054 §2). By default it names
# the body + every proposable field of the target type, straight from `field_catalog`.
# `commit.fields` (passed in as `input.commit_fields`) narrows it: the field loop
# enumerates only allow-listed descriptors, and `input.body_allowed` /
# `input.title_allowed` gate the body and title clauses (both are `true` when no
# allow-list is given, so the unfiltered contract renders exactly as before). The
# field-descriptor / item-shape rendering is intentionally identical to the seed
# templates it replaces, so a `list`/`select` field is described the same way it always
# was. `input.entry_type` is the target FQN; `input.creating` distinguishes a
# from-scratch draft (title required) from a revise (title optional).
DEFAULT_EXTRACTION_TEMPLATE = """{% role "system" %}
You are extracting the final result of a brainstorm into a structured patch. The conversation that follows is your only input — read it and produce the result the author and you converged on.

Reply with ONLY a JSON object, with no preamble, no commentary, and no code fences, of exactly this shape:

{% if input.body_allowed %}{"body": "<the markdown body>", "fields": {"<field id>": <value>}}{% else %}{"fields": {"<field id>": <value>}}{% endif %}

{% if input.body_allowed %}- "body": {% if input.body_description %}{{ input.body_description }} {% endif %}{% if input.creating %}Write the body for the new entry on that basis.{% else %}Include the "body" key ONLY if the conversation actually revised the body; then give its complete revised text. OMIT the "body" key entirely if the body was not discussed or changed — never reconstruct it from nothing.{% endif %}
{% endif %}- "fields": {% if input.creating %}{% if input.title_allowed %}ALWAYS include "title". {% endif %}Add any other field the conversation set, {% else %}include a field ONLY when the conversation changed it, {% endif %}keyed by its field id. For tags / multi_select give a JSON array of strings; for a select field use one of its listed options exactly; for an ordered-list field give the complete new list in its stated item shape (the whole list, in order); otherwise give the field's complete new value.{% if not input.creating %}{% if input.title_allowed %} You may also propose a new "title".{% endif %} Use {} if nothing changed.{% endif %}

The fields you may set:
{% for f in field_catalog(input.entry_type) if f.id != "body" and (input.commit_fields is none or f.id in input.commit_fields) %}
- {{ f.id }} ({{ f.label }}) — {{ f.type }}{% if f.options %}; one of: {{ f.options | join(", ") }}{% endif %}{% if f.description %} — {{ f.description }}{% endif %}{% if f.get("items") %}{% if f.item_scalar %}; a JSON array of {{ f["items"][0].type }} values{% if f["items"][0].options %}, each one of: {{ f["items"][0].options | join(", ") }}{% endif %}{% else %}; a JSON array of objects, each with keys: {% for m in f["items"] %}{{ m.key }} ({{ m.type }}{% if m.options %}; one of: {{ m.options | join(", ") }}{% endif %}){% if not loop.last %}, {% endif %}{% endfor %}{% endif %}{% endif %}
{% else %}
- (none{% if input.body_allowed %} beyond title/body{% endif %})
{% endfor %}

Output only that JSON object. It is parsed, validated against the entry's schema, and reviewed against the current entry before anything is saved.
{% endrole %}"""


def render_extraction_contract(
    project_service: ProjectService,
    *,
    entry_type: str,
    creating: bool,
    commit_fields: list[str] | None = None,
) -> str:
    """Render the extraction contract (the system prompt) for ``entry_type``.

    ``commit_fields`` is the prompt's ``commit.fields`` allow-list (ADR-0054 §2):
    None ⇒ the full contract (body + every proposable field); a list ⇒ only those
    targets, with ``body`` counted as a field (so its absence yields a fields-only
    contract). Rendered through `build_preview` so `field_catalog` and the entry
    helpers are available exactly as in the seed templates; the system block is the
    contract. Raises `PreviewError` on a broken template (the route surfaces it).
    """

    # `body` is an intrinsic field (ADR-0059): resolve its description — which
    # tells the model what the body is FOR, replacing the old hardcoded "complete
    # markdown body" prose that invited the field dump (§D) — and its
    # `ai_proposable` flag, which gates the body clause (§E). The clause is also
    # gated on the target type actually HAVING a body (§B): a bodiless type gets
    # a fields-only contract. Body's description / flag are global (per-layer,
    # not per-type), read from the resolved field registry.
    schema = project_service.read_metadata_schema()
    body_field = schema.fields.get("body")
    definition = schema.entry_types.get(entry_type)
    # Suppress the body clause only for a KNOWN, bodiless type. An UNKNOWN type
    # (no definition) keeps the body clause — the existing graceful degradation
    # (`_field_catalog` returns no fields, so the contract is body-only).
    body_type_ok = definition is None or "body" in definition.fields
    body_proposable = bool(getattr(body_field, "ai_proposable", True)) if body_field else True
    body_description = getattr(body_field, "description", None) if body_field else None
    body_allowed = (commit_fields is None or "body" in commit_fields) and body_proposable and body_type_ok
    # Create mode ALWAYS requires a title (`validate_ai_entry_draft` rejects a
    # draft without one), so a `commit.fields` allow-list can never suppress the
    # title clause there — only a revise's allow-list can (title is optional then).
    title_allowed = creating or commit_fields is None or "title" in commit_fields
    rendered, _ = build_preview(
        project_service=project_service,
        template_source=DEFAULT_EXTRACTION_TEMPLATE,
        target_scene_id="",
        session_id=None,
        inputs={
            "entry_type": entry_type,
            "creating": creating,
            "commit_fields": commit_fields,
            "body_allowed": body_allowed,
            "body_description": body_description,
            "title_allowed": title_allowed,
        },
        text_before="",
        text_after="",
        commit=False,
    )
    system_prompt, _ = build_chat_payload(rendered)
    return system_prompt


def _coalesce_turns(turns: list[ChatMessage]) -> list[ChatMessage]:
    """Drop whitespace-only turns and merge consecutive same-role ones — the
    sanitization `build_chat_payload` does for rendered templates, which a raw
    transcript (or one we extend with cue / correction turns) would otherwise
    skip. Without it two same-role turns can land back to back — a transcript
    ending on a user turn plus the user cue, or the assistant's failed reply
    next to a prior assistant turn — and the provider rejects that outright."""

    out: list[ChatMessage] = []
    for msg in turns:
        if not msg.content.strip():
            continue
        if out and out[-1].role == msg.role:
            out[-1] = ChatMessage(role=msg.role, content=f"{out[-1].content}\n\n{msg.content}")
        else:
            out.append(msg)
    return out


def _messages_with_extract_cue(transcript: list[ChatMessage]) -> list[ChatMessage]:
    """The transcript plus the extract cue, sanitized for the provider."""
    return _coalesce_turns([*transcript, ChatMessage(role="user", content=EXTRACT_CUE)])


async def run_entry_patch_extraction(
    project: ProjectService,
    *,
    entry_type: str,
    creating: bool,
    request: ExtractEntryPatchRequest,
) -> EntryPatchExtraction:
    """Render the fresh contract, run one extraction turn, validate its reply.

    Shared by the revise and create routes so the two never diverge on how the
    turn is run or costed. `creating` selects the contract's title handling; the
    validated patch is scoped to `entry_type` either way (kind-neutral, ADR-0048
    §5). The extraction turn's cost rides back on `cost_usd` for the caller to
    attribute to the session, exactly as a streamed turn's delta is."""

    try:
        contract = render_extraction_contract(
            project,
            entry_type=entry_type,
            creating=creating,
            commit_fields=request.commit_fields,
        )
    except PreviewError as exc:
        # A broken contract template — the generated contract failing to render
        # (e.g. a schema the field-catalog helper can't walk). Surface it as a
        # clean failure the pane shows, not an unhandled 500 (mirrors how
        # `ai_preview` and `ai_generate` handle a PreviewError from the same renderer).
        return EntryPatchExtraction(
            patch=None,
            cost_usd=None,
            ok=False,
            error=f"Couldn't render the extraction prompt: {exc.message}",
        )
    chat = await run_chat_turn(
        project,
        AIChatRequest(
            assistant_id=request.assistant_id,
            system_prompt=contract,
            messages=_messages_with_extract_cue(request.messages),
            chat_id=None,
        ),
    )
    if not chat.ok or not (chat.content or "").strip():
        return EntryPatchExtraction(
            patch=None,
            cost_usd=chat.cost_usd,
            ok=False,
            error=chat.error or "The model returned nothing to commit.",
        )
    patch = project.validate_ai_entry_patch_for_type(entry_type, chat.content)
    cost = chat.cost_usd

    # One firm retry on a garbled reply (#1036): re-run with the model's own
    # failed reply plus a stricter cue, so a chatty / cheap model that buried or
    # omitted the JSON gets a chance to correct itself. Costs one extra call, and
    # only on failure. A second garble is terminal — the caller reports it.
    if patch.garbled:
        retry = await run_chat_turn(
            project,
            AIChatRequest(
                assistant_id=request.assistant_id,
                system_prompt=contract,
                messages=_coalesce_turns(
                    [
                        *request.messages,
                        ChatMessage(role="user", content=EXTRACT_CUE),
                        ChatMessage(role="assistant", content=chat.content),
                        ChatMessage(role="user", content=RETRY_CUE),
                    ]
                ),
                chat_id=None,
            ),
        )
        cost = _sum_costs(cost, retry.cost_usd)
        if retry.ok and (retry.content or "").strip():
            patch = project.validate_ai_entry_patch_for_type(entry_type, retry.content)
    return EntryPatchExtraction(patch=patch, cost_usd=cost, ok=True)


def _sum_costs(a: float | None, b: float | None) -> float | None:
    """Add two optional per-turn costs — None means 'unknown / unpriced'."""
    if a is None:
        return b
    if b is None:
        return a
    return a + b
