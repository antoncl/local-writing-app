# ADR-0083: Model prices come from OpenRouter's public feed; baked-in is the offline seed

- Status: **Accepted** — 2026-09-05, Anton Lauridsen, PR #1825.
- **Issue:** #1823 (Slice 1, backend), #1824 (Slice 2, UI)
- **Relates to:** ADR-0073 (live catalogue merge), ADR-0058 (provider call path off the ABC), `docs/ai-model-selection.md`

> **Verified against `234a91f9` (2026-09-05).** Citations name the symbol first; the line is a convenience and is what rots.

## Problem

Anthropic and OpenAI do not publish per-token prices on their model-list endpoints, so for those native routes `_baked_in.yaml` is the *only* source of cost data (`baked_in_catalogue`, `backend/app/services/ai/profiles/_loader.py:118`; the merge carries price only on baked rows — `merge_live_catalogue`, `_loader.py:74`; a live-only model becomes a `_synth_live_descriptor`, `_loader.py:56`, with every price field `None`). That hand-audited table drifts, and both drift modes are live in the shipped app:

- **Missing.** `claude-opus-5` and `claude-sonnet-5` have no row. A real dogfooding chat (`the-collective/chats/chat_00b25526aa.md`) ran every turn on `claude-opus-5` with full `usage` recorded but `cost_usd: null` throughout: `translate_usage_to_cost` (`backend/app/services/ai/usage.py:40`) resolves no descriptor → `cost = None`; `_record_chat_cost_delta` (`backend/app/services/project/chats.py:420`) then skips the ledger write on a `None`/≤0 delta, so `cost_usd_total` never leaves 0. The user sees "cost 0" after a long session.
- **Stale.** `claude-opus-4-7` / `claude-opus-4-8` are baked at `15 / 75` per-Mtok but the real price is `5 / 25` (Opus dropped at 4.5); Fable is baked at `15 / 75` vs. the real `10 / 50`. Even *priced* native chats have been over-costed ~1.5–3×. Last hand-audit: 2026-06-20.

Meanwhile OpenRouter publishes authoritative, current prices for the *same underlying models* on `/api/v1/models`, an endpoint that is **public — no API key required** (`OpenRouterProfile.list_models`, `backend/app/services/ai/profiles/openrouter.py:107`, comment at :112). The app already turns that feed's `pricing.prompt`/`pricing.completion` into descriptor cost fields for the OpenRouter route (`_row_to_descriptor` / `_per_mtok`, `openrouter.py:252`, `:292`). The price we need is one HTTP GET away — we simply never consult it for native routes.

The root cause is architectural, not a missed row: **a hand-maintained price table is the wrong source of truth when an authoritative live feed exists.** Adding the three missing rows fixes today's symptom and guarantees the next model re-introduces it.

## Decision

Source native Anthropic/OpenAI prices from a cached **price oracle** built off OpenRouter's public feed, with a per-model **user override** on top for the cases the feed can't cover or gets wrong. `_baked_in.yaml` is demoted from "source of truth" to an offline seed. A model that resolves to no price at all is surfaced as an explicit warning, never a fabricated `0`.

### 1 — Price resolution: override > oracle > baked-in > warn

For any (provider, model), the cost fields are resolved highest-wins:

1. **User override** — a machine-level, per-model price the author set by hand. Wins over everything (§4).
2. **OpenRouter oracle** — the live price from the public feed (§2).
3. **Baked-in** — the offline seed in `_baked_in.yaml`.
4. **None** — no source has a price. Cost resolves to `None` ("unknown"), and the UI shows a warning with a path to set an override (§5). Never a synthesized `0` — a confident zero stays reserved for a genuinely free model (#697).

### 2 — A price oracle over OpenRouter's public feed

A new module (`services/ai/profiles/price_oracle.py`) fetches OpenRouter's `/api/v1/models` **key-less** and builds a process-level index `native-id → (cost_in, cost_out)` from the `anthropic/*` and `openai/*` rows. The index overlays the cost fields of native descriptors at the profile's `list_models` boundary, so a corrected price flows through the one method every consumer already calls — picker (`routers/ai.py:200`), send-preview (`preview.py:895`), and post-call costing (`descriptor_for`, `tokens.py:64`) — with no separate cost-path plumbing.

**Price-only.** The overlay touches `cost_in_per_mtok` / `cost_out_per_mtok` and nothing else. Tier, capabilities, context window, caching style, `cache_read_multiplier`, and `max_output_tokens` stay exactly as the native profile / baked row set them — OpenRouter's *heuristic* tiering (`_tier_from_cost_and_id`, `openrouter.py:314`) never leaks onto a native model.

### 3 — Refresh is event-driven, not a clock

The oracle index is cached at process level with **no TTL**. It is (re)built on:
- **Cold start** — the first `list_models` that needs it warms the index (lazy; a failed fetch leaves it cold so the next call retries).
- **Assistant add / model change** — the moment a new model id can enter play (Slice 2).
- **A manual "update prices" button** — a machine-global refresh the author triggers (Slice 2).

No background timer: refreshes are deterministic and author-driven, in keeping with the local-first "no surprises" stance. Between events the cached prices are served as-is; the button is the escape hatch when the author knows a price changed.

### 4 — User price override, machine-level, replace-semantics

A `price_overrides` map lives on `MachineSettings` (beside `default_models`, `machine_settings.py:104`) — prices are machine-scoped, not per-project, so one override applies everywhere. An override **replaces** any lower-precedence price: it both *fills* a price the oracle and baked seed lack (Mythos, a local Ollama model, any model OpenRouter doesn't list) and *corrects* one the author distrusts. This is the authorable replacement for hand-editing `_baked_in.yaml` — the "could a user author this?" gate, satisfied through the settings UI rather than a dev-only file edit.

### 5 — No price is a visible warning

When resolution reaches step 4 (no override, no oracle hit, no baked row), the model has no price. Rather than silently rendering "—", the UI warns where the model is chosen (picker / assistant editor) and where cost is shown ("price unknown for `<model>` — set price"), linking into the override editor. Making the gap visible and one click from fixable is the point.

### 6 — Fail-soft, never worse than today

Every failure mode falls through to the next source: a fetch error, timeout, malformed feed, or an id the oracle doesn't carry all fall to baked-in, then to the warning. Offline operation is unchanged — the oracle fetch fails fast and the baked seed answers. A cost is `None` only when *all* sources are silent, exactly as today.

## Scope

**In:**
- A cached, key-less price oracle over OpenRouter's public feed, overlaying native descriptor cost fields at `list_models` (cost-fields only).
- Native→OpenRouter id normalization with a unit corpus (§ below).
- Machine-level `price_overrides` with replace-semantics and the override > oracle > baked precedence.
- A no-price warning surface and the override editor.
- Event-driven refresh (cold start + assistant add/change + manual button).
- Demoting `_baked_in.yaml` to offline seed; updating its header and the ADR-0073 note.

**Out, and why:**
- **Tier / capability / context sourcing from OpenRouter** — the oracle is price-only; native profiles already tier correctly and OpenRouter's tiers are heuristic.
- **Routing native calls through OpenRouter** — this is pricing *metadata*; the call still goes native.
- **Back-filling historical chats** — cost is folded from ledger rows, not recomputed from stored usage (`read_chat_session`, `chats.py:204`), so past `null`-cost turns stay null. Forward-only. A recompute-from-usage migration would be its own ADR.
- **A TTL / background refresh** — explicitly rejected in favour of event-driven refresh (§3).
- **cache-read / cache-write price sourcing from OpenRouter** — the cache multiplier stays baked (`0.1` for the Anthropic family); the oracle supplies only base in/out.

## Native → OpenRouter id normalization

The oracle index is keyed by the OpenRouter id with its `provider/` prefix removed (`anthropic/claude-opus-4.8` → `claude-opus-4.8`). A native id is normalized to that key before lookup: strip any dated snapshot suffix (`-YYYYMMDD` / `-YYYY-MM-DD`), then collapse a version dash *between two digits* to a dot. This is a pure function with a unit corpus:

- `claude-opus-4-8` → `claude-opus-4.8`
- `claude-fable-5-1` → `claude-fable-5.1`
- `claude-opus-5` → `claude-opus-5` (already the key)
- `claude-haiku-4-5-20251001` → `claude-haiku-4.5` (date stripped, then dash→dot)
- `o3-mini` → `o3-mini` (dash not between digits — unchanged)
- `gpt-4o` / `gpt-4o-2024-11-20` → `gpt-4o`

It is the one real correctness surface in this change and is tested in isolation. (A local date-stripper is used rather than reusing `_normalize_model_id`, `call_resolver.py:36`, to avoid coupling costing to the max-output-clamp path.)

## Alternatives considered

- **Keep hand-updating `_baked_in.yaml`** (the quick fix: add opus-5/sonnet-5, correct 4.7/4.8/Fable). Rejected: it is the status quo that just failed. It recurs on every model launch and price change, and the audit cadence guarantees windows where native cost is silently 0 or multiples off.
- **Backfill from the oracle only when baked-in is *missing*, keep baked authoritative when present.** Rejected: leaves the stale 4.7/4.8/Fable rows wrong and creates two competing price sources. Precedence must be unambiguous (§1).
- **Scrape the providers' own pricing pages.** Rejected: no stable machine API; brittle HTML; more sources to maintain than the one live feed that already normalizes them.
- **Gate the oracle on the user having configured OpenRouter.** Rejected: the feed is public and key-less (`openrouter.py:112`); gating it would deny correct prices to the majority native-only user for no benefit.
- **A TTL-refreshed cache.** Rejected in review: a background clock is a surprise in a local-first app; author-driven events (assistant add, a button) are deterministic and sufficient (§3).
- **Route everything through OpenRouter to inherit its pricing.** Rejected: changes the actual call path, caching, and provider trust for a metadata problem; far larger blast radius than the bug warrants.

## Consequences

- `_baked_in.yaml`'s role narrows to offline seed. Its "check provider pricing pages / Last hand-audit" header is rewritten to say prices are normally live and the file is the fallback. The staleness maintenance burden largely disappears; a genuinely unlisted model is now the author's override, not a dev edit.
- A first shared catalogue cache appears (there is none today — the `profile_cache.py` referenced at `base.py:479` does not exist). Native cost lookups stop re-fetching per call once the oracle is warm.
- New soft dependency on OpenRouter reachability for *current* prices; fully degraded-safe to baked-in, then to the warning. Documented as an estimate, consistent with how the app already frames cost.
- Costs become live-data-dependent, so tests inject a fixed feed; no test asserts a cost against the network.

## Rollout (slices)

- **Slice 1 — #1823 (backend, this ADR's landing PR).** The oracle + process cache + id normalization + the cost-field overlay at `list_models` for Anthropic/OpenAI + cold-start warm + baked-in header demotion. After this, a `claude-opus-5` chat prices correctly (oracle: 5/25) with no UI work. Precedence at this slice is oracle > baked.
- **Slice 2 — #1824 (UI + control).** The `price_overrides` field + editor, the no-price warning, the manual "update prices" button, and the assistant-add/change refresh trigger. This adds the top (override) and bottom (warn) of the §1 stack.

## Acceptance

1. In a project whose assistant runs on `claude-opus-5`, send a chat turn. The turn records non-null `cost_usd`, a ledger row is written, and the session total is non-zero — priced at 5/25 per-Mtok from the oracle, with no baked `claude-opus-5` row present. *(Slice 1)*
2. Open the model picker with no OpenRouter key configured. `claude-opus-4-8` shows `5 / 25`, not the stale baked `15 / 75`. *(Slice 1)*
3. Point the oracle at an unreachable host. Cost still computes for any baked model from the seed; `claude-opus-5` cost is `None` (unknown), never a fabricated 0; the cost path does not hang or error. *(Slice 1)*
4. The id-normalization corpus passes (the six cases above). *(Slice 1)*
5. Set a `price_overrides` entry for `claude-mythos-5`; a chat on it prices from the override. Clear it; the picker and cost display warn "price unknown". *(Slice 2)*

**Not:** historical `the-collective` turns do not retroactively gain a cost; the picker does not adopt OpenRouter's tier labels for native models; native calls are not routed through OpenRouter.

## To verify / build at implementation

- Where the cold-start warm runs so no cost call blocks on a slow fetch: the streaming path pre-fetches `descriptor_for` before streaming (`routers/ai.py:534`), so the await lands there, not mid-stream.
- Whether OpenRouter's feed carries `pricing.input_cache_read` / `input_cache_write` for Anthropic routes and if adopting them later beats the baked `cache_read_multiplier` (out of scope now). An oracle-only model (no baked row) currently keeps `cache_read_multiplier=None` → priced at full rate on the cached slice; the effect is negligible (hundreds of cached tokens) but noted.
- The construction seam for the key-less oracle fetch (`OpenRouterProfile("")` directly vs. `capability_profile_for`, `registry.py:70`).
- Mythos 5: OpenRouter does not list it. It is covered by a user override (§4) rather than a baked pin; decide separately whether it stays in the sampling-family list until it is a real, priced model.

## Amendment 1 (2026-09-05): the override is a per-assistant *fill* field, not a machine-level *replace* map

Slice 2 revised §1 (precedence) and §4 (override) after two findings in planning. **This amendment supersedes §4's machine-level `price_overrides` map and the §1 "override wins" precedence; §2 (oracle), §3 (refresh), §5 (warning), and §6 (fail-soft) stand.**

### Why the original §4 didn't survive contact

- **No per-model UI, and no overridable-computed field.** The override has to be authored somewhere, and the assistant is the only Node that carries a model selection. But modelling the price as a *computed, overridable* field fights the grain: this codebase enforces that computed fields are derived and never stored (validation rejects a stored value for a computed field, `strip_computed_fields` drops them on save, the metadata rail renders them read-only). Making one writable — even to the machine layer — is a new exception at four pipeline stages, the opposite of reuse.
- **"Replace" semantics go stale.** An override that *wins over* the oracle silently shadows the real price forever once OpenRouter announces the model. Keeping it safe would require a visible, clearable override-over-live-base mechanism — real machinery to build. Flipping the precedence removes the problem instead of managing it.

### The decision

The override is **two optional stored `number` fields on the assistant node** — `ai_price_in_usd_per_mtok` / `ai_price_out_usd_per_mtok`, USD per 1M tokens (matching how providers publish pricing; no EUR conversion on the field — display currency is a rendering concern elsewhere). Because they are ordinary stored fields they **auto-render in the metadata rail** — no bespoke editor, no computed-field surgery.

- **Fill semantics — precedence becomes `oracle → baked → manual → warn`.** The manual price prices a call only when neither the oracle nor the baked seed does (an unlisted or local model). The oracle always wins when present, so a manual value **auto-heals**: the moment OpenRouter lists the model, the oracle takes over. **Both sides are required to apply** — a half-set price (input only, or output only) is treated as unknown, not a confident $0 on the blank side, preserving `compute_cost`'s None-vs-0.0 contract. Implemented at the cost site by `apply_manual_fill` (`services/ai/tokens.py`), threaded from the resolved assistant via `ResolvedCall.manual_price_{in,out}_usd_per_mtok` (`call_resolver.py`) into `translate_usage_to_cost` at all four cost sites (the generate + chat non-stream turns and both streaming descriptor pre-fetches).
- **Scope is per-assistant.** Two assistants on the same unlisted model set the price independently. Acceptable: the real case is one niche/local model on an assistant being configured, and there is no per-model surface to key a shared value to.
- **Reset (Slice 2b).** Because a filled value goes dormant once the oracle lists the model, an oracle refresh sweeps the open project's assistants and clears the manual price fields of any whose model the oracle now prices — so a value entered while a model was unlisted doesn't linger. Fires on the refresh event (manual "update prices" button, assistant add/model-change), not on every read.

### Slices restated

- **Slice 2a — this PR:** the assistant price fields + the `apply_manual_fill` cost path + this amendment. Fill precedence `oracle → baked → manual`.
- **Slice 2b — #1824:** the no-price warning, the manual "update prices" button + refresh endpoint, and the reset sweep + assistant add/change trigger.

The Slice-1 machine-level store is not built; §4's `MachineSettings.price_overrides` is withdrawn in favour of the assistant fields above.
