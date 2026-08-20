from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.base import (
    AIPolicy,
)
from app.models.schema import PromptInputDefinition

# --- AI / machine settings ---

# Bounds for the master type scaler (#127): wide enough to matter, tight enough
# that pane chrome and prose stay laid out coherently.
UI_SCALE_MIN = 0.85
UI_SCALE_MAX = 1.5


class DisplaySettings(BaseModel):
    """Per-user prose-presentation preferences (#127 / #575): the master type
    scaler plus paragraph formatting. Display-only — never touches prose content.
    Applied as CSS custom properties on the document root by the frontend."""

    ui_scale: float = 1.0
    paragraph_align: Literal["left", "justify"] = "left"
    paragraph_indent: bool = False

    @field_validator("ui_scale")
    @classmethod
    def _clamp_ui_scale(cls, value: float) -> float:
        # Clamp rather than reject: a hand-edited config out of bounds is coerced
        # back into a sane layout instead of failing the whole settings load.
        return max(UI_SCALE_MIN, min(UI_SCALE_MAX, round(value, 3)))


class ProviderCredentialsView(BaseModel):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_host: str = ""


class RecentProject(BaseModel):
    path: str
    title: str
    opened_at: str   # ISO 8601


class RecentProjectView(RecentProject):
    """A recent-projects row as the settings view exposes it.

    Adds `within_root`, computed at view time and never stored: a recent that
    now points outside the machine projects root is shown as unavailable —
    equivalent to a deleted folder (#441) — rather than offered as a normal
    open. `within_root` is decided by a pure path comparison, so it never
    mis-flags a project on an unmounted drive the way a liveness stat would.
    """

    within_root: bool = True


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
    recent_projects: list[RecentProjectView] = Field(default_factory=list)
    palette: list[Swatch] = Field(default_factory=list)
    display: DisplaySettings = Field(default_factory=DisplaySettings)
    # The application-global default AI policy (#746) — resolved at the top of
    # every project's inheritance chain.
    ai_policy: AIPolicy = "off"
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
    # Prose-presentation prefs (#127 / #575). None = leave untouched; a value
    # replaces the whole block (all three fields travel together from the UI).
    display: DisplaySettings | None = None
    # The application-global default AI policy (#746). None = leave untouched.
    # Widening it is a permission change, so the UI applies it as its own
    # explicit gesture, never folded into the batched settings Save
    # (decisions_ai_permission_fails_closed).
    ai_policy: AIPolicy | None = None


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
    # Which assistant the check actually resolved and tested (#336). A ping
    # with no assistant_id resolves the topmost assistant, which is rarely the
    # one a given chat sends with — surfacing the name here keeps a green tick
    # from implying it tested "your AI" when it tested one specific assistant.
    # None only when the roster is empty (the legacy default_provider path).
    assistant_id: str | None = None
    assistant_name: str | None = None


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


class PromptInputConflict(BaseModel):
    """A same-name / different-type collision across the snippets a prompt
    includes (ADR-0061 §3). `types` are the distinct types seen for `name`, in
    encounter order. Surfaced in the author preview; never silently resolved."""

    name: str
    types: list[str] = Field(default_factory=list)


class AIPreviewRequest(BaseModel):
    template_source: str = Field(min_length=1)
    # ADR-0061 S2: the definitions of the inputs the author is editing (the open
    # prompt's own `inputs`). Sent only by the author preview pane, which needs
    # the effective set resolved against the LIVE body; the resolver unions these
    # with the includes' inputs. Empty for every other preview caller.
    own_inputs: list[PromptInputDefinition] = Field(default_factory=list)
    # ADR-0061 S2: resolve + return `effective_inputs`/`input_conflicts` for this
    # body. Off by default so the chat/dialog preview calls — which read the saved
    # roster's effective_inputs, not the live body — pay nothing for the resolve.
    resolve_effective_inputs: bool = False
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
    # ADR-0051 S5: the bound chat's `subject`. A scene subject is the chat's
    # anchored scene (the old target_scene_id), used as the lowest-priority
    # scene binding so a resumed chat renders `{{ scene }}` without the frontend
    # needing to know which subjects are scenes. Empty for non-chat previews.
    subject: str = ""
    # When set, the cost estimate uses this assistant's provider/model.
    # Omit for previews that aren't bound to an assistant (e.g. the
    # prompt-editor preview pane) — token counts still come back, only
    # the cost/cache fields are omitted.
    assistant_id: str | None = None


class PreviewContentBlock(BaseModel):
    text: str


class PreviewMessage(BaseModel):
    role: str
    blocks: list[PreviewContentBlock]


class PreviewCacheBlock(BaseModel):
    """One block of the **send-path composition** the model will receive
    (ADR-0060 §6): the system prefix, the tier-tagged lore the backend places
    (now visible in the preview again), then the uncached conversation turns.

    `tier` is the volatility class the send path assigns — `"stable"` (cached at
    1h on explicit-cache providers), `"volatile"` (5m), or `None` (uncached, e.g.
    a conversation turn). `text` is the block's content, so the author can *see*
    the lore that will be sent (not just its token size). The author cannot control
    placement but can now see it.
    """

    label: str
    role: str
    tokens: int
    tier: str | None = None
    text: str = ""


class PreviewErrorInfo(BaseModel):
    """Per-render error surfaced on `AIPreviewResponse.error` instead of an
    HTTP error. The /api/ai/preview endpoint is exploratory — the editor
    auto-fires it before the user has filled inputs — so render failures
    return 200 with this info populated rather than a thrown response.

    `kind` is a coarse tag so the frontend can craft a friendly message
    without re-parsing `message`:
      - "undefined"       → Jinja UndefinedError; `undefined_name` carries
                            the missing attribute when derivable, and
                            `undefined_namespace` the namespace it was accessed
                            on (`project` for `project.language`) when the miss
                            was an attribute on a real render-context object
                            rather than an undeclared input.
      - "syntax"          → TemplateSyntaxError; `line` is set.
      - "scene_not_found" → preview target_scene_id didn't resolve.
      - "other"           → anything else (catch-all).
    """

    message: str
    kind: str = "other"
    line: int | None = None
    col: int | None = None
    undefined_name: str | None = None
    undefined_namespace: str | None = None


class AIPreviewResponse(BaseModel):
    messages: list[PreviewMessage]
    warnings: list[str] = Field(default_factory=list)
    char_count: int
    session_id: str | None = None
    rendered: bool
    error: PreviewErrorInfo | None = None
    # Token estimate over the assembled wire bytes. Always populated.
    estimated_tokens: int = 0
    # The send-path composition (ADR-0060 §6): the system prefix (stable), the
    # tier-tagged lore the backend will place (visible again now that templates no
    # longer emit it), then the uncached conversation turns — as the model receives
    # it. Powers the cache strip UI. Empty when there is nothing to send.
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
    # ADR-0057 §2: whether the lore gate (`use_lore()` / `use()`) actually executed
    # during this render — the execution-derived lore gate. The frontend captures
    # this at the lock render and persists it as the chat's `lore_enabled`, so the
    # send path knows whether to inject lore at all. Always populated; False when
    # the template never called the helper.
    lore_enabled: bool = False
    # ADR-0060 §2: node ids the template selected via `use(node)`, deduped and in
    # insertion order. Captured at the lock render alongside `lore_enabled` and
    # persisted as the chat's `used_node_ids`, so the send path unions them into
    # its one lore selector. Empty when the template selected no nodes.
    used_node_ids: list[str] = Field(default_factory=list)
    # ADR-0060 §5: per-node volatility priors from `use(node, "stable"|"volatile")`,
    # keyed by id. Captured at the lock render beside `used_node_ids` and persisted
    # so the send path's tiering reads them. Empty when no node carried a hint.
    used_node_hints: dict[str, str] = Field(default_factory=dict)
    # ADR-0067 S2: the field descriptors this render registered via
    # `{% do field_contract.store(f) %}`, in insertion order. Captured at the lock
    # render alongside `used_node_ids` and persisted as the chat's
    # `field_contract_stored`, so the commit reads the SAME set back instead of
    # re-rendering a separate extractor contract. Empty when the prompt never
    # called `field_contract.store`.
    field_contract_stored: list[dict[str, Any]] = Field(default_factory=list)
    # ADR-0061 S2: the effective inputs of the previewed body — its own inputs ∪
    # the transitive union of every `{% include %}`-ed snippet's inputs — plus any
    # same-name/different-type conflict across those snippets. Populated only when
    # the request set `resolve_effective_inputs`; the author preview drives its
    # inputs panel from `effective_inputs` and shows `input_conflicts` as an error.
    # Resolved before the render, so they come back even when the render errors on
    # a not-yet-filled input.
    effective_inputs: list[PromptInputDefinition] = Field(default_factory=list)
    input_conflicts: list[PromptInputConflict] = Field(default_factory=list)
    # ADR-0061 S3b: which snippet contributed each INHERITED input — name →
    # source snippet id. Only names not declared by the outer prompt appear (an
    # own override is not inherited). The editor's two-tier Inputs list reads this
    # to render "inherited, from <snippet>"; the id → title lookup is the
    # frontend's (it holds the prompt roster). Populated with `effective_inputs`.
    input_provenance: dict[str, str] = Field(default_factory=dict)


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

    `kind` identifies the source — "manuscript" / "lore" / "snippet" point at an
    entry by id; "preset" carries a builtin preset name (e.g. "full_outline").
    """
    kind: Literal["manuscript", "lore", "snippet", "preset"]
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
    # ADR-0051 S2/S5: the node this chat is *about* — a lore entry, character, or
    # scene. Persisted as the `subject` entity_ref in the node's front-matter
    # `metadata`, so the index extracts a chat→subject edge and the subject
    # surfaces its conversations through the ordinary backlink machinery. Empty
    # for freeform chats. **A scene subject IS the chat's anchored scene** — S5
    # folded the old `target_scene_id` field into this one: the render/journal
    # scene is derived from `subject` (via `_subject_scene_id`), so `{{ scene }}`
    # and the as-of-scene name resolution keep working with no separate field.
    subject: str = ""
    # ADR-0055 S4: the mutation set this chat OWNS — its staged, position-free
    # change (a committing brainstorm's work-product). Persisted as a `staged_set`
    # entity_ref in the node's front-matter `metadata`, so the index extracts a
    # chat->set edge and the set survives closing the chat. Singular: a distinct
    # staged change is a new chat with its own context. Empty for impersonate /
    # freeform chats. Seeded into the AI context on send so a resumed conversation
    # continues refining the same change instead of restarting.
    staged_set: str = ""
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
    # ADR-0057 §2: the execution-derived lore gate. Whether this chat sees lore
    # is the prompt's own choice, expressed by whether `relevant_lore()` actually
    # ran during the chat's lock render (not a static text-scan, not a user
    # knob). Captured once from that render (§6) and stable thereafter. Gate off
    # → the send path injects no lore at all (Journey C: a deliberately lore-free
    # prompt stays clean). Defaults False so a chat that never ran the helper is
    # lore-free by construction.
    lore_enabled: bool = False
    # ADR-0060 §2: node ids the chat's prompt selected via `use(node)` at its lock
    # render, captured alongside `lore_enabled` and stable thereafter. The send
    # path unions these into its one deduped lore selector (`_relevant_lore`'s
    # direct channel), so an author-picked entry/scene/card lands in the tiered,
    # cached set — never emitted inline. Defaults empty (no selections).
    used_node_ids: list[str] = Field(default_factory=list)
    # ADR-0060 §5: per-node volatility priors from `use(node, hint)`, captured at
    # the lock render beside `used_node_ids` and stable thereafter. The send path's
    # `_tier_lore_ids` reads them as a revision-bounded placement bias. Empty = none.
    used_node_hints: dict[str, str] = Field(default_factory=dict)
    # ADR-0067 S2: the field descriptors this chat's lock render registered via
    # `field_contract`, captured beside `used_node_ids`/`used_node_hints` and
    # stable thereafter. The commit (`run_entry_patch_extraction`) reads this
    # back as the shape to extract — no re-render, no re-parse. Empty for a
    # chat whose prompt never called `field_contract.store` (a plain
    # conversation, or one authored before ADR-0067).
    field_contract_stored: list[dict[str, Any]] = Field(default_factory=list)
    # V2: running USD cost for this chat session, in the provider's currency
    # (USD; frontend converts to EUR for display). Re-derived on read as the
    # sum of this chat's priced ai_invocations rows. None — not 0.0 — when the
    # chat has no priced cost yet (fresh, or every turn ran an unpriced model):
    # "cost unknown", which the footer hides rather than showing a fabricated
    # "€0.00" (#697). The persisted YAML value stays 0.0 for round-trip and is
    # never consulted.
    cost_usd_total: float | None = 0.0
    # Per-cache-slot ISO timestamps of the most recent cache write. Slot
    # keys are short labels emitted by the chat dispatch ("system", "lore",
    # etc.). Powers the TTL countdown chips (step 9). Updated when a turn
    # writes to a slot (extracted via UsageMetrics.cache_write_tokens > 0).
    cache_write_times: dict[str, str] = Field(default_factory=dict)


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    # ADR-0051 S6: the node's identity type (`chat:chat_session`) so the roster
    # is a real EvalNode. The Chats pane flows through `evaluateView`, whose
    # default chat view membership is `descendants_of: chat:chat_session`; a bare
    # `"chat"` stamp would not descend from it and the designed view would filter
    # to empty. Carried from the file the roster already reads, not hand-stamped
    # in the frontend.
    entry_type: str = "chat:chat_session"
    # ADR-0051 S6: what the chat is about (`metadata.subject`), surfaced so a
    # designed view can group / filter by it — the marquee "group by subject".
    # Empty for freeform chats.
    subject: str = ""
    # ADR-0055 S4: the mutation set this chat owns (`metadata.staged_set`),
    # surfaced on the roster so a designed view can group / filter chats by
    # whether they carry a staged change. Empty for impersonate / freeform chats.
    staged_set: str = ""
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
    # ADR-0051 S2/S5: the node this chat is about (a brainstorm launch stamps the
    # originating lore entry; a scene launch stamps the scene). Persisted into
    # `metadata.subject`; a scene subject is the chat's anchored scene.
    subject: str = ""
    # ADR-0055 S4: an entity-pinned set this chat owns from the outset, if the
    # launch already staged one. Persisted into `metadata.staged_set`. Usually
    # empty at create (a brainstorm stages its set later, via save).
    staged_set: str = ""


class SaveChatSessionRequest(BaseModel):
    title: str
    prompt_entry_id: str = ""
    assistant_id: str = ""
    system_prompt: str = ""
    # ADR-0051 S2/S5: echoed back on every save so the subject survives per-turn
    # writes. Falls back to the persisted value when a caller omits it, so it is
    # never silently dropped. (Absorbed the old `target_scene_id` echo.)
    subject: str = ""
    # ADR-0055 S4: echoed on every save like `subject`, with the same persisted-
    # value fallback, so a per-turn write never drops the chat's staged set. The
    # commit path (S4) is what first sets it; general saves just carry it through.
    staged_set: str = ""
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
    # ADR-0057 §2: the lore gate, echoed like `subject`/`staged_set`. None =
    # "don't touch the persisted value" (general saves omit it); an explicit
    # bool sets it. Only the lock-render save (which learns it from the preview
    # response's `lore_enabled`) sends a value; thereafter it is preserved.
    lore_enabled: bool | None = None
    # ADR-0060 §2: the author-selected node ids, echoed like `lore_enabled`. None =
    # "leave the captured value alone" (general saves omit it); a list (even []) is
    # the new value. Only the lock-render save carries it (from the preview
    # response's `used_node_ids`); thereafter it is preserved.
    used_node_ids: list[str] | None = None
    # ADR-0060 §5: the per-node volatility priors, echoed like `used_node_ids`.
    # None = "leave the captured value alone"; a dict (even {}) is the new value.
    # Only the lock-render save carries it (from the preview response).
    used_node_hints: dict[str, str] | None = None
    # ADR-0067 S2: the field-contract set the lock render registered, echoed like
    # `used_node_ids`. None = "leave the captured value alone" (general saves);
    # a list (even []) is the new value. Only the lock-render save carries it
    # (from the preview response's `field_contract_stored`).
    field_contract_stored: list[dict[str, Any]] | None = None
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


class ValidateEntryPatchRequest(BaseModel):
    """POST /api/ai/entry-patch/{node_id} body — the model's raw finalize
    reply (ADR-0046 §6.3). Validated server-side into an `AIEntryPatch`; the
    raw text is never shown to the user unless it turns out garbled. The path
    is kind-neutral (ADR-0048 §5): the node's `entry_type` is resolved by id."""

    raw: str = ""


class ValidateEntryDraftRequest(BaseModel):
    """POST /api/ai/entry-draft body — the create-mode sibling (ADR-0046 §6.4).
    A from-scratch brainstorm has no node to key on, so the target
    `entry_type` is carried in the body and validation is scoped to it. Same
    `AIEntryPatch` result and garbled handling as the revise path."""

    entry_type: str = Field(min_length=1)
    raw: str = ""


class AIEntryPatch(BaseModel):
    """A validated, review-ready patch parsed from a brainstorm commit
    (ADR-0046 §4/§6.3).

    `fields` holds only schema-legal, proposable field values (references and
    computed excluded, §4); `dropped` names field ids that were present in the
    reply but rejected — unknown, illegal for the type, non-proposable, or an
    invalid value — so the review can note what the model tried and missed.
    `garbled` is true when the reply could not be read as a JSON object at all,
    the condition surfaced to the author instead of a silent no-op."""

    body: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    dropped: list[str] = Field(default_factory=list)
    garbled: bool = False


class ExtractEntryPatchRequest(BaseModel):
    """POST /api/ai/entry-patch/{node_id}/extract body — ADR-0051 S4 / ADR-0067 S2.

    The commit runs as a **cached continuation** of the chat itself: `chat_id`
    is the chat's real id, so the server reads back the field set its lock
    render registered (`ChatSession.field_contract_stored`) and continues the
    SAME cached system prefix + lore rather than re-shipping the transcript
    under a freshly-rendered contract. `messages` is the visible transcript,
    sent as ordinary conversation history (the provider call is stateless per
    request, same as every other turn of this chat)."""

    messages: list[ChatMessage] = Field(default_factory=list)
    assistant_id: str | None = None
    chat_id: str = Field(min_length=1)


class ExtractEntryDraftRequest(ExtractEntryPatchRequest):
    """Create-mode sibling — no node exists yet, so the target `entry_type`
    rides in the body (ADR-0046 §6.4 / ADR-0051 S4)."""

    entry_type: str = Field(min_length=1)


class EntryPatchExtraction(BaseModel):
    """Result of a fresh extraction (ADR-0051 S4): the validated, review-ready
    `patch` plus the `cost_usd` of the extraction turn, which the caller
    attributes to the session the same way a streamed turn's cost is. `patch` is
    null and `ok` false when the extraction model call itself failed or returned
    nothing (distinct from a `garbled` patch, which still round-trips as a patch
    so the author is told to finalize again)."""

    patch: AIEntryPatch | None = None
    cost_usd: float | None = None
    ok: bool = True
    error: str | None = None


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
