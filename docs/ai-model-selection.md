# AI Model Selection — Design Note

## Problem

Most users don't know what models a given provider offers, what their pros and
cons are, or how to compare them. Today the Assistant editor exposes
`ai_provider` + `ai_model` as free-text fields, which requires the user to
already know the exact model id. Model rosters churn frequently; baked-in
dropdowns go stale within weeks.

We want a picker that:

- Defaults to a high-level **capability tier** (Fast / Balanced / Premium /
  Reasoning / Local) rather than a raw model id.
- **Discovers models live** from each provider, so the catalogue stays current
  without code changes.
- Supports adding new providers and **gracefully sunsetting** deprecated
  models without breaking existing assistants.
- Bakes **prompt caching** in at the dispatch layer — a transparent cost win
  that lands with this work, even though the runtime cache-TTL UX is a
  separate v2 effort.

## Scope (v1)

In scope:

- `ProviderProfile` abstract + concrete per-provider implementations
  (Anthropic, OpenAI, OpenRouter, Ollama).
- Live `list_models()` per provider with a per-machine cache and offline
  fallback.
- Capability-tier UX as the primary picker; exact model picker under an
  **Advanced** disclosure.
- Save-time tier resolution (frontend writes the literal `ai_model`).
- Caching baked into the dispatch layer, no user-facing controls yet.

Out of scope (v2 or later):

- Cost surfacing (per-session cost in chat, per-assistant spend totals,
  expensive-send warnings).
- Cache TTL countdown, refresh-on-edit, manual cache controls.
- Ollama "Pull model" button in the picker.

## Data model

```python
# backend/app/services/ai/profiles/base.py

class CapabilityTier(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    PREMIUM = "premium"
    REASONING = "reasoning"
    LOCAL = "local"           # Ollama-only; not a tier for cloud providers

class Capability(str, Enum):
    VISION = "vision"
    TOOLS = "tools"
    THINKING = "thinking"
    CACHING = "caching"

@dataclass
class ModelDescriptor:
    id: str                              # provider's canonical id (e.g. "claude-sonnet-4-6")
    display_name: str                    # short, human-readable ("Sonnet 4.6")
    provider: str                        # "anthropic" / "openai" / "openrouter" / "ollama"
    context_window: int
    tier: CapabilityTier
    capabilities: set[Capability]
    deprecated: bool = False
    sunset_date: date | None = None
    successor: str | None = None         # suggested replacement model id
    # Cost fields drive tier auto-rank now; UI surfacing is v2.
    cost_in_per_mtok: float | None = None
    cost_out_per_mtok: float | None = None
    cache_read_multiplier: float | None = None  # e.g. 0.25 = cache read is 25% of input cost

class ProviderProfile(ABC):
    name: str
    display_name: str

    @abstractmethod
    async def list_models(self, *, force_refresh: bool = False) -> list[ModelDescriptor]: ...

    @abstractmethod
    def caching_style(self, model_id: str) -> Literal["none", "auto", "explicit"]: ...
```

## Provider implementations

| Profile | `list_models()` source | Notes |
|---|---|---|
| `AnthropicProfile` | `GET /v1/models` + bake-in tier + cost map | Caching is `explicit` — wrap stable content with `cache_control: ephemeral` |
| `OpenAIProfile` | `GET /v1/models` + bake-in tier + cost map | Caching is `auto` — no markup needed |
| `OpenRouterProfile` | `GET /api/v1/models` (carries pricing, context, capabilities) | Caching style per-model; OpenRouter routes through to underlying provider. Pass `session_id` for sticky routing across turns |
| `OllamaProfile` | `GET /api/tags` (local install) | All models tier=`LOCAL`; no auto-rank, picker just lists them. `caching_style: none` |

The bake-in tier + cost map for Anthropic/OpenAI lives in
`backend/app/services/ai/profiles/_baked_in.yaml`. Refresh process is manual:
when a new model drops, add a line. Acceptable maintenance burden for v1
because the alternative — scraping pricing pages — is brittle.

## Tier resolution

When the user picks a tier, the resolver chooses the **cheapest non-deprecated
model in that tier** (sorted by `cost_in_per_mtok`). Tie-break: highest
`context_window`, then most recent (by descriptor list order).

Rationale: matches the "users don't know models" framing — they trust the
app to pick a sensible default. Power users will balk eventually ("but I
*want* the more expensive one!"); the Advanced disclosure escape hatch is
their pressure valve. If complaints accumulate, revisit with a curated
priority list per (provider, tier) — but only when there's a concrete
reason.

Ollama is the exception: tier=`LOCAL` is the only valid tier for Ollama
assistants, and the model picker is the actual selector (no auto-rank since
all local models are free).

## Caching strategy

The dispatch layer ([providers.py](../backend/app/services/ai/providers.py))
consults `profile.caching_style(model_id)` for each request:

- `"none"` — no markup. Send normally.
- `"auto"` — no markup. Provider caches transparently (OpenAI, DeepSeek,
  Gemini 2.5 via OpenRouter).
- `"explicit"` — wrap the system message and any large stable user-block
  content with `{"cache_control": {"type": "ephemeral"}}`. Anthropic
  direct, plus Anthropic/Alibaba/Gemini via OpenRouter.

Cost win is immediate and silent. No UI surface in v1 — `prompt_tokens_details.cached_tokens`
in responses is the only feedback. v2 surfaces this.

OpenRouter's `session_id` (passed as request header `x-session-id`) pins
sticky routing across turns within a chat session, which keeps the cache
warm without manual intervention. Use the chat session id directly.

Reference: [OpenRouter prompt caching guide](https://openrouter.ai/docs/guides/best-practices/prompt-caching).

## Cache lookup

A per-machine cache file holds the last successful `list_models()` per
provider with a fetched-at timestamp:

```
~/.config/local_writing_app/provider_models_cache.yaml
```

Refresh triggers:

- App start: background, non-blocking — picker renders cached data with a
  small "refreshing…" indicator until the refresh returns.
- Manual "Refresh models" button in the picker.
- Stale beyond 24h: refresh on next picker open.

If a refresh fails (offline, API down), the picker continues with cached
data and shows a small warning chip.

## Frontend: Assistant builder picker

```
Subscription:  [Anthropic                              ▾]
Capability:    [⚖ Balanced — Sonnet 4.6                ▾]
                 ⚡ Fast       — Haiku 4.5
                 ⚖ Balanced   — Sonnet 4.6     ← current
                 ✨ Premium    — Opus 4.8
                 🧠 Reasoning  — Opus 4.8 (thinking)

▸ Advanced
    Model:       [claude-sonnet-4-6                   ▾]   ← overrides tier
    Temperature: [0.7]    Max tokens: [4096]
    Thinking:    [ ] enable
```

- Tier dropdown shows resolved model alongside the tier label.
- Picking a model in **Advanced** sets `ai_capability_tier = ""` (custom).
- Switching tier auto-resolves model and writes both fields.
- Switching provider re-resolves the current tier against the new provider's
  catalogue (or clears the tier if not available, e.g. switching to Ollama).

## Assistant entry schema changes

Add one field, keep the existing two:

| Field | Type | Behaviour |
|---|---|---|
| `ai_provider` | text | Existing. `"anthropic"` / `"openai"` / `"openrouter"` / `"ollama"`. |
| `ai_capability_tier` | text, optional | **New.** Tier enum value or `""` for explicit-model mode. |
| `ai_model` | text | Existing. Literal model id used for dispatch. |

**Resolution is save-time, frontend-side.** When the user picks a tier, the
frontend asks the profile (via a new `GET /api/ai/providers/<name>/resolve-tier?tier=balanced`
endpoint) for the resolved model, then writes both fields. Backend dispatch
reads only `ai_provider` + `ai_model`.

Why save-time and not request-time:

- **Predictable.** The model the user saw at save time is the model used at
  runtime. No silent drift if the tier mapping changes upstream.
- **Backend stays dumb.** Dispatch doesn't need to import profile logic.
- Trade-off: when new models drop, existing assistants don't auto-upgrade.
  Acceptable — re-saving the assistant picks up the new default.

## Migration

Existing assistants have `ai_provider` + `ai_model`. After this lands:

- Loader defaults `ai_capability_tier = ""` (explicit-model mode) for every
  existing entry. Zero-touch.
- Users opt into tier mode by picking from the new dropdown.
- No schema version bump required — the new field is optional.

## Sunset handling

When a model is marked `deprecated: true` in its descriptor:

- Picker greys it out and shows its `sunset_date` + suggested `successor`.
- Existing assistants that reference it load without error; the picker shows
  a one-line warning ("This model will be retired on …; consider switching
  to <successor>").
- After `sunset_date` passes, the picker hides it entirely; existing
  assistants still load, but a more prominent warning fires.

## Project-level defaults

The dormant `ai_default_model_class` field on `ProjectInfo`
([project_service.py:406](../backend/app/services/project_service.py:406))
becomes the project's default tier, inherited by newly-created assistants.
Existing field, currently never read by anything else — safe to repurpose.

## Files touched (estimated)

New:

- `backend/app/services/ai/profiles/` — new package
  - `base.py` — abstract + dataclasses
  - `anthropic.py`, `openai.py`, `openrouter.py`, `ollama.py`
  - `_baked_in.yaml` — fallback tier + cost data for providers that don't
    publish pricing
- `backend/app/services/ai/profile_cache.py` — per-machine model cache
- `frontend/src/ProviderTierPicker.svelte` — extractable picker
  component

Modified:

- `backend/app/services/ai/providers.py` — consult `caching_style` per
  request; add `session_id` header for OpenRouter
- `backend/app/main.py` — `/api/ai/providers` listing, `/api/ai/providers/<name>/models`,
  `/api/ai/providers/<name>/resolve-tier`
- `backend/app/services/project_service.py` — repurpose `ai_default_model_class`
  to mean tier
- `frontend/src/App.svelte` — Assistant builder picker swap-out

## Open questions for v2

- **Cost surfacing.** Schema is in place (`cost_*` on descriptors). UI
  surfaces: per-session running cost in chat pane, per-assistant total
  spend, expensive-send warning. Lands as its own feature.
- **Cache TTL countdown.** Anthropic's 5-min default cache window; show a
  ticking indicator in chat pane, offer auto-refresh-on-typing. Sister
  feature with its own state machine.
- **Ollama Pull-from-picker.** Use `POST /api/pull` with streaming progress;
  surface disk-space warnings; auto-refresh `list_models()` on completion.
- **Tier resolution edge cases.** If users complain about auto-rank picking
  the "wrong" model in a tier, switch to a curated priority list per
  (provider, tier).
