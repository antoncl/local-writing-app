# ADR-0084: A cache strategy is an object the provider picks per model; the transport encodes its plan

- Status: **Proposed** — 2026-09-06, authored by Claude, not yet approved by Anton.
- **Issue:** #1064 (the narrowed residual: `realize_cache` + the bidirectional up-seam)
- **Relates to:** ADR-0058 (a provider is a class), ADR-0060 §5/§6 (volatility is a provider-neutral ordering; the preview is cache-aware), ADR-0057 (one lore selection), ADR-0065 (a class registered once; earn a method when two need it), `docs/design/context-caching.md`

> **Verified against `cb1d68d9` (2026-09-06).** Citations name the symbol first; the line is a convenience and is what rots. Provider behaviour is quoted from OpenRouter's prompt-caching guide (`https://openrouter.ai/docs/guides/best-practices/prompt-caching`) as read on the same day.

## Problem

ADR-0060 §5 settled the *policy* half of context caching: the send path emits a volatility-ordered list of `{text, tier}` blocks and never speaks a provider's caching vocabulary (`ChatCall.system_blocks`, `backend/app/services/ai/profiles/base.py:305`; assembly in `chat.py:295–302`). What it left to "each adapter" — the *realisation* of those tiers within a provider's limits — has grown into the shape #1064 describes, and four facts about the code today show why the enum that carries it is the wrong unit.

**1. The only per-model caching knob is a three-value enum.** `ProviderProfile.caching_style(model_id) -> "none" | "auto" | "explicit"` (`base.py:483`; `CachingStyle`, `base.py:51`). It is consumed as a *branch* in one place (`openrouter_system_messages`, `openrouter.py:187`), as a *bool* in another (`caches = caching_style in ("auto", "explicit")`, `preview.py:915`), and as an *equality test* in the UI (`estimate?.caching_style === "explicit"`, `ChatMetaLine.svelte:23`; `InputsDialog.svelte:138`). Three readers, three different projections of one enum.

**2. The realisation is cloned.** Two loops turn tiers into `cache_control` markers with the 4-cap: `anthropic_system_blocks` (`anthropic.py:304`) and the explicit branch of `openrouter_system_messages` (`openrouter.py:187`), both over the shared `cache_control_indices` / `TIER_TTL` (`explicit_cache.py`). Two more collapse the blocks to one string: `OpenAICompatibleProfile._build_messages` (`openai_compatible.py:176`) and the non-explicit branch of `openrouter_system_messages`. Two behaviours, two copies each — a caching change is a four-site edit, the cost ADR-0058 removed from the call path but not from caching.

**3. The enum is too coarse for the routes it already names.** `_CACHING_BY_PREFIX` (`openrouter.py:47`) maps `google` to `explicit`, so a Gemini route receives Anthropic's realisation: up to four markers, each carrying `"ttl": "1h"` or `"5m"`. Per OpenRouter's guide, Gemini honours only the *final* breakpoint, ignores the `ttl` field entirely, and caches for a fixed, non-renewable ~3–5 minutes. The wire is not wrong enough to fail, only wrong enough to mislead: the UI would project a one-hour cache term onto a five-minute cache. OpenAI's newer explicit mode is not a marker style at all but request-level `prompt_cache_options` / `prompt_cache_key`; it has no representable value in the enum. DeepSeek, Grok, Groq and Moonshot are automatic prefix caches with unspecified TTLs — "auto" is right for them, and it is all the enum can say.

**4. The TTL vocabulary has leaked upward — past the profile, into the frontend.** `SLOT_TTL_SECONDS = { system: 3600 }` and `ttlLabel = ttl >= 3600_000 ? "1h" : "5m"` (`chatInputs.ts:15`, `:207`) hard-code Anthropic's answer; `PreviewCacheBlock`'s docstring promises "stable (cached at 1h)" (`models/ai.py:297`). The chat's "CACHE TTL" card therefore shows a one-hour countdown for any provider whose style is `explicit`, whatever that provider actually does. This is the pre-existing leak #1064 names, moved one layer further out than the issue recorded.

Anton's framing of the fix (2026-09-06): *split the provider abstraction in two — one part establishes the connection, one part manages caching — so an OpenRouter assistant can tailor caching to the specific model.* This ADR adopts that split and pins down the seam between the two halves, because the seam is where a naive split blurs: a caching object that emits wire shape is a transport in disguise, and a transport that reads tiers is a strategy in disguise.

## Intent

The app says *how volatile* each block is. A **cache strategy** — one object per caching behaviour, chosen by the provider **per model** — turns that ordering into a **plan**: which blocks get a marker, what each marker says, and how long the provider is expected to keep each block. The **transport** (the provider profile's connection and SDK code) encodes the plan onto its wire shape without interpreting it. The same plan flows *up* to the preview and the chat's meta line, so the writer sees the provider's real projection instead of a hard-coded one.

## Anti-goals (what this must not do)

- **Not** a strategy that sees session state, reorders blocks, or moves content between tiers. Policy — stable-first ordering, the revision-baseline split, the one lore selection — stays in `chat.py` (ADR-0060 §5, ADR-0057). A strategy is a pure function of the ordered blocks it is handed.
- **Not** a strategy that emits wire shape. The Anthropic SDK takes `system=[...]`; the OpenAI-compatible wire takes `messages[0].content=[...]`. A plan is transport-neutral; the transport renders it.
- **Not** a shared layer that reads a plan. `chat.py`, `preview.py`'s block assembly, and the frontend consume the plan's *projection* (cached or not, planned seconds) and never a marker, a ttl token, or a breakpoint count.
- **Not** a user-authorable or config-driven strategy table. Which caching a model does is a provider fact, and a wrong entry silently costs money; the set is closed, one class each (the ADR-0058/0065 idiom).
- **Not** a per-assistant caching knob. The assistant picks a model; the model's provider picks the strategy.
- **Not** OpenAI's request-level explicit mode, a token-count-gated minimum-size check, or per-block cache pricing. Each is named in Scope as out, with the reason.
- **Not** a frontend that knows a TTL. After Slice 3 the only TTL numbers in the frontend arrive in the preview response.

## Decision

### 1 — Two objects, two owners

The provider profile splits along the line Anton drew:

| Object | Owns | Today's members |
| --- | --- | --- |
| **`ProviderProfile`** (the transport; unchanged in role) | connection and identity (`from_settings`, `configured_key`, `key_prefixes`, `list_models`, `health_ping`), the call (`chat`, `chat_stream`), tokens and usage (`count_tokens`, `extract_usage`), and **choosing** a strategy per model | `AnthropicProfile`, `OpenAIProfile`, `OpenRouterProfile`, `OllamaProfile` |
| **`CacheStrategy`** (new ABC, `services/ai/profiles/cache_strategy.py`) | turning ordered `{text, tier}` blocks into a `CachePlan` within one provider's limits — marker budget, marker payload, planned lifetime | `NoCache`, `PrefixCache`, `AnthropicBreakpoints`, (Slice 2) `GeminiBreakpoint` |

`caching_style(model_id)` on the profile is replaced by **`cache_strategy(model_id) -> CacheStrategy`**. The three-value `CachingStyle` literal retires with it (Slice 3; Slice 1 derives it from the strategy so no consumer moves early — see Rollout).

### 2 — The strategy contract: `plan(blocks) -> CachePlan`

```python
class CacheStrategy(ABC):
    kind: str                                   # "none" | "prefix" | "anthropic" | "gemini" — a label for tests/telemetry, not a branch key
    @abstractmethod
    def plan(self, blocks: list[dict]) -> CachePlan: ...

@dataclass(frozen=True)
class PlannedBlock:
    text: str
    tier: str | None                            # the policy's volatility tier, carried through unchanged
    marker: dict | None                         # the exact `cache_control` payload to attach, or None
    ttl_seconds: int | None                     # the strategy's projection of how long this block stays cached; None = unknown/uncached

@dataclass(frozen=True)
class CachePlan:
    mode: Literal["markers", "collapse"]        # markers: keep blocks apart and attach markers; collapse: one joined string
    cached: bool                                # does this provider cache the prefix at all (auto or explicit)
    blocks: list[PlannedBlock]                  # empty-text blocks already dropped
```

Rules:
- **Pure.** `plan` reads the blocks it is given and nothing else — no session, no settings, no token counter. It may drop empty blocks (both encoders do this today) and must not reorder or re-tier.
- **`marker` is a payload, not a wire position.** It is the object both marker-carrying transports attach verbatim (`cache_control` is one primitive shared by the Anthropic SDK and OpenRouter's content blocks). A strategy that must *not* send a `ttl` key (Gemini) simply omits it from the payload; the key's presence is the strategy's call, never the encoder's.
- **`ttl_seconds` is a projection, separate from `marker`.** Gemini plans `ttl_seconds=300` and a marker with no `ttl`; Anthropic plans `3600` and `{"type": "ephemeral", "ttl": "1h"}`. The UI reads the former; the wire carries the latter.
- **`collapse` mode still carries per-block projections.** A `PrefixCache` plan is `mode="collapse", cached=True`, every block `marker=None, ttl_seconds=None` ("cached, no stated term"). The transport joins the texts with the separator it uses today (`"\n\n"`).
- **The system-prompt-only path is the one-block case.** Where a transport today special-cases a bare `system_prompt` (`anthropic_system_with_cache`, `anthropic.py:294`), it instead plans `[{"text": system_prompt, "tier": "stable"}]` — the same wrapping `system_prompt_cache_blocks` (`chat.py:31`) already performs for the send path.

Nothing request-level (an `extra_body` field, a cache key) is in the plan. A strategy that needs one earns the field when it exists — the ADR-0065 rule — and the only known candidate (OpenAI's explicit mode) is out of scope here.

### 3 — The closed set of strategies

| Strategy | Plan | Used by |
| --- | --- | --- |
| `NoCache` | `collapse`, `cached=False`, no markers, no projections | Ollama; any OpenRouter route with no known prefix |
| `PrefixCache` | `collapse`, `cached=True`, no markers, `ttl_seconds=None` | OpenAI native; OpenRouter `openai`, `deepseek`, `x-ai`/`xai`, `groq`, `moonshotai` |
| `AnthropicBreakpoints` | `markers`; a marker on the **last four** eligible tiered blocks (today's `cache_control_indices`), payload `{"type":"ephemeral","ttl": "1h"\|"5m"}` by tier, `ttl_seconds` 3600/300 | Anthropic native; OpenRouter `anthropic`; OpenRouter `alibaba`/`qwen` *as today* (verify item) |
| `GeminiBreakpoint` (Slice 2) | `markers`; **one** marker on the last stable-tier block, payload `{"type":"ephemeral"}` (no `ttl`), `ttl_seconds=300` on the blocks it covers | OpenRouter `google` |

`TIER_TTL`, `MAX_BREAKPOINTS` and `cache_control_indices` (`explicit_cache.py`) move *into* `AnthropicBreakpoints`; the module retires. The 4-cap and the `1h`/`5m` tokens end up in exactly one class, which is where ADR-0060 §5 said they belong.

### 4 — The profile picks the strategy per model

- `AnthropicProfile.cache_strategy` returns `AnthropicBreakpoints` for any model (today's `caching_style`, `anthropic.py:126`, is unconditional for the same reason).
- `OpenAIProfile` returns `PrefixCache`; `OllamaProfile` returns `NoCache`.
- `OpenRouterProfile.cache_strategy(model_id)` looks the route prefix up in a table whose **values are strategy instances** — `_CACHING_BY_PREFIX` (`openrouter.py:47`) with its values changed from enum strings to objects. This is the "tailor caching to the specific model" Anton asked for, and it is where it already lived; the change is what the table holds, not where it is. `caching_style_for_model` (`openrouter.py:177`) — a module-level helper whose docstring justifies itself by a streaming dispatcher ADR-0058 removed — retires with the enum.

Strategies are stateless, so one module-level instance per class suffices; there is no registry to keep because there is nothing to register — the profile names the class it wants.

### 5 — The transport encodes the plan

Each marker-carrying transport keeps one encoder that takes a `CachePlan` and returns its wire shape; the encoder never inspects `tier`:

- `anthropic_system_blocks(plan) -> list[dict] | ""` — `{"type":"text","text":…}` per block plus the block's `marker` when present (the `system=` kwarg, `anthropic.py:190`).
- `openrouter_system_messages(plan) -> list[dict]` — in `markers` mode a single system message whose `content` is the block list with markers; in `collapse` mode the joined string (`_build_messages`, `openrouter.py:77`).
- `OpenAICompatibleProfile._build_messages` uses the plan's collapsed text; with `NoCache`/`PrefixCache` the output is byte-identical to today's join.

A transport asks its own profile for the strategy: `plan = self.cache_strategy(call.model).plan(blocks)`. The `ChatCall` shape is unchanged — the seam between app and provider stays "ordered tiered blocks", exactly as ADR-0060 §5 fixed it.

### 6 — The plan is the up-seam

`PreviewEstimate` (`preview.py:788`) and the preview response model (`models/ai.py:363–380`) replace `caching_style` with the plan's projection: `cached: bool` and, per `PreviewCacheBlock`, `cached: bool` + `ttl_seconds: int | None`. The preview obtains it the same way the send path does — `profile.cache_strategy(model).plan(blocks)` over the blocks `_preview_send_blocks` already builds — so the preview and the wire cannot disagree about which blocks are marked.

On the frontend, `SLOT_TTL_SECONDS` and the `"1h"/"5m"` labels go; `ttlChipsFor` takes the block's `ttl_seconds` from the estimate. `ChatMetaLine`'s "CACHE TTL" card shows when the plan has a block with a known term; a `PrefixCache` plan renders "cached · no stated term"; `NoCache` renders nothing, as `none` does today. The `cache_write_times` stamping (`_touched_cache_write_times`, `chats.py:469`) is untouched — it records *when* the prefix was last written; the plan supplies *how long* it lives.

`estimate_send_cost(…, caches: bool)` (`tokens.py:172`) takes `plan.cached`. Its stable/other split is unchanged in this ADR (see Scope: per-block pricing is out).

### 7 — What this settles from #1064's open list

1. *Where does the planned TTL surface?* In the two surfaces that already show caching — the chat meta line and the inputs-dialog estimate strip — by enriching the response they already read. No new live channel: the plan rides the existing preview call.
2. *Do content tiers differ by provider?* No. Tiers are the content's lifecycle (settled vs new-this-turn); every strategy consumes the same two. The boundary stays where ADR-0060 §5 put it.
3. *OpenRouter is N providers behind one.* `cache_strategy(model_id)` receives the full route id, as `caching_style` does today.

## User journey (the definition of done)

Anton hires an assistant on `deepseek/deepseek-chat` through OpenRouter and opens a brainstorm chat. The meta line reads *cached · no stated term* — the strategy is `PrefixCache`, the wire is one collapsed system message, cached tokens come back in usage as they do today. He switches the assistant to `google/gemini-2.5-pro`: the outgoing request carries **one** `cache_control` marker at the end of the stable prefix with no `ttl` key, and the meta line counts down from about five minutes, not an hour. He switches to `anthropic/claude-sonnet-4-6` on the same OpenRouter key: up to four markers with `1h`/`5m`, a one-hour countdown — byte-for-byte what ships today. Nothing in the chat, the template, or the assistant asked about caching; the provider answered.

## Scope

**In:**
- `CacheStrategy` / `CachePlan` / `PlannedBlock` and the three strategies that reproduce today's wire (`NoCache`, `PrefixCache`, `AnthropicBreakpoints`).
- `ProviderProfile.cache_strategy(model_id)` on all four profiles; OpenRouter's prefix table holds strategies.
- Both encoders consume a plan; `explicit_cache.py` and `caching_style_for_model` retire.
- `GeminiBreakpoint` — the first behaviour change, its own slice.
- The preview and the frontend read the plan's projection; `caching_style` and the frontend's TTL constants retire.
- `context-caching.md` §3a and ADR-0060 §5's adapter table gain a pointer to this ADR (the §3a "not enforced in code" note is already stale — the cap is enforced in `cache_control_indices`).

**Out, and why:**
- **OpenAI's request-level explicit mode (`prompt_cache_options` / `prompt_cache_key`).** Nothing we run uses it; our OpenAI profile is `PrefixCache`. Building a plan field for it now is reserving a mechanism for a surface that does not exist. Recorded as out; its shape is deliberately *not* sketched here.
- **Minimum-cacheable-size gating.** Anthropic and Gemini ignore a marker below their minimum (1 024–4 096 tokens) at no cost; enforcing it would give the strategy a token counter and a model-dependent table for a no-op. Not done.
- **Per-block cache pricing in the estimate.** `estimate_send_cost` prices the stable tier as cached and everything else at full rate; a `volatile` block with a 5-minute marker is in fact written to cache on Anthropic. A truthful estimate is the plan's natural next consumer, but it is a costing change with its own acceptance and is not part of this decision.
- **Cache-read/write multipliers, `session_id` stickiness (`openrouter_extra_body`, `openrouter.py:237`), the `cache_write_times` slot model.** Unchanged.
- **A caching knob on the assistant, or a user-authored strategy table.** Anti-goals above.

## Alternatives considered

- **Enrich the enum** (add `"gemini"`, `"anthropic"`, …). Rejected: the enum is already read three ways (branch, bool, equality) by three consumers; a fourth value means auditing all three, and OpenAI's request-level mode still has no place in a marker-style enum. The enum was a label standing in for behaviour; the behaviour wants an object.
- **`realize_cache(blocks)` directly on `ProviderProfile`** (the issue's original sketch). Rejected: `OpenRouterProfile` would still need an internal per-model dispatch — a strategy object under another name, private to one profile — and the Anthropic realisation would exist twice (native profile, `anthropic/` route), which is the duplication being removed.
- **The strategy emits the wire shape.** Rejected: it binds a caching behaviour to one SDK's envelope. `AnthropicBreakpoints` serves two transports today (the Anthropic SDK's `system=[…]` and OpenRouter's `messages[0].content=[…]`); one plan, two encoders is the shape that makes that a non-event.
- **Make policy provider-aware** (tiers chosen per provider). Rejected: no provider has shown a need for a third tier or a different split; §7 Q2. Moving the boundary up would put session state inside the provider layer — the thing ADR-0060 §5 was written to prevent.
- **Compute TTLs in the frontend from the provider name.** Rejected: it is the leak in its purest form, and it is what `chatInputs.ts` does now.
- **A user-editable strategy table** ("could a user author this?"). Rejected: caching is a provider fact, not authoring, and a wrong entry is a silent cost, not a visible mistake.

## Consequences

- Adding a provider whose caching matches an existing behaviour is one line in `cache_strategy()`; adding a new caching behaviour is one class plus a wire test. Neither touches `chat.py`, the preview assembler, or the frontend.
- The 4-breakpoint cap and Anthropic's ttl tokens exist in one class. The frontend holds no TTL number.
- Gemini routes get a correct wire and a correct countdown; the app stops sending markers Gemini ignores. Whether Gemini's implicit cache renews on a hit (Anthropic's does) affects how the countdown should restart; the verify list carries it.
- `CachingStyle` disappears from the API surface (`aiTypes.ts:188`, `:399`; `models/ai.py:380`). Frontend tests that assert on `caching_style` move to the plan fields.
- `context-caching.md` §3a becomes a pointer to the strategy table rather than a second, hand-maintained copy of it.
- A strategy is a pure function, so its tests are tables: blocks in, plan out. The wire tests (`test_provider_system_blocks_reach_wire.py`, `test_ai_anthropic_caching.py`, `test_ai_openrouter_caching.py`) keep asserting the encoder output and become the byte-identity check for Slice 1.

## Rollout (slices)

- **Slice 1 — the split, byte-identical.** `cache_strategy.py` with the ABC, `CachePlan`, and `NoCache`/`PrefixCache`/`AnthropicBreakpoints`; `cache_strategy(model_id)` on all four profiles; both encoders take a plan; `explicit_cache.py` folds into `AnthropicBreakpoints`. `caching_style()` stays for this slice as a concrete base method returning the strategy's `kind` mapped onto the old three values, so `preview.py` and the frontend do not move. Gemini routes keep `AnthropicBreakpoints` for this slice, named in the table as the known carry-over.
  *Not:* any wire change; any preview or frontend change. *Done when:* the existing wire tests pass unmodified, and a mutation that drops a marker or a `ttl` from `AnthropicBreakpoints` is caught by them.
- **Slice 2 — `GeminiBreakpoint`.** The class, the `google` prefix repointed, a wire test asserting exactly one marker on the last stable block and no `ttl` key.
  *Not:* a token-size gate. *Done when:* the Gemini leg of the user journey holds on the wire (captured request).
- **Slice 3 — the up-seam.** Preview and response models carry `cached` + per-block `ttl_seconds`; `caching_style` and `CachingStyle` retire; `SLOT_TTL_SECONDS` and the `1h`/`5m` labels go; `ChatMetaLine` and `InputsDialog` read the plan; `estimate_send_cost` takes `plan.cached`.
  *Not:* per-block pricing; a new live channel. *Done when:* the meta line shows ~5 min on a Gemini route, "no stated term" on DeepSeek, 1h on Anthropic, and a grep for TTL literals (`3600`, `"1h"`, `"5m"`) in `frontend/src` finds none outside tests.

#1064 sits in the Post-1.0 milestone. Slice 1 is a duplication-removing refactor with no wire change and fits the debt-free 1.0 gate if Anton wants it there; Slices 2–3 change behaviour and can follow either side of 1.0. The ADR does not decide the milestone.

## Acceptance

1. `AnthropicBreakpoints.plan` over the send path's blocks marks the last four tiered blocks with `1h`/`5m` payloads; `anthropic_system_blocks(plan)` and `openrouter_system_messages(plan)` produce today's wire byte-for-byte. *(Slice 1)*
2. `PrefixCache.plan` collapses; the OpenRouter `deepseek/…` and native OpenAI system messages are unchanged strings. *(Slice 1)*
3. Removing a `cache_control` from the Anthropic encoder, or the `ttl` from a marker, fails an existing wire test. *(Slice 1)*
4. A `google/gemini-2.5-pro` request carries exactly one `cache_control` marker, on the last stable block, with no `ttl` key. *(Slice 2)*
5. The preview response for an OpenRouter Gemini assistant reports `ttl_seconds=300` on the stable blocks; for DeepSeek `cached=True` with no `ttl_seconds`; for Anthropic `3600`/`300`. The chat meta line renders each accordingly. *(Slice 3)*
6. No TTL literal remains in `frontend/src` outside tests. *(Slice 3)*

**Not:** no template, assistant, or chat gains a caching control; `chat.py`'s block assembly is not edited; the Anthropic wire does not change in any slice.

## To verify / build at implementation

- **`alibaba` / `qwen` routes.** Today mapped `explicit` and sent Anthropic-style markers with `ttl`; OpenRouter's guide (as read) does not list them. Confirm whether they honour `cache_control`, and with what semantics, before deciding whether they stay on `AnthropicBreakpoints`, move to `GeminiBreakpoint`, or fall to `PrefixCache`.
- **Gemini renewal.** OpenRouter states Gemini's implicit cache is non-renewable (~3–5 min). If a cache hit does not extend the term, the countdown should restart on *write*, not on every send; check how `cache_write_slots` is stamped per turn before wiring Slice 3's countdown.
- **Anthropic on OpenRouter — automatic mode.** OpenRouter offers automatic caching for Anthropic routes too. `AnthropicBreakpoints` (explicit) is kept because it is what ships; note whether automatic would change cost.
- **DeepSeek usage.** Confirm cached tokens arrive as `prompt_tokens_details.cached_tokens` on the OpenRouter path (the field `extract_usage`, `openrouter.py:169`, already reads).
- **The preview's blocks.** `_preview_send_blocks` builds a `PreviewCacheBlock` list with tokens; the plan needs `{text, tier}`. Confirm the preview can plan over the same list it displays without a second assembly.
