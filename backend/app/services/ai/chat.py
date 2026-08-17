"""Chat send-payload assembly (#178 slice 5).

`expand_and_prepare_chat_blocks` runs the implicit-context expander on a bound
chat's last user message, persists new lore detections to its journal, and
assembles the ordered system cache-blocks the provider call sends. Extracted
from the HTTP layer as a free function taking the project service; journal
expansion is chat-specific, which is why the generate path does not reuse it —
the two share only the system-prompt cache-block via `system_prompt_cache_blocks`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models import (
    AIChatRequest,
    AIChatResponse,
    ChatSession,
    SaveChatSessionRequest,
)
from app.services import machine_settings as machine_settings_service
from app.services.ai import providers as ai_providers
from app.services.ai.call_resolver import resolve_call_params
from app.services.ai.usage import translate_usage_to_cost
from app.services.project.errors import ProjectServiceError

if TYPE_CHECKING:
    from app.services.project_service import ProjectService


def system_prompt_cache_blocks(system_prompt: str) -> list[dict] | None:
    """Wrap a rendered system prompt as a single cacheable 1h block, or None
    when empty.

    Providers that support explicit prompt caching (Anthropic, and OpenRouter
    when routing to them) mark this block cacheable, so back-to-back invocations
    that reuse the same system body are cache reads. The 1h TTL keeps the system
    stable across a scene's continuations. Shared by the chat send path (its
    stable slot 1) and the generate path (its only system block) so the two can
    never drift into caching in one mode but not the other.
    """
    if not system_prompt:
        return None
    return [{"text": system_prompt, "cache_break_after": True, "ttl": "1h"}]


def _staged_set_block(project: ProjectService, staged_set_id: str) -> str:
    """Resolve a chat's OWNED mutation set and render its seed block (ADR-0055 §4).

    Returns "" when the id is empty or no longer resolves (e.g. a deleted set),
    so the send path stays a thin `if block: append`. Lives here rather than in
    `helpers.py` (which is at its size cap) since it is the send path's own step.
    """
    if not staged_set_id:
        return ""
    from app.services.ai.helpers import _format_staged_set_block

    try:
        staged = project.read_mutation_set_entry(staged_set_id)
    except ProjectServiceError:
        return ""
    return _format_staged_set_block(staged.title, staged.target_entry_type, staged.rows)


def _detect_and_persist_journal(
    project: ProjectService,
    chat: ChatSession,
    chat_id: str,
    messages_list: list[dict],
) -> list[Any]:
    """Run the send-time context expander on the last user message and persist
    any new detections to the chat's journal.

    ADR-0057 §4: the expander is an *input* to the one lore selection — it feeds
    the journal `relevant_lore()` reads, not a rival second selector. It runs
    only for a lore-enabled chat; that gate is the caller's (`chat.lore_enabled`).
    Returns the entries newly detected on THIS turn (for the audit UI).
    """
    from app.services.ai.context_expander import expand_context

    # The last user message in the conversation triggered this send.
    user_text = ""
    for m in reversed(messages_list):
        if m.get("role") == "user":
            user_text = m.get("content") or ""
            break
    turn = max(0, len(messages_list) - 1)

    new_entries = expand_context(
        project,
        user_text,
        existing_journal=chat.journal,
        explicit_picks=chat.context_items,
        source="user_message",
        turn=turn,
        # The chat's anchored scene is its mutation resolution scene (#60/#61),
        # so a renamed entity is detected under its as-of-scene name. The anchor
        # is derived from the chat's `subject` when that subject is a scene
        # (ADR-0051 S5 folded the old `target_scene_id` field into `subject`).
        scene=project._subject_scene_id(chat.subject) or None,
    )
    if new_entries:
        project.save_chat_session(
            chat_id,
            SaveChatSessionRequest(
                title=chat.title,
                prompt_entry_id=chat.prompt_entry_id,
                assistant_id=chat.assistant_id,
                system_prompt=chat.system_prompt,
                pinned=chat.pinned,
                context_items=chat.context_items,
                messages=chat.messages,
                inputs=chat.inputs,
                journal=list(chat.journal) + new_entries,
                # `lore_enabled` omitted → preserved (SaveChatSessionRequest
                # treats None as "leave the captured gate alone").
            ),
        )
    return new_entries


def _chat_resolution_scene(project: ProjectService, chat: ChatSession) -> Any:
    """The chat's anchored scene wrapped as an EntryRef, or None for a scene-less
    chat. Send-time lore must resolve as-of the same scene as the lock render
    (ADR-0055), so this mirrors `build_preview`'s scene wrapping — otherwise the
    two would render an entity's fields at different effective states.
    """
    scene_id = project._subject_scene_id(chat.subject)
    if not scene_id:
        return None
    from app.services.ai.helpers import EntryRef

    try:
        raw = project.read_scene(scene_id)
    except Exception:  # noqa: BLE001
        # A missing / stale-cache scene (its file deleted out-of-band while the
        # node index is warm raises FileNotFoundError, not ProjectServiceError)
        # must degrade to a scene-less render, never 500 the send. Mirrors the
        # broad catch `build_preview` uses at the same read.
        return None
    try:
        schema = project.read_metadata_schema()
    except Exception:  # noqa: BLE001
        schema = None
    return EntryRef(project, schema, raw.id, loaded=raw)


def _lore_cache_blocks(
    project: ProjectService,
    chat: ChatSession,
    chat_id: str,
    journal_for_send: list[Any],
) -> list[dict]:
    """The chat's one deduped lore set, placed once *per stability tier*
    (docs/design/context-caching.md §4). `relevant_lore` — the single selector —
    computes `{direct ∪ auto(journal) ∪ always} − {never, manual_only}` and, with
    the chat's in-memory session baseline, splits it: entries unchanged since last
    turn → a 1h stable block; entries new or changed → a 5m volatile block. Both
    resolve as-of the chat's scene. `commit()` promotes this turn's set to next
    turn's baseline. A fresh process starts cold (empty baseline → all volatile),
    which re-settles on the next turn — deliberately not persisted (§6).
    """
    from app.services.ai.helpers import _relevant_lore
    from app.services.ai.sessions import default_registry

    scene = _chat_resolution_scene(project, chat)
    index = project.build_mutations_index() if scene is not None else None
    session = default_registry.get_or_create(f"chatlore:{chat_id}")

    # One selector, two partitions against the same (pre-commit) baseline, so each
    # entry lands in exactly one tier. This re-runs the selector twice per send
    # (once per partition) — acceptable at one call per turn; the mutations index
    # is built once above and threaded into both, not rebuilt per call. ADR-0060
    # §2: the chat's `use(node)` selections join the selector's SAME direct channel
    # (deduped by id, `never`-filtered), never a rival matcher.
    used_ids = list(chat.used_node_ids)
    stable_xml = _relevant_lore(
        project, scene, "implicit", "stable", session, journal_for_send, index, used_ids
    )
    volatile_xml = _relevant_lore(
        project, scene, "implicit", "volatile", session, journal_for_send, index, used_ids
    )
    session.commit()

    blocks: list[dict] = []
    if stable_xml:
        blocks.append({"text": stable_xml, "cache_break_after": True, "ttl": "1h"})
    if volatile_xml:
        blocks.append({"text": volatile_xml, "cache_break_after": True, "ttl": "5m"})
    return blocks


def expand_and_prepare_chat_blocks(
    project: ProjectService,
    chat_id: str | None,
    system_prompt: str,
    messages_list: list[dict],
) -> tuple[list[dict] | None, str | None, list[Any]]:
    """When chat_id is bound, assemble the ordered system cache-blocks the
    provider call sends, and return:
      - system_blocks, in stable→volatile order so longer TTLs stay ahead of
        shorter: [{system_prompt, 1h}, {staged_change, 1h}?, {stable_lore, 1h}?,
        {volatile_lore, 5m}?] — the staged_change block (ADR-0055 S4) is present
        only when the chat owns a resolvable mutation set; the two lore blocks
        (ADR-0057 + docs/design/context-caching.md) only when the chat is
        lore-enabled and the corresponding tier is non-empty
      - session_id for OpenRouter provider stickiness
      - journal_added: lore IDs newly detected on THIS turn (for audit UI)

    ADR-0057 §2/§4: the lore gate. Whether this chat sees lore is the prompt's
    own choice, read from whether the template flipped the gate at its lock
    render (`chat.lore_enabled`). Gate off → no send-time detection and no lore
    block at all, so a deliberately lore-free prompt stays clean (Journey C).

    Placement (docs/design/context-caching.md §4): the backend — not the template
    — selects, dedups, and places lore. The one deduped set is split per turn
    against the chat's in-memory session baseline into a stable 1h block and a
    volatile 5m block, so a settled entity is a cheap cache read instead of being
    re-billed every turn.

    Returns (None, None, []) when chat_id is empty or the chat doesn't
    exist — caller falls back to the legacy single-string system path.
    """
    if not chat_id:
        return None, None, []
    try:
        chat = project.read_chat_session(chat_id)
    except ProjectServiceError:
        return None, None, []

    new_entries: list[Any] = []
    journal_for_send: list[Any] = []
    if chat.lore_enabled:
        new_entries = _detect_and_persist_journal(project, chat, chat_id, messages_list)
        journal_for_send = list(chat.journal) + new_entries

    # Slot 1: system + project-stable (per decisions_implicit_context) — the
    # shared 1h cache block; multi-turn sessions reuse it for hours.
    blocks: list[dict] = list(system_prompt_cache_blocks(system_prompt) or [])
    # Slot 1b (ADR-0055 S4): the mutation set this chat OWNS, seeded so a resumed
    # brainstorm continues refining the same staged change. Stable per chat (it
    # changes only when the writer re-stages), matching 1h TTL. Empty / dangling
    # ref → "" → no block. A mutation set, not lore, so it is not gated.
    staged_xml = _staged_set_block(project, chat.staged_set)
    if staged_xml:
        blocks.append({"text": staged_xml, "cache_break_after": True, "ttl": "1h"})
    # Slots 2a/2b: the one deduped lore set, placed once per stability tier
    # (stable 1h, then volatile 5m). Only for a lore-enabled chat. At most 4
    # cache blocks total here — exactly Anthropic's breakpoint limit.
    if chat.lore_enabled:
        blocks.extend(_lore_cache_blocks(project, chat, chat_id, journal_for_send))

    return (blocks or None), chat_id, list(new_entries)


async def run_chat_turn(project: ProjectService, request: AIChatRequest) -> AIChatResponse:
    """Run one chat-completion turn: resolve provider/model, prepare the bound
    chat's context blocks, call the provider, and shape the response with usage +
    cost. The `/api/ai/chat` route is a thin shim over this, and the fresh-extraction
    commit (`services/ai/extraction`) runs its turn through it too — rather than
    reaching back into the HTTP layer for the chat orchestration.
    """
    settings = machine_settings_service.load_settings()
    resolved = resolve_call_params(
        project,
        settings,
        assistant_id=request.assistant_id,
        provider_override=request.provider,
        model_override=request.model,
        max_tokens_override=request.max_tokens,
    )
    try:
        policy = project.ai_policy()
    except ProjectServiceError:
        policy = "off"

    messages_list = [m.model_dump() for m in request.messages]
    system_blocks, session_id, journal_added = expand_and_prepare_chat_blocks(
        project,
        request.chat_id, request.system_prompt, messages_list
    )

    result = ai_providers.chat(
        resolved.to_call(
            system_prompt=request.system_prompt,
            messages=messages_list,
            system_blocks=system_blocks,
            session_id=session_id,
        ),
        provider_name=resolved.provider,
        settings=settings,
        policy=policy,
    )
    # Both Anthropic and OpenAI signal "hit max_tokens" — different names.
    truncated = result.stop_reason in {"max_tokens", "length"}
    usage_wire, cost_usd = await translate_usage_to_cost(
        result.usage,
        provider=result.provider,
        model=result.model,
        settings=settings,
    )
    return AIChatResponse(
        role="assistant",
        content=result.content,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        policy=policy,
        ok=result.ok,
        error=result.error,
        stop_reason=result.stop_reason,
        truncated=truncated,
        journal_added=journal_added,
        usage=usage_wire,
        cost_usd=cost_usd,
    )
