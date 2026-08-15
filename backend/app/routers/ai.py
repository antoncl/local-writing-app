"""AI provider, preview, chat, generate, streaming, and cost routes (#170 main.py split)."""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.models import (
    AIChatRequest,
    AIChatResponse,
    AIContextPresetResponse,
    AIEntryPatch,
    AIGenerateRequest,
    AIGenerateResponse,
    AIHealthRequest,
    AIHealthResponse,
    AIInvocation,
    AIInvocationList,
    AIModelInfo,
    AIPreviewRequest,
    AIPreviewResponse,
    AIProviderInfo,
    AIProviderList,
    AIProviderModelList,
    AITierResolution,
    ChatMessage,
    ChatUsage,
    CreateAIInvocationRequest,
    EntryPatchExtraction,
    ExtractEntryDraftRequest,
    ExtractEntryPatchRequest,
    PreviewCacheBlock,
    PreviewContentBlock,
    PreviewErrorInfo,
    PreviewMessage,
    SaveChatSessionRequest,
    ValidateEntryDraftRequest,
    ValidateEntryPatchRequest,
)
from app.runtime import CurrentProject, translate_errors
from app.services import machine_settings as machine_settings_service
from app.services.ai import providers as ai_providers
from app.services.ai import tokens as ai_tokens
from app.services.ai.call_resolver import resolve_call_params
from app.services.ai.extraction import EXTRACT_CUE, render_extraction_contract
from app.services.ai.preview import PreviewError, build_chat_payload, build_preview
from app.services.ai.profiles import CapabilityTier, ModelDescriptor
from app.services.ai.profiles.registry import known_provider_names, profile_for
from app.services.project_service import ProjectService, ProjectServiceError

router = APIRouter()


def _preview_error_detail(exc: PreviewError) -> Any:
    """Shape the FastAPI HTTPException detail for a PreviewError.

    Plain string when there's no location info (compat with the original
    behavior); a structured dict when Jinja gave us a line. The frontend's
    `formatErrorDetail` falls back to the `message` field, so old callers
    still see something sensible.
    """
    if exc.line is None and exc.col is None:
        return exc.message
    detail: dict[str, Any] = {"message": exc.message}
    if exc.line is not None:
        detail["line"] = exc.line
    if exc.col is not None:
        detail["col"] = exc.col
    return detail


# --- AI: health check ---


@router.post("/api/ai/health", response_model=AIHealthResponse)
def ai_health(project: CurrentProject, request: AIHealthRequest) -> AIHealthResponse:
    settings = machine_settings_service.load_settings()
    resolved = resolve_call_params(
        project,
        settings,
        assistant_id=request.assistant_id,
        provider_override=request.provider,
        model_override=request.model,
        max_tokens_override=None,
    )
    try:
        policy = project.ai_policy()
    except ProjectServiceError:
        policy = "off"
    return ai_providers.health_check(
        provider_name=resolved.provider,
        model=resolved.model,
        settings=settings,
        policy=policy,
    )


def _descriptor_to_wire(descriptor: ModelDescriptor) -> AIModelInfo:
    return AIModelInfo(
        id=descriptor.id,
        display_name=descriptor.display_name,
        provider=descriptor.provider,
        context_window=descriptor.context_window,
        tier=descriptor.tier.value,
        capabilities=sorted(c.value for c in descriptor.capabilities),
        deprecated=descriptor.deprecated,
        sunset_date=descriptor.sunset_date.isoformat() if descriptor.sunset_date else None,
        successor=descriptor.successor,
        cost_in_per_mtok=descriptor.cost_in_per_mtok,
        cost_out_per_mtok=descriptor.cost_out_per_mtok,
        cache_read_multiplier=descriptor.cache_read_multiplier,
    )


@router.get("/api/ai/providers", response_model=AIProviderList)
def list_ai_providers() -> AIProviderList:
    """List the providers the assistant builder can pick from."""

    from app.services.machine_settings import PROVIDER_DISPLAY_NAMES

    return AIProviderList(
        providers=[
            AIProviderInfo(
                name=name,
                display_name=PROVIDER_DISPLAY_NAMES.get(name, name.title()),
            )
            for name in known_provider_names()
        ]
    )


@router.get("/api/ai/providers/{provider}/models", response_model=AIProviderModelList)
async def list_ai_provider_models(
    provider: str, force_refresh: bool = Query(default=False)
) -> AIProviderModelList:
    """Return the provider's model catalogue.

    Falls back to bake-in data if live discovery fails (offline, bad key
    — see `ProviderProfile.list_models()` semantics). `force_refresh`
    bypasses any in-memory cache the profile holds."""

    if provider not in known_provider_names():
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    settings = machine_settings_service.load_settings()
    profile = profile_for(provider, settings)
    descriptors = await profile.list_models(force_refresh=force_refresh)
    return AIProviderModelList(
        provider=provider,
        models=[_descriptor_to_wire(d) for d in descriptors],
    )


@router.get(
    "/api/ai/providers/{provider}/resolve-tier",
    response_model=AITierResolution,
)
async def resolve_ai_provider_tier(
    provider: str, tier: str = Query(...)
) -> AITierResolution:
    """Ask a provider to resolve a capability tier to a concrete model id.

    Frontend calls this at save time so the assistant entry stores the
    literal model. Returns null `model_id` if the tier has no candidates
    (e.g. PREMIUM on Ollama)."""

    if provider not in known_provider_names():
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    try:
        tier_enum = CapabilityTier(tier)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown tier: {tier}") from exc
    settings = machine_settings_service.load_settings()
    profile = profile_for(provider, settings)
    descriptors = await profile.list_models()
    model_id = profile.model_for_tier(tier_enum, descriptors)
    return AITierResolution(provider=provider, tier=tier, model_id=model_id)


@router.post("/api/ai/preview", response_model=AIPreviewResponse)
async def ai_preview(project: CurrentProject, request: AIPreviewRequest) -> AIPreviewResponse:
    with translate_errors():
        # `current_project` raises ProjectServiceError if no project is open;
        # translate_errors handles that. Preview-render failures (undefined
        # variables, syntax errors, missing target scene) are exploratory —
        # the editor auto-fires this endpoint before the user has filled
        # required inputs, so we return 200 with `error` populated rather
        # than throwing. `/api/ai/generate` keeps the strict 422 behavior.
        try:
            rendered, session_id = build_preview(
                project_service=project,
                template_source=request.template_source,
                target_scene_id=request.target_scene_id,
                session_id=request.session_id,
                inputs=request.inputs,
                text_before=request.text_before,
                text_after=request.text_after,
                selection=request.selection,
                commit=request.commit,
                resolution_scene_id=request.resolution_scene_id,
                subject=request.subject,
            )
        except PreviewError as exc:
            return AIPreviewResponse(
                messages=[],
                warnings=[],
                char_count=0,
                session_id=request.session_id,
                rendered=False,
                error=PreviewErrorInfo(
                    message=exc.message,
                    kind=exc.kind,
                    line=exc.line,
                    col=exc.col,
                    undefined_name=exc.undefined_name,
                ),
            )

    messages = [
        PreviewMessage(
            role=m.role,
            blocks=[
                PreviewContentBlock(text=b.text, cache_break_after=b.cache_break_after)
                for b in m.blocks
            ],
        )
        for m in rendered.messages
    ]
    char_count = sum(len(b.text) for m in messages for b in m.blocks)

    # ----- Token + cost estimate (V2) ---------------------------------
    settings = machine_settings_service.load_settings()
    provider: str | None = None
    model: str | None = None
    caching_style: str | None = None
    descriptor: ModelDescriptor | None = None
    if request.assistant_id is not None:
        resolved = resolve_call_params(
            project,
            settings,
            assistant_id=request.assistant_id,
            provider_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        provider = resolved.provider or None
        model = resolved.model or None
        if provider:
            try:
                profile = profile_for(provider, settings)
                caching_style = profile.caching_style(model or "")
            except ValueError:
                caching_style = None
        if provider and model:
            descriptor = await ai_tokens.descriptor_for(
                provider=provider, model=model, settings=settings
            )

    # Group blocks into "cache segments" — each ending at a
    # cache_break_after marker (or at the end of the message). One segment
    # ≈ one ephemeral cache slot from the dispatch layer's perspective.
    cache_blocks: list[PreviewCacheBlock] = []
    counter_provider = provider or "anthropic"  # tokenizer choice is identical across providers in v1
    for message in messages:
        current_texts: list[str] = []
        segment_index_in_message = 0
        for block in message.blocks:
            current_texts.append(block.text)
            if block.cache_break_after:
                segment_index_in_message += 1
                segment_text = "".join(current_texts)
                cache_blocks.append(
                    PreviewCacheBlock(
                        label=f"{message.role} block {segment_index_in_message}",
                        role=message.role,
                        tokens=ai_tokens.count_tokens(
                            segment_text,
                            provider=counter_provider,
                            model=model or "",
                            settings=settings,
                        ),
                        cache_break_after=True,
                    )
                )
                current_texts = []
        if current_texts:
            # Trailing run with no terminating marker — the "tail" of the
            # message. Counts the same way but is_cache=false in spirit.
            segment_index_in_message += 1
            tail_text = "".join(current_texts)
            label = (
                f"{message.role} tail"
                if segment_index_in_message > 1 or len(message.blocks) > 1
                else f"{message.role}"
            )
            cache_blocks.append(
                PreviewCacheBlock(
                    label=label,
                    role=message.role,
                    tokens=ai_tokens.count_tokens(
                        tail_text,
                        provider=counter_provider,
                        model=model or "",
                        settings=settings,
                    ),
                    cache_break_after=False,
                )
            )

    estimated_tokens = sum(b.tokens for b in cache_blocks)
    estimated_cost_usd: float | None = None
    if descriptor is not None:
        cost = ai_tokens.estimate_input_cost(estimated_tokens, descriptor)
        # Distinguish "no pricing known" (None) from "pricing known, zero
        # tokens" (0.0). When descriptor exists but cost is 0, that means
        # either zero-length input or pricing-not-published — surface 0.0
        # so the UI can show "€0.0000" rather than "—".
        estimated_cost_usd = cost

    return AIPreviewResponse(
        messages=messages,
        warnings=rendered.warnings,
        char_count=char_count,
        session_id=session_id,
        rendered=True,
        estimated_tokens=estimated_tokens,
        cache_blocks=cache_blocks,
        estimated_cost_usd=estimated_cost_usd,
        provider=provider,
        model=model,
        caching_style=caching_style,
    )


# --- AI: chat completion (first real model call) ---


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


def _prepare_chat_send_payload(
    project: ProjectService,
    chat_id: str | None,
    system_prompt: str,
    messages_list: list[dict],
) -> tuple[list[dict] | None, str | None, list[Any]]:
    """When chat_id is bound, run the implicit-context expander on the last
    user message, append new detections to ChatSession.journal, save the
    chat, and return:
      - system_blocks, in stable→volatile order so longer TTLs stay ahead of
        shorter: [{system_prompt, 1h}, {staged_change, 1h}?, {journal_xml, 5m}]
        — the staged_change block (ADR-0055 S4) is present only when the chat
        owns a resolvable mutation set
      - session_id for OpenRouter provider stickiness
      - journal_added: lore IDs newly detected on THIS turn (for audit UI)

    Returns (None, None, []) when chat_id is empty or the chat doesn't
    exist — caller falls back to the legacy single-string system path.
    """
    if not chat_id:
        return None, None, []
    try:
        chat = project.read_chat_session(chat_id)
    except ProjectServiceError:
        return None, None, []

    from app.services.ai.context_expander import expand_context
    from app.services.ai.helpers import _format_lore_block

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
        extended_journal = list(chat.journal) + new_entries
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
                journal=extended_journal,
            ),
        )
        journal_for_send = extended_journal
    else:
        journal_for_send = list(chat.journal)

    blocks: list[dict] = []
    if system_prompt:
        # Slot 1: system + project-stable (per decisions_implicit_context).
        # 1h TTL because this only changes when the chat is locked at first
        # send; multi-turn sessions reuse this for hours.
        blocks.append({"text": system_prompt, "cache_break_after": True, "ttl": "1h"})
    # Slot 1b (ADR-0055 S4): the mutation set this chat OWNS, seeded so a resumed
    # brainstorm continues refining the same staged change. Stable per chat (it
    # changes only when the writer re-stages), so it sits above the turn-by-turn
    # journal with a matching 1h TTL. Empty / dangling ref → "" → no block.
    staged_xml = _staged_set_block(project, chat.staged_set)
    if staged_xml:
        blocks.append({"text": staged_xml, "cache_break_after": True, "ttl": "1h"})
    if journal_for_send:
        journal_xml = _format_lore_block(
            project, [e.entry_id for e in journal_for_send]
        )
        if journal_xml:
            # Slot 2: merged explicit + detected context (we treat the
            # journal as the detected portion; explicit picks already live
            # in the rendered system_prompt at first turn). 5m TTL because
            # this grows mid-session — append-only, ratchets forward.
            blocks.append({"text": journal_xml, "cache_break_after": True, "ttl": "5m"})

    return (blocks or None), chat_id, list(new_entries)


async def _usage_and_cost(
    usage,
    *,
    provider: str,
    model: str,
    settings,
) -> tuple[ChatUsage | None, float | None]:
    """Convert dispatch-layer UsageMetrics + a (provider, model) lookup
    into wire-format ChatUsage and USD cost. Returns (None, None) when
    usage is missing; cost stays None when pricing isn't known."""

    if usage is None:
        return None, None
    wire_usage = ChatUsage(
        input_tokens=usage.input_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        output_tokens=usage.output_tokens,
    )
    if not provider or not model:
        return wire_usage, None
    from app.services.ai.profiles import compute_cost
    descriptor = await ai_tokens.descriptor_for(
        provider=provider, model=model, settings=settings
    )
    if descriptor is None:
        return wire_usage, None
    cost = compute_cost(usage, descriptor)
    return wire_usage, cost


@router.post("/api/ai/chat", response_model=AIChatResponse)
async def ai_chat(project: CurrentProject, request: AIChatRequest) -> AIChatResponse:
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
    system_blocks, session_id, journal_added = _prepare_chat_send_payload(
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
    usage_wire, cost_usd = await _usage_and_cost(
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


# --- AI: generate (template + provider, the full pipeline) ---


@router.post("/api/ai/generate", response_model=AIGenerateResponse)
async def ai_generate(project: CurrentProject, request: AIGenerateRequest) -> AIGenerateResponse:
    with translate_errors():
        try:
            rendered, session_id = build_preview(
                project_service=project,
                template_source=request.template_source,
                target_scene_id=request.target_scene_id,
                session_id=request.session_id,
                inputs=request.inputs,
                text_before=request.text_before,
                text_after=request.text_after,
                selection=request.selection,
                commit=request.commit,
                resolution_scene_id=request.resolution_scene_id,
            )
        except PreviewError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=_preview_error_detail(exc),
            ) from exc

    system_prompt, chat_messages = build_chat_payload(rendered)

    preview_messages = [
        PreviewMessage(
            role=m.role,
            blocks=[
                PreviewContentBlock(text=b.text, cache_break_after=b.cache_break_after)
                for b in m.blocks
            ],
        )
        for m in rendered.messages
    ]
    char_count = sum(len(b.text) for m in preview_messages for b in m.blocks)

    if not chat_messages:
        raise HTTPException(
            status_code=400,
            detail=(
                "Template produced no user/assistant messages — nothing to send to "
                "the model. The template must contain at least one {% role \"user\" %} "
                "block with non-empty content."
            ),
        )

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

    # Wrap the rendered system_prompt so providers that support explicit
    # prompt caching (Anthropic, and OpenRouter when routing to them) can
    # mark it cacheable. Continuation reuses the same prompt body across
    # back-to-back invocations on the same scene — a 1h TTL keeps the
    # system stable so the second hit is a cache read. Chat already gets
    # this via _prepare_chat_send_payload; we deliberately don't reuse
    # that helper here because journal expansion is chat-specific.
    system_blocks: list[dict] | None = None
    if system_prompt:
        system_blocks = [{"text": system_prompt, "cache_break_after": True, "ttl": "1h"}]

    result = ai_providers.chat(
        provider_name=resolved.provider,
        model=resolved.model,
        system_prompt=system_prompt,
        messages=chat_messages,
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
        settings=settings,
        policy=policy,
        system_blocks=system_blocks,
        session_id=session_id,
    )
    truncated = result.stop_reason in {"max_tokens", "length"}
    usage_wire, cost_usd = await _usage_and_cost(
        result.usage,
        provider=result.provider,
        model=result.model,
        settings=settings,
    )

    return AIGenerateResponse(
        content=result.content,
        rendered_messages=preview_messages,
        rendered_warnings=rendered.warnings,
        char_count=char_count,
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        policy=policy,
        ok=result.ok,
        error=result.error,
        stop_reason=result.stop_reason,
        truncated=truncated,
        session_id=session_id,
        usage=usage_wire,
        cost_usd=cost_usd,
    )


# --- AI: streaming variants (NDJSON) ---
#
# Each line of the response is a JSON object. Events:
#   {"type":"delta","text":"..."}                            (zero or more)
#   {"type":"thinking","text":"..."}                         (zero or more)
#   {"type":"done","provider":"...","model":"...",
#    "latency_ms":N,"stop_reason":"...","truncated":bool,
#    "policy":"...","session_id":"...","char_count":N}       (exactly one, on success)
#   {"type":"error","error":"...","provider":"...",
#    "model":"...","latency_ms":N,"policy":"..."}            (exactly one, on failure)


def _ndjson(line: dict[str, Any]) -> str:
    return json.dumps(line, ensure_ascii=False) + "\n"


def _stream_provider_events(
    events: Iterator[ai_providers.StreamEvent],
    *,
    policy: str,
    extra_done: dict[str, Any] | None = None,
    descriptor: ModelDescriptor | None = None,
) -> Iterator[str]:
    """Adapt provider events to NDJSON lines. Suppresses empty deltas.

    When `descriptor` is provided and the terminal StreamDone carries
    usage, the `done` line includes `usage` + `cost_usd`. The descriptor
    is pre-fetched by the endpoint so this sync generator can compute
    cost without an await.
    """
    extra_done = extra_done or {}
    try:
        for ev in events:
            if isinstance(ev, ai_providers.StreamDelta):
                if ev.text:
                    yield _ndjson({"type": "delta", "text": ev.text})
            elif isinstance(ev, ai_providers.StreamThinking):
                if ev.text:
                    yield _ndjson({"type": "thinking", "text": ev.text})
            elif isinstance(ev, ai_providers.StreamDone):
                done_line: dict[str, Any] = {
                    "type": "done",
                    "provider": ev.provider,
                    "model": ev.model,
                    "latency_ms": ev.latency_ms,
                    "stop_reason": ev.stop_reason,
                    "truncated": ev.truncated,
                    "policy": policy,
                    **extra_done,
                }
                if ev.usage is not None:
                    done_line["usage"] = {
                        "input_tokens": ev.usage.input_tokens,
                        "cached_input_tokens": ev.usage.cached_input_tokens,
                        "cache_write_tokens": ev.usage.cache_write_tokens,
                        "output_tokens": ev.usage.output_tokens,
                    }
                    if descriptor is not None:
                        from app.services.ai.profiles import compute_cost
                        done_line["cost_usd"] = compute_cost(ev.usage, descriptor)
                yield _ndjson(done_line)
            elif isinstance(ev, ai_providers.StreamError):
                yield _ndjson({
                    "type": "error",
                    "error": ev.error,
                    "provider": ev.provider,
                    "model": ev.model,
                    "latency_ms": ev.latency_ms,
                    "policy": policy,
                })
    except Exception as exc:  # noqa: BLE001 — last-resort guard so the stream always terminates
        yield _ndjson({
            "type": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "provider": "",
            "model": "",
            "latency_ms": 0,
            "policy": policy,
        })


@router.post("/api/ai/chat/stream")
async def ai_chat_stream(project: CurrentProject, request: AIChatRequest) -> StreamingResponse:
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
    system_blocks, session_id, journal_added = _prepare_chat_send_payload(
        project,
        request.chat_id, request.system_prompt, messages_list
    )

    # Pre-fetch the pricing descriptor so the sync stream generator can
    # compute cost when the terminal StreamDone arrives, without needing
    # an await mid-stream.
    descriptor = await ai_tokens.descriptor_for(
        provider=resolved.provider, model=resolved.model, settings=settings
    )

    events = ai_providers.chat_stream(
        provider_name=resolved.provider,
        model=resolved.model,
        system_prompt=request.system_prompt,
        messages=messages_list,
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
        thinking_enabled=resolved.thinking_enabled,
        settings=settings,
        policy=policy,
        system_blocks=system_blocks,
        session_id=session_id,
    )
    return StreamingResponse(
        _stream_provider_events(
            events, policy=policy,
            extra_done=(
                {"journal_added": [e.model_dump() for e in journal_added]}
                if journal_added else None
            ),
            descriptor=descriptor,
        ),
        media_type="application/x-ndjson",
    )


@router.post("/api/ai/generate/stream")
async def ai_generate_stream(project: CurrentProject, request: AIGenerateRequest) -> StreamingResponse:
    # Render template first — if this fails, return an HTTP error like the
    # non-streaming endpoint does. The stream itself only carries provider events.
    with translate_errors():
        try:
            rendered, session_id = build_preview(
                project_service=project,
                template_source=request.template_source,
                target_scene_id=request.target_scene_id,
                session_id=request.session_id,
                inputs=request.inputs,
                text_before=request.text_before,
                text_after=request.text_after,
                selection=request.selection,
                commit=request.commit,
                resolution_scene_id=request.resolution_scene_id,
            )
        except PreviewError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=_preview_error_detail(exc),
            ) from exc

    system_prompt, chat_messages = build_chat_payload(rendered)
    if not chat_messages:
        raise HTTPException(
            status_code=400,
            detail=(
                "Template produced no user/assistant messages — nothing to send to "
                "the model. The template must contain at least one {% role \"user\" %} "
                "block with non-empty content."
            ),
        )
    char_count = sum(len(b.text) for m in rendered.messages for b in m.blocks)

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

    descriptor = await ai_tokens.descriptor_for(
        provider=resolved.provider, model=resolved.model, settings=settings
    )
    # Same cache-marker treatment as the non-streaming path above. Keep
    # both endpoints in sync — divergence here would mean cache hits in
    # one mode and not the other.
    system_blocks: list[dict] | None = None
    if system_prompt:
        system_blocks = [{"text": system_prompt, "cache_break_after": True, "ttl": "1h"}]

    events = ai_providers.chat_stream(
        provider_name=resolved.provider,
        model=resolved.model,
        system_prompt=system_prompt,
        messages=chat_messages,
        max_tokens=resolved.max_tokens,
        temperature=resolved.temperature,
        thinking_enabled=resolved.thinking_enabled,
        settings=settings,
        policy=policy,
        system_blocks=system_blocks,
        session_id=session_id,
    )
    return StreamingResponse(
        _stream_provider_events(
            events,
            policy=policy,
            extra_done={"session_id": session_id, "char_count": char_count},
            descriptor=descriptor,
        ),
        media_type="application/x-ndjson",
    )


@router.post("/api/ai/invocations", response_model=AIInvocation, status_code=201)
def ai_invocation_append(project: CurrentProject, request: CreateAIInvocationRequest) -> AIInvocation:
    """Append one AI invocation telemetry record. Called from the frontend
    on accept of a continuation or roleplay generation. The `cost` computed
    field and the per-character cost chip read these records.
    """
    with translate_errors():
        return project.append_ai_invocation(request)


@router.get("/api/ai/invocations", response_model=AIInvocationList)
def ai_invocation_list(
    project: CurrentProject,
    scene_id: str | None = Query(default=None),
    character_id: str | None = Query(default=None),
    chat_session_id: str | None = Query(default=None),
) -> AIInvocationList:
    """List invocation records, optionally filtered by scene_id,
    character_id, and/or chat_session_id. Frontend uses scene_id to
    group per-character cost; chat_session_id surfaces per-chat cost
    after Phase C2 Slice B.
    """
    with translate_errors():
        return project.list_ai_invocations(
            scene_id=scene_id,
            character_id=character_id,
            chat_session_id=chat_session_id,
        )


@router.get("/api/ai/context-preset", response_model=AIContextPresetResponse)
def ai_context_preset(project: CurrentProject, kind: str = Query(...)) -> AIContextPresetResponse:
    from app.services.ai.context_presets import VALID_PRESETS, render_preset

    if kind not in VALID_PRESETS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown context preset '{kind}'. Valid: {list(VALID_PRESETS)}.",
        )
    with translate_errors():
        content = render_preset(project, kind)
    return AIContextPresetResponse(kind=kind, content=content)


# --- The AI patch loop: one kind-neutral validate path (ADR-0048 §5) ---
#
# The propose → review → adopt → commit loop (ADR-0046) is node-shaped, not
# lore-shaped: these two endpoints validate a brainstorm-commit reply against
# ANY schema-typed node's `entry_type`. The target's kind rides in implicitly —
# `entry-patch` resolves it from the node index by id, `entry-draft` takes the
# entry_type FQN (`kind:key`) directly — so a later kind (e.g. `plot:card`)
# reuses this exact review path rather than duplicating it (anti-goal 2). The
# adopted result is written through each kind's own intentful save endpoint.


@router.post("/api/ai/entry-patch/{node_id}", response_model=AIEntryPatch)
def validate_ai_entry_patch(
    project: CurrentProject, node_id: str, request: ValidateEntryPatchRequest
) -> AIEntryPatch:
    """Validate a brainstorm-commit reply into a review-ready patch for an
    existing node (ADR-0046 §4/§6.3). Parses the model's JSON, validates each
    proposed field against the node's resolved schema, drops the illegal ones
    per-field, and flags a garbled reply. Read-only — the adopted patch is
    written through the node's own save endpoint (`PUT /api/lore/{id}`, …)."""
    with translate_errors():
        return project.validate_ai_entry_patch(node_id, request.raw)


@router.post("/api/ai/entry-draft", response_model=AIEntryPatch)
def validate_ai_entry_draft(
    project: CurrentProject, request: ValidateEntryDraftRequest
) -> AIEntryPatch:
    """Create-mode sibling of `/api/ai/entry-patch/{node_id}` (ADR-0046 §6.4):
    no node exists yet, so the target `entry_type` rides in the body. Read-only
    — the adopted draft is created through the kind's own create + save
    endpoints (`POST /api/lore` + `PUT /api/lore/{id}`, …)."""
    with translate_errors():
        return project.validate_ai_entry_draft(request.entry_type, request.raw)


# --- AI: fresh-extraction commit (ADR-0051 S4) ---
#
# The commit of a brainstorm chat. Instead of replaying the frozen seed system
# prompt + transcript + a terse finalize cue (the old client-side
# `runFinalizeTurn`, which got less reliable the longer the chat ran), the server
# rebuilds the format contract from the target's schema and runs it as its own
# fresh pass — the transcript is pure input, the contract sits at the top of a
# small context. Length-independent by construction (ADR §4). Both endpoints reuse
# the existing pieces end to end: `render_extraction_contract` (built on the
# preview pipeline), the ordinary `ai_chat` provider call, and the SAME
# parse+validate the finalize path used — so nothing downstream of the patch
# changes.


def _messages_with_extract_cue(transcript: list[ChatMessage]) -> list[ChatMessage]:
    """Append the extract cue to the transcript, coalescing consecutive same-role
    turns and dropping whitespace-only ones — the sanitization `build_chat_payload`
    does for rendered templates, which the raw transcript would otherwise skip.
    Without it a transcript ending on a user turn (e.g. the author committed right
    after a failed reply left the last turn a user one) would put two user turns
    back to back, and the provider rejects that outright."""

    out: list[ChatMessage] = []
    for msg in [*transcript, ChatMessage(role="user", content=EXTRACT_CUE)]:
        if not msg.content.strip():
            continue
        if out and out[-1].role == msg.role:
            out[-1] = ChatMessage(role=msg.role, content=f"{out[-1].content}\n\n{msg.content}")
        else:
            out.append(msg)
    return out


async def _run_entry_patch_extraction(
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
    chat = await ai_chat(
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
    return EntryPatchExtraction(patch=patch, cost_usd=chat.cost_usd, ok=True)


@router.post("/api/ai/entry-patch/{node_id}/extract", response_model=EntryPatchExtraction)
async def extract_entry_patch(
    project: CurrentProject, node_id: str, request: ExtractEntryPatchRequest
) -> EntryPatchExtraction:
    """Revise-mode fresh extraction (ADR-0051 S4). The target `entry_type` is
    resolved from the node index by id, then the contract + turn + validate run.
    Read-only — the adopted patch is written through the node's own save path."""
    with translate_errors():
        entry_type = project.entry_type_for_node(node_id)
        return await _run_entry_patch_extraction(
            project, entry_type=entry_type, creating=False, request=request
        )


@router.post("/api/ai/entry-draft/extract", response_model=EntryPatchExtraction)
async def extract_entry_draft(
    project: CurrentProject, request: ExtractEntryDraftRequest
) -> EntryPatchExtraction:
    """Create-mode sibling (ADR-0046 §6.4 / ADR-0051 S4): no node yet, so the
    target `entry_type` rides in the body and the contract requires a title."""
    with translate_errors():
        return await _run_entry_patch_extraction(
            project, entry_type=request.entry_type, creating=True, request=request
        )
