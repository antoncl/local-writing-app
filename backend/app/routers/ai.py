"""AI provider, preview, chat, generate, streaming, and cost routes (#170 main.py split)."""
from __future__ import annotations

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
    CreateAIInvocationRequest,
    EntryPatchExtraction,
    ExtractEntryDraftRequest,
    ExtractEntryPatchRequest,
    PreviewContentBlock,
    PreviewErrorInfo,
    PreviewMessage,
    ValidateEntryDraftRequest,
    ValidateEntryPatchRequest,
)
from app.runtime import CurrentProject, translate_errors
from app.services import machine_settings as machine_settings_service
from app.services.ai import providers as ai_providers
from app.services.ai import tokens as ai_tokens
from app.services.ai.call_resolver import resolve_call_params
from app.services.ai.chat import (
    expand_and_prepare_chat_blocks,
    run_chat_turn,
    system_prompt_cache_blocks,
)
from app.services.ai.extraction import run_entry_patch_extraction
from app.services.ai.preview import (
    PreviewError,
    PreviewRequest,
    build_chat_payload,
    build_preview,
    estimate_preview_tokens_and_cost,
)
from app.services.ai.profiles import CapabilityTier, ModelDescriptor
from app.services.ai.profiles.registry import known_provider_names, profile_for
from app.services.ai.streaming import transform_provider_events_to_ndjson
from app.services.ai.usage import translate_usage_to_cost
from app.services.project_service import ProjectServiceError

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
    result = ai_providers.health_check(
        provider_name=resolved.provider,
        model=resolved.model,
        settings=settings,
        policy=policy,
    )
    # Report which assistant was actually resolved so the readout can say
    # "✓ via <name>" — a ping with no assistant_id tests the topmost assistant,
    # not the one a given chat sends with (#336). None only when the roster is
    # empty and resolution fell through to the legacy default_provider path.
    assistant = project.resolve_assistant(request.assistant_id)
    if assistant is not None:
        result.assistant_id = assistant.id
        result.assistant_name = assistant.title
    return result


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
                project,
                PreviewRequest(
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
                ),
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
                    undefined_namespace=exc.undefined_namespace,
                ),
            )

    messages = [
        PreviewMessage(
            role=m.role,
            blocks=[
                PreviewContentBlock(text=b.text)
                for b in m.blocks
            ],
        )
        for m in rendered.messages
    ]
    char_count = sum(len(b.text) for m in messages for b in m.blocks)

    settings = machine_settings_service.load_settings()
    estimate = await estimate_preview_tokens_and_cost(
        project, rendered, assistant_id=request.assistant_id, settings=settings
    )

    return AIPreviewResponse(
        messages=messages,
        warnings=rendered.warnings,
        char_count=char_count,
        session_id=session_id,
        rendered=True,
        estimated_tokens=estimate.estimated_tokens,
        cache_blocks=estimate.cache_blocks,
        estimated_cost_usd=estimate.estimated_cost_usd,
        provider=estimate.provider,
        model=estimate.model,
        caching_style=estimate.caching_style,
        # ADR-0057 §2: the execution-derived lore gate, captured from this
        # render so the frontend can persist it as the chat's `lore_enabled`.
        lore_enabled=rendered.lore_invoked,
        # ADR-0060 §2: node ids the template selected via `use(node)`, captured
        # here so the lock-render save can persist them as `used_node_ids`.
        used_node_ids=rendered.used_node_ids,
        # ADR-0060 §5: the per-node volatility priors from `use(node, hint)`.
        used_node_hints=rendered.used_node_hints,
    )


# --- AI: chat completion (first real model call) ---


@router.post("/api/ai/chat", response_model=AIChatResponse)
async def ai_chat(project: CurrentProject, request: AIChatRequest) -> AIChatResponse:
    return await run_chat_turn(project, request)


# --- AI: generate (template + provider, the full pipeline) ---


@router.post("/api/ai/generate", response_model=AIGenerateResponse)
async def ai_generate(project: CurrentProject, request: AIGenerateRequest) -> AIGenerateResponse:
    with translate_errors():
        try:
            rendered, session_id = build_preview(
                project,
                PreviewRequest(
                    template_source=request.template_source,
                    target_scene_id=request.target_scene_id,
                    session_id=request.session_id,
                    inputs=request.inputs,
                    text_before=request.text_before,
                    text_after=request.text_after,
                    selection=request.selection,
                    commit=request.commit,
                    resolution_scene_id=request.resolution_scene_id,
                ),
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
                PreviewContentBlock(text=b.text)
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

    # Chat gets its system block via expand_and_prepare_chat_blocks (with
    # journal expansion, which is chat-specific); generate shares only the
    # system-prompt cache wrap so the two never drift on caching.
    system_blocks = system_prompt_cache_blocks(system_prompt)

    result = ai_providers.chat(
        resolved.to_call(
            system_prompt=system_prompt,
            messages=chat_messages,
            system_blocks=system_blocks,
            session_id=session_id,
        ),
        provider_name=resolved.provider,
        settings=settings,
        policy=policy,
    )
    truncated = result.stop_reason in {"max_tokens", "length"}
    usage_wire, cost_usd = await translate_usage_to_cost(
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


# --- AI: streaming variants (NDJSON) --- (line protocol in services/ai/streaming.py)


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
    system_blocks, session_id, journal_added = expand_and_prepare_chat_blocks(
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
    return StreamingResponse(
        transform_provider_events_to_ndjson(
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
                project,
                PreviewRequest(
                    template_source=request.template_source,
                    target_scene_id=request.target_scene_id,
                    session_id=request.session_id,
                    inputs=request.inputs,
                    text_before=request.text_before,
                    text_after=request.text_after,
                    selection=request.selection,
                    commit=request.commit,
                    resolution_scene_id=request.resolution_scene_id,
                ),
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
    # Shares the exact system-block wrap with the non-streaming path so the
    # two can't drift into caching in one mode but not the other.
    system_blocks = system_prompt_cache_blocks(system_prompt)

    events = ai_providers.chat_stream(
        resolved.to_call(
            system_prompt=system_prompt,
            messages=chat_messages,
            system_blocks=system_blocks,
            session_id=session_id,
        ),
        provider_name=resolved.provider,
        settings=settings,
        policy=policy,
    )
    return StreamingResponse(
        transform_provider_events_to_ndjson(
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


# --- AI: fresh-extraction commit (ADR-0051 S4; orchestration in services/ai/extraction) ---


@router.post("/api/ai/entry-patch/{node_id}/extract", response_model=EntryPatchExtraction)
async def extract_entry_patch(
    project: CurrentProject, node_id: str, request: ExtractEntryPatchRequest
) -> EntryPatchExtraction:
    """Revise-mode fresh extraction (ADR-0051 S4). The target `entry_type` is
    resolved from the node index by id, then the contract + turn + validate run.
    Read-only — the adopted patch is written through the node's own save path."""
    with translate_errors():
        entry_type = project.entry_type_for_node(node_id)
        return await run_entry_patch_extraction(
            project, entry_type=entry_type, creating=False, request=request
        )


@router.post("/api/ai/entry-draft/extract", response_model=EntryPatchExtraction)
async def extract_entry_draft(
    project: CurrentProject, request: ExtractEntryDraftRequest
) -> EntryPatchExtraction:
    """Create-mode sibling (ADR-0046 §6.4 / ADR-0051 S4): no node yet, so the
    target `entry_type` rides in the body and the contract requires a title."""
    with translate_errors():
        return await run_entry_patch_extraction(
            project, entry_type=request.entry_type, creating=True, request=request
        )
