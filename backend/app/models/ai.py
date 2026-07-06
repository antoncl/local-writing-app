from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.base import (
    AIPolicy,
)

# --- AI / machine settings ---


class ProviderCredentialsView(BaseModel):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_host: str = ""


class RecentProject(BaseModel):
    path: str
    title: str
    opened_at: str   # ISO 8601


class Swatch(BaseModel):
    """A named entry in the machine-level color palette.

    `id` is stable — entries, type defaults, and select options reference
    a swatch by id, never by hex. Renaming or recoloring a swatch updates
    everything that references it. `hex` is validated as `#RRGGBB`.
    """

    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    label: str = Field(min_length=1)
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class MachineSettingsView(BaseModel):
    version: int
    providers: ProviderCredentialsView
    default_provider: str
    default_models: dict[str, str]
    default_projects_folder: str = ""
    recent_projects: list[RecentProject] = Field(default_factory=list)
    palette: list[Swatch] = Field(default_factory=list)
    config_path: str


class ProviderCredentialsPatch(BaseModel):
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    ollama_host: str | None = None


class MachineSettingsUpdate(BaseModel):
    providers: ProviderCredentialsPatch | None = None
    default_provider: str | None = None
    default_models: dict[str, str] | None = None
    default_projects_folder: str | None = None
    # Replace the recent-projects list (e.g. user removed a stale entry).
    # None = leave untouched; an explicit list rewrites it verbatim.
    recent_projects: list[RecentProject] | None = None
    # Replace the whole palette list. None = leave untouched.
    palette: list[Swatch] | None = None


class AIHealthRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    assistant_id: str | None = None


class AIHealthResponse(BaseModel):
    provider: str
    model: str
    ok: bool
    latency_ms: int
    policy: AIPolicy
    error: str | None = None


class AIProviderInfo(BaseModel):
    """Lightweight provider listing for the picker's provider dropdown."""

    name: str
    display_name: str


class AIProviderList(BaseModel):
    providers: list[AIProviderInfo]


class AIModelInfo(BaseModel):
    """Wire-format mirror of `ModelDescriptor` (in
    `app.services.ai.profiles.base`). Strings instead of enums so the
    JSON shape stays stable across enum additions."""

    id: str
    display_name: str
    provider: str
    context_window: int
    tier: str
    capabilities: list[str]
    deprecated: bool = False
    sunset_date: str | None = None
    successor: str | None = None
    cost_in_per_mtok: float | None = None
    cost_out_per_mtok: float | None = None
    cache_read_multiplier: float | None = None


class AIProviderModelList(BaseModel):
    provider: str
    models: list[AIModelInfo]


class AITierResolution(BaseModel):
    """Result of asking a provider profile to resolve a tier to a model id.

    `model_id` is null when the tier has no candidates (e.g. requesting
    PREMIUM from Ollama, or any tier when the provider's discovery is
    offline and bake-in is empty)."""

    provider: str
    tier: str
    model_id: str | None


class AIPreviewRequest(BaseModel):
    template_source: str = Field(min_length=1)
    # Empty string is allowed: chat-routed prompts don't need a scene context.
    # build_preview skips scene resolution in that case and `scene` becomes None.
    target_scene_id: str = ""
    session_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    text_before: str = ""
    text_after: str = ""
    selection: str = ""
    commit: bool = False
    # Explicit mutation resolution scene from a `scene_ref` input (ADR-0012);
    # the frontend resolves the input value here. Overrides target_scene_id.
    resolution_scene_id: str = ""
    # When set, the cost estimate uses this assistant's provider/model.
    # Omit for previews that aren't bound to an assistant (e.g. the
    # prompt-editor preview pane) — token counts still come back, only
    # the cost/cache fields are omitted.
    assistant_id: str | None = None


class PreviewContentBlock(BaseModel):
    text: str
    cache_break_after: bool


class PreviewMessage(BaseModel):
    role: str
    blocks: list[PreviewContentBlock]


class PreviewCacheBlock(BaseModel):
    """One cache block derived from `cache_break_after` markers on the
    rendered messages. Labels are position-derived for v1; richer
    naming may come later (template hints, role-based, etc.).
    """

    label: str
    role: str
    tokens: int
    cache_break_after: bool


class PreviewErrorInfo(BaseModel):
    """Per-render error surfaced on `AIPreviewResponse.error` instead of an
    HTTP error. The /api/ai/preview endpoint is exploratory — the editor
    auto-fires it before the user has filled inputs — so render failures
    return 200 with this info populated rather than a thrown response.

    `kind` is a coarse tag so the frontend can craft a friendly message
    without re-parsing `message`:
      - "undefined"       → Jinja UndefinedError; `undefined_name` carries
                            the missing attribute when derivable.
      - "syntax"          → TemplateSyntaxError; `line` is set.
      - "scene_not_found" → preview target_scene_id didn't resolve.
      - "other"           → anything else (catch-all).
    """

    message: str
    kind: str = "other"
    line: int | None = None
    col: int | None = None
    undefined_name: str | None = None


class AIPreviewResponse(BaseModel):
    messages: list[PreviewMessage]
    warnings: list[str] = Field(default_factory=list)
    char_count: int
    session_id: str | None = None
    rendered: bool
    error: PreviewErrorInfo | None = None
    # Token estimate over the assembled wire bytes. Always populated.
    estimated_tokens: int = 0
    # Per-cache-block breakdown — powers the cache strip UI. Each entry
    # is one run of blocks ending at a `cache_break_after` marker (or
    # the end of the message). Empty when there are no rendered messages.
    cache_blocks: list[PreviewCacheBlock] = Field(default_factory=list)
    # Pre-send input-side cost in USD. Frontend converts to EUR for
    # display (see decisions_currency_display). Null when no assistant
    # is bound or pricing is unknown (Ollama, live discovery failure).
    estimated_cost_usd: float | None = None
    # When an assistant is bound, surface its provider/model so the
    # frontend can label the estimate. Null otherwise.
    provider: str | None = None
    model: str | None = None
    # caching_style from the resolved provider (`none` / `auto` /
    # `explicit`). Drives whether the cache strip shows in the UI.
    # Null when no assistant is bound.
    caching_style: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AIChatRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    assistant_id: str | None = None
    system_prompt: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    max_tokens: int | None = None
    # Optional chat session id. When present the server runs the implicit-
    # context expander on the last user message, appends new detections to
    # ChatSession.journal, and packs the journal into a cache-stable block
    # between system_prompt and conversation history.
    chat_id: str | None = None


class ChatUsage(BaseModel):
    """Per-call token counts mirrored from the dispatch layer's
    `UsageMetrics` dataclass. The three input slots are disjoint —
    sum (input + cached_input + cache_write) for the total billable
    input. Costs come from `compute_cost(UsageMetrics, descriptor)`.
    """

    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0


class AIChatResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str
    provider: str
    model: str
    latency_ms: int
    policy: AIPolicy
    ok: bool
    error: str | None = None
    stop_reason: str | None = None
    truncated: bool = False
    # Lore entries newly auto-detected on THIS turn (for the audit UI chip
    # strip). Empty when no detections fired. Snapshots — frontend doesn't
    # need to look up titles separately.
    journal_added: list[ChatSessionJournalEntry] = Field(default_factory=list)
    # V2: per-call telemetry. Null on failure paths and when the provider
    # response didn't include usage (rare). Cost is null when pricing
    # isn't known (Ollama, descriptor lookup failure). Frontend converts
    # to EUR for display (see decisions_currency_display).
    usage: ChatUsage | None = None
    cost_usd: float | None = None


class AIGenerateRequest(BaseModel):
    template_source: str = Field(min_length=1)
    target_scene_id: str = Field(min_length=1)
    session_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    text_before: str = ""
    text_after: str = ""
    selection: str = ""
    commit: bool = False
    # Explicit mutation resolution scene from a `scene_ref` input (ADR-0012);
    # the frontend resolves the input value here. Overrides target_scene_id.
    resolution_scene_id: str = ""
    provider: str | None = None
    model: str | None = None
    assistant_id: str | None = None
    max_tokens: int | None = None


class AIGenerateResponse(BaseModel):
    content: str
    rendered_messages: list[PreviewMessage] = Field(default_factory=list)
    rendered_warnings: list[str] = Field(default_factory=list)
    char_count: int
    provider: str
    model: str
    latency_ms: int
    policy: AIPolicy
    ok: bool
    error: str | None = None
    stop_reason: str | None = None
    truncated: bool = False
    session_id: str | None = None
    # V2 telemetry — see AIChatResponse for the rules.
    usage: ChatUsage | None = None
    cost_usd: float | None = None


class AIContextPresetResponse(BaseModel):
    kind: str
    content: str


class ProjectCostChatRow(BaseModel):
    id: str
    title: str
    cost_usd: float


class ProjectCostResponse(BaseModel):
    """V2: sum of chat session costs in the current project. Frontend
    converts to EUR for display (see decisions_currency_display)."""

    total_usd: float
    chats: list[ProjectCostChatRow] = Field(default_factory=list)


# --- Persistent chat sessions (Phase 3) ---


class ChatSessionJournalEntry(BaseModel):
    """One lore entry auto-detected into the chat's implicit context.

    The journal is append-only across the session: once an entity has been
    detected (textually or via depth-1 expansion of another detection), it
    stays in scope for every subsequent turn. This monotonic shape lets the
    prompt cache breakpoint after the journal ratchet forward as the
    journal grows, without invalidating earlier turns' caches.

    `title` and `entry_type` are snapshots at detection time so the audit
    UI keeps showing what the user saw, even if the lore entry is later
    renamed or retyped.

    `source` records WHY the entry entered scope. Useful for the audit UI
    and for debugging surprising auto-includes.
    """
    entry_id: str
    title: str = ""
    entry_type: str = ""
    added_at_turn: int = 0
    source: Literal["user_message", "rendered_prompt", "depth1_expansion"] = "user_message"


class ChatSessionMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    thinking: str = ""
    truncated: bool = False
    # Lore entries that the implicit-context expander auto-detected on the
    # turn this assistant message belongs to. Captured for the audit UI so
    # reopening the chat preserves the "added when you said X" trail.
    # Always empty on user messages (detection happens between user and
    # assistant, attributed to the assistant turn).
    journal_added: list[ChatSessionJournalEntry] = Field(default_factory=list)
    # V2: per-turn token + cost telemetry, captured from the streamed
    # response. Always null on user messages. Frozen value at time-of-
    # send — historical cost doesn't drift when pricing changes.
    usage: ChatUsage | None = None
    cost_usd: float | None = None


class ChatSessionContextItem(BaseModel):
    """A context attachment carried with the chat across turns.

    `kind` identifies the source — "scene" / "lore" / "snippet" point at an
    entry by id; "preset" carries a builtin preset name (e.g. "full_outline").
    """
    kind: Literal["scene", "lore", "snippet", "preset"]
    id: str
    entry_type: str = ""
    title: str = ""


class ChatSession(BaseModel):
    id: str
    title: str
    # The locked preset for this chat. Once messages exist, prompt_entry_id,
    # assistant_id, and system_prompt cannot change — switching requires starting
    # a new chat. This keeps the Anthropic cache prefix stable across turns.
    prompt_entry_id: str = ""
    assistant_id: str = ""
    system_prompt: str = ""
    # Scene this chat was opened against (e.g. "invoke chat prompt" from a
    # prose scene). The first-send template render passes it as the `scene`
    # binding so prompts that reference scene body/metadata resolve it.
    # Empty for freeform chats and chats started from the Chats pane.
    target_scene_id: str = ""
    pinned: bool = False
    created_at: str
    updated_at: str
    context_items: list[ChatSessionContextItem] = Field(default_factory=list)
    messages: list[ChatSessionMessage] = Field(default_factory=list)
    # Per-input draft values keyed by input.name. Persisted so reopening
    # a half-configured chat (drafts entered but not yet sent) restores
    # what the user typed. After first send, the values are locked
    # along with system_prompt (template was rendered with them).
    inputs: dict[str, Any] = Field(default_factory=dict)
    # Append-only log of entities auto-detected into this chat's implicit
    # context. Grows as the user types new names across turns. See
    # ChatSessionJournalEntry for the per-entry shape.
    journal: list[ChatSessionJournalEntry] = Field(default_factory=list)
    # V2: running USD cost for this chat session, in the provider's currency
    # (USD; frontend converts to EUR for display). Incremented turn-by-turn
    # via save_chat_session(cost_delta_usd=...). Frozen value at time-of-
    # send — does NOT recompute if model pricing changes.
    cost_usd_total: float = 0.0
    # Per-cache-slot ISO timestamps of the most recent cache write. Slot
    # keys are short labels emitted by the chat dispatch ("system", "lore",
    # etc.). Powers the TTL countdown chips (step 9). Updated when a turn
    # writes to a slot (extracted via UsageMetrics.cache_write_tokens > 0).
    cache_write_times: dict[str, str] = Field(default_factory=dict)


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    prompt_entry_id: str = ""
    assistant_id: str = ""
    pinned: bool = False
    created_at: str
    updated_at: str
    message_count: int = 0
    # All-time running USD cost; rendered as EUR in the chats pane chip.
    # Matches ChatSession.cost_usd_total — the file is the source of truth.
    cost_usd_total: float = 0.0


class ChatSessionList(BaseModel):
    sessions: list[ChatSessionSummary]


class CreateChatSessionRequest(BaseModel):
    title: str = ""
    prompt_entry_id: str = ""
    assistant_id: str = ""
    system_prompt: str = ""
    target_scene_id: str = ""


class SaveChatSessionRequest(BaseModel):
    title: str
    prompt_entry_id: str = ""
    assistant_id: str = ""
    system_prompt: str = ""
    target_scene_id: str = ""
    pinned: bool = False
    context_items: list[ChatSessionContextItem] = Field(default_factory=list)
    messages: list[ChatSessionMessage] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    # None = "don't touch the persisted journal". A list (even []) means
    # "this is the new journal value" and is subject to the append-only
    # guard. The chat-send endpoint is the only intended producer of new
    # journal entries; general saves (rename, message append, etc.)
    # should omit the field so the journal persists untouched.
    journal: list[ChatSessionJournalEntry] | None = None
    # V2: optional incremental cost update. When provided (typically by
    # the chat panel after a successful AI turn), it's ADDED to the
    # persisted cost_usd_total. Omit on plain renames / message-list saves.
    cost_delta_usd: float | None = None
    # V2: when provided, each slot name has its cache_write_times entry
    # set to the server's current ISO timestamp. Frontend sends the labels
    # for any slot whose `cache_write_tokens` was > 0 in the response.
    cache_write_slots: list[str] | None = None


class AIInvocation(BaseModel):
    """Append-only telemetry record for one accepted AI invocation
    (continuation, roleplay, or chat turn). The cost computed field sums
    these by scope. Storage: <project>/ai_invocations.yaml. Not a Node
    kind for MVP — sidecar log; promote to a kind later if an audit-log
    UI surfaces.
    """
    id: str
    ts: str
    prompt_entry_id: str = ""
    prompt_entry_type: str = ""
    scene_id: str = ""
    character_id: str = ""
    # Phase C2 Slice B: chat-session attribution. Populated for rows
    # logged via the chat-save path; empty for accept-flow rows.
    chat_session_id: str = ""
    provider: str = ""
    model: str = ""
    usage: ChatUsage | None = None
    cost_usd: float | None = None


class AIInvocationList(BaseModel):
    invocations: list[AIInvocation] = Field(default_factory=list)


class CreateAIInvocationRequest(BaseModel):
    """POST /api/ai/invocations body. Server assigns id + ts; everything
    else flows from the prior generate response and the accept context.
    """
    prompt_entry_id: str = ""
    prompt_entry_type: str = ""
    scene_id: str = ""
    character_id: str = ""
    chat_session_id: str = ""
    provider: str = ""
    model: str = ""
    usage: ChatUsage | None = None
    cost_usd: float | None = None
# AIChatResponse declares journal_added as a forward reference because
# ChatSessionJournalEntry is defined later in the file (in the chat-session
# section). Resolve it once everything is in scope.
AIChatResponse.model_rebuild()
