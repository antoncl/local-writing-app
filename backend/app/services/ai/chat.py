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


def expand_and_prepare_chat_blocks(
    project: ProjectService,
    chat_id: str | None,
    system_prompt: str,
    messages_list: list[dict],
) -> tuple[list[dict] | None, str | None, list[Any]]:
    """When chat_id is bound, assemble the ordered system cache-blocks the
    provider call sends, and return:
      - system_blocks, in stable→volatile order so longer TTLs stay ahead of
        shorter: [{system_prompt, 1h}, {staged_change, 1h}?, {journal_xml, 5m}]
        — the staged_change block (ADR-0055 S4) is present only when the chat
        owns a resolvable mutation set; the journal block (ADR-0057) only when
        the chat is lore-enabled
      - session_id for OpenRouter provider stickiness
      - journal_added: lore IDs newly detected on THIS turn (for audit UI)

    ADR-0057 §2/§4: the lore gate. Whether this chat sees lore is the prompt's
    own choice, read from whether `relevant_lore()` executed at its lock render
    (`chat.lore_enabled`). Gate off → no send-time detection and no lore block at
    all, so a deliberately lore-free prompt stays clean (Journey C). Gate on →
    the expander feeds the journal that the one selector reads — an input, never
    a rival block.

    Returns (None, None, []) when chat_id is empty or the chat doesn't
    exist — caller falls back to the legacy single-string system path.
    """
    if not chat_id:
        return None, None, []
    try:
        chat = project.read_chat_session(chat_id)
    except ProjectServiceError:
        return None, None, []

    from app.services.ai.helpers import _format_lore_block

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
    # changes only when the writer re-stages), so it sits above the turn-by-turn
    # journal with a matching 1h TTL. Empty / dangling ref → "" → no block. This
    # is a mutation set, not lore, so it is not subject to the lore gate.
    staged_xml = _staged_set_block(project, chat.staged_set)
    if staged_xml:
        blocks.append({"text": staged_xml, "cache_break_after": True, "ttl": "1h"})
    # Slot 2 (ADR-0057 §3/§5): the detected/journal lore, placed once. Present
    # only for a lore-enabled chat (`journal_for_send` stays empty otherwise). 5m
    # TTL because it grows mid-session — append-only, ratchets forward.
    if journal_for_send:
        journal_xml = _format_lore_block(
            project, [e.entry_id for e in journal_for_send]
        )
        if journal_xml:
            blocks.append({"text": journal_xml, "cache_break_after": True, "ttl": "5m"})

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
        provider_name=resolved.provider,
        model=resolved.model,
        system_prompt=request.system_prompt,
        messages=messages_list,
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
        settings=settings,
        policy=policy,
        system_blocks=system_blocks,
        session_id=session_id,
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
