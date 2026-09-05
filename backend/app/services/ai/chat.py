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
    """Wrap a rendered system prompt as a single **stable-tier** block, or None
    when empty.

    ADR-0060 §5: the shared block model carries only `{text, tier}` — a volatility
    class, not a provider primitive. Each adapter maps the tier to its own caching
    (Anthropic/OpenRouter: a `cache_control` breakpoint, `stable` → a 1h ttl), so
    back-to-back invocations that reuse the same system body are cache reads. The
    system prompt is the most stable content, so it leads the stable-first order.
    Shared by the chat send path (its stable slot 1) and the generate path (its
    only system block) so the two can never drift.
    """
    if not system_prompt:
        return None
    return [{"text": system_prompt, "tier": "stable"}]


def _staged_set_block(project: ProjectService, staged_set_id: str) -> str:
    """Resolve a chat's OWNED mutation set and render its seed block (ADR-0055 §4).

    Returns "" when the id is empty or no longer resolves (e.g. a deleted set),
    so the send path stays a thin `if block: append`. Lives here rather than in
    `helpers.py` (which is at its size cap) since it is the send path's own step.
    """
    if not staged_set_id:
        return ""
    from app.services.ai.lore_block import _format_staged_set_block

    try:
        staged = project.read_mutation_set_entry(staged_set_id)
    except ProjectServiceError:
        return ""
    return _format_staged_set_block(staged.title, staged.target_entry_type, staged.rows)


def _echo_chat_save_request(
    chat: ChatSession,
    *,
    journal: list[Any],
    seen_revisions: dict[str, str] | None = None,
) -> SaveChatSessionRequest:
    """A send-path save that echoes the chat's locked identity/state and writes
    the given journal (and, when given, the last-seen lore revisions), leaving
    every "None = preserve" field (lore_enabled, used_node_ids, …) untouched.
    Shared by the journal-detection save and the #1635 seen-revisions save so a
    newly echoed field can't be added to one and forgotten in the other."""
    return SaveChatSessionRequest(
        title=chat.title,
        prompt_entry_id=chat.prompt_entry_id,
        assistant_id=chat.assistant_id,
        system_prompt=chat.system_prompt,
        subject=chat.subject,
        staged_set=chat.staged_set,
        pinned=chat.pinned,
        context_items=chat.context_items,
        messages=chat.messages,
        inputs=chat.inputs,
        journal=journal,
        seen_revisions=seen_revisions,
    )


def _detect_and_persist_journal(
    project: ProjectService,
    chat: ChatSession,
    chat_id: str,
    messages_list: list[dict],
    scene: Any,
    system_prompt: str,
) -> list[Any]:
    """Run the send-time context expander on the last user message + the
    rendered system prompt (ADR-0075 §2/slice 3b) + the scene's own prose
    (ADR-0075 slice 3), and persist any new detections to the chat's journal.

    ADR-0057 §4: the expander is an *input* to the one lore selection — it feeds
    the journal `relevant_lore()` reads, not a rival second selector. It runs
    only for a lore-enabled chat; that gate is the caller's (`chat.lore_enabled`).
    Returns the entries newly detected on THIS turn (for the audit UI).

    `scene` is the chat's resolution scene, already loaded by the caller
    (`_chat_resolution_scene`) — passed through so a renamed entity is
    detected under its as-of-scene name (#60/#61), and so the scene's body +
    long_text fields are scannable without a second `read_scene`.

    `system_prompt` is the fully-rendered, locked system prompt the caller
    already has — passed through to `expand_context`'s `rendered_text` as a
    third scan surface in the SAME pass. The journal's existing dedup
    (`in_scope`) makes this a first-turn-only detection: once an entity from
    the (frozen) system prompt is journaled, later turns re-scan the same
    text but find nothing new.
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
        # Everything already in context via a picker: the resolved picks
        # (used_node_ids) plus any context_items lore picks — so a picked entry
        # that is also mentioned isn't re-journaled as "auto-added" (#1634).
        picked_ids=[
            *chat.used_node_ids,
            *(item.id for item in chat.context_items if item.kind == "lore" and item.id),
        ],
        source="user_message",
        turn=turn,
        scene=scene,
        rendered_text=system_prompt,
    )
    if new_entries:
        # `seen_revisions` omitted → preserved; `lore_enabled` etc. are None-
        # preserve fields on the request (see _echo_chat_save_request).
        project.save_chat_session(
            chat_id,
            _echo_chat_save_request(chat, journal=list(chat.journal) + new_entries),
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
    scene: Any,
) -> tuple[list[dict], dict[str, str]]:
    """The chat's one deduped lore set, placed once *per volatility tier*
    (docs/design/context-caching.md §4). `_relevant_lore_ids` — the single selector
    — computes `{direct ∪ auto(journal) ∪ always} − {never, manual_only}`;
    `_tier_lore_ids` splits it against the chat's in-memory session baseline: entries
    unchanged since last turn → the stable block, new or changed → the volatile
    block, biased by any `use(node, hint)` prior. Both resolve as-of the chat's
    scene. `commit()` promotes this turn's set to next turn's baseline. A fresh
    process starts cold (empty baseline → all volatile), which re-settles on the next
    turn — deliberately not persisted (§6). The blocks carry only a `tier`; the
    provider adapter maps it to a ttl/breakpoint (ADR-0060 §5).

    `scene` is the chat's resolution scene, already loaded once by the caller
    (`_chat_resolution_scene`) and shared with `_detect_and_persist_journal` —
    avoids a second `read_scene` for the same turn.
    """
    from app.services.ai.lore_block import _format_lore_block
    from app.services.ai.lore_selection import (
        _relevant_lore_ids,
        _tier_lore_ids,
    )
    from app.services.ai.sessions import default_registry

    index = project.build_mutations_index() if scene is not None else None
    session = default_registry.get_or_create(f"chatlore:{chat_id}")
    # #1635: on a cold process the in-memory baseline is empty; seed it from the
    # chat's persisted last-seen revisions so tiering (and the door's "edited"
    # signal) survive a restart. Only when cold — never clobber a live baseline.
    if not session.baseline and chat.seen_revisions:
        session.baseline = dict(chat.seen_revisions)

    # ADR-0060 §2/§5: one selector, computed ONCE, then split into the two tiers by
    # `_tier_lore_ids` against the same (pre-commit) baseline — so each entry lands
    # in exactly one tier and the selector isn't re-run per partition. The chat's
    # `use(node)` selections join the selector's SAME direct channel (deduped by id,
    # `never`-filtered); their `use(node, hint)` priors bias placement only.
    used_ids = list(chat.used_node_ids)
    hints = dict(chat.used_node_hints)
    ids = _relevant_lore_ids(project, scene, "implicit", journal_for_send, used_ids)
    stable_ids, volatile_ids = _tier_lore_ids(project, ids, session, hints)
    session.commit()

    blocks: list[dict] = []
    stable_xml = _format_lore_block(project, stable_ids, scene=scene, index=index)
    if stable_xml:
        blocks.append({"text": stable_xml, "tier": "stable"})
    volatile_xml = _format_lore_block(project, volatile_ids, scene=scene, index=index)
    if volatile_xml:
        blocks.append({"text": volatile_xml, "tier": "volatile"})
    return blocks, dict(session.baseline)


def expand_and_prepare_chat_blocks(
    project: ProjectService,
    chat_id: str | None,
    system_prompt: str,
    messages_list: list[dict],
) -> tuple[list[dict] | None, str | None, list[Any]]:
    """When chat_id is bound, assemble the ordered system cache-blocks the
    provider call sends, and return:
      - system_blocks, in stable-first order (ADR-0060 §5): [{system_prompt,
        stable}, {staged_change, stable}?, {stable_lore, stable}?, {volatile_lore,
        volatile}?] — the staged_change block (ADR-0055 S4) is present only when the
        chat owns a resolvable mutation set; the two lore blocks (ADR-0057 +
        docs/design/context-caching.md) only when the chat is lore-enabled and the
        corresponding tier is non-empty. Each block carries a `tier`, not a ttl;
        the adapter maps tier → ttl/breakpoint and caps the breakpoint count
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
    # Loaded ONCE — the scene EntryRef (body + metadata) shared by detection
    # (ADR-0075 slice 3 scans its prose) and lore rendering, so a lore-enabled
    # turn does exactly one `read_scene` for its resolution scene.
    scene = _chat_resolution_scene(project, chat) if chat.lore_enabled else None
    if chat.lore_enabled:
        new_entries = _detect_and_persist_journal(
            project, chat, chat_id, messages_list, scene, system_prompt
        )
        journal_for_send = list(chat.journal) + new_entries

    # Slot 1: system + project-stable (per decisions_implicit_context) — the
    # shared 1h cache block; multi-turn sessions reuse it for hours.
    blocks: list[dict] = list(system_prompt_cache_blocks(system_prompt) or [])
    # Slot 1b (ADR-0055 S4): the mutation set this chat OWNS, seeded so a resumed
    # brainstorm continues refining the same mutation set. Stable per chat (it
    # changes only when the writer re-stages), matching 1h TTL. Empty / dangling
    # ref → "" → no block. A mutation set, not lore, so it is not gated.
    staged_xml = _staged_set_block(project, chat.staged_set)
    if staged_xml:
        blocks.append({"text": staged_xml, "tier": "stable"})
    # Slots 2a/2b: the one deduped lore set, placed once per volatility tier
    # (stable, then volatile). Only for a lore-enabled chat. The provider adapter
    # caps breakpoints (Anthropic: ≤4) and assigns each tier its ttl — the shared
    # layer only orders stable-first (ADR-0060 §5).
    if chat.lore_enabled:
        lore_blocks, seen_revisions = _lore_cache_blocks(
            project, chat, chat_id, journal_for_send, scene
        )
        blocks.extend(lore_blocks)
        # #1635: persist the last-seen revisions if they changed, so the door's
        # "edited" badge survives a restart and reflects this turn's send. Carry
        # the up-to-date journal (journal_for_send) so this save doesn't regress
        # the entries _detect_and_persist_journal just wrote.
        if seen_revisions != chat.seen_revisions:
            project.save_chat_session(
                chat_id,
                _echo_chat_save_request(
                    chat, journal=journal_for_send, seen_revisions=seen_revisions
                ),
            )

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
        manual_price_in_usd_per_mtok=resolved.manual_price_in_usd_per_mtok,
        manual_price_out_usd_per_mtok=resolved.manual_price_out_usd_per_mtok,
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
