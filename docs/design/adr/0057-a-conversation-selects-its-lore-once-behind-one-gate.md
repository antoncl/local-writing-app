# ADR-0057: A conversation's lore is one gated function whose result is dedupped by id

- Status: **Accepted** — 2026-08-15 (approved by Anton; authored by Claude, PR #1017). Origin: dogfooding
  — a create-character brainstorm ignored two `lore:note`s the writer had marked **Context policy =
  Always**. Tracing the drop surfaced not a missing feature but a *second*, ungated lore-selection
  channel on the send path that the render-time channel never reconciles with.
- Follows: ADR-0006 (lore context is resolver-mediated at the `_format_lore_block` formatter), ADR-0026
  (type-aware Jinja helpers — `relevant_lore()` is one), ADR-0051 (a node owns its conversations —
  chats are first-class subject-referencing nodes), ADR-0055 (a conversation reads as-of a scene; the
  send-time envelope assembly).
- Governed by: the layered context envelope's **cache-coherence tradeoff** — a stable (long-TTL) tier
  and a volatile (short-TTL) tier; an object placed in the stable tier is stale-until-refresh
  (`strategy_ai_integration`; the `CacheBreakExtension` in `services/ai/templates.py`).
- Vehicle: #1016.
- Citations pinned to `master@1046ed3`.

## Context

Lore reaches an AI chat through **two independent channels that sit on opposite sides of the HTTP
boundary and never reconcile**:

1. **Render-time.** Jinja rendering is a backend service. When the client wants a prompt rendered it
   calls a render/preview endpoint; the backend runs the template — including the `relevant_lore()`
   helper (`_relevant_lore`, `services/ai/helpers.py`; registered as the Jinja global in
   `register_helpers`) — against the project's lore, and returns a **string**. The client holds that
   string and posts it back on send. The backend then treats it as **opaque** — it cannot see which
   lore ids are baked inside. Only prompts that *call* the helper participate; today only the built-in
   `roleplay.md` does.

2. **Send-time.** `expand_context` (`services/ai/context_expander.py`), called from
   `_prepare_chat_send_payload` (`routers/ai.py`), runs on **every** send. It scans the last user
   message, does an auto-only alias match (`_alias_match`, `helpers.py`) plus a one-hop textual
   expansion (`_textual_one_hop`), appends detections to the chat's journal, and renders them as a
   separate lore block — **regardless of whether the prompt used `relevant_lore()` at all.**

`context_policy` is a per-entry `select` — `["always", "auto", "manual_only", "never"]`, default
`auto` (`default_schema.py`; `VALID_CONTEXT_POLICIES` in `helpers.py`). Its intended semantics:
`auto` = include when the text mentions it; `always` = include unconditionally; `never` = excluded
everywhere; `manual_only` = only via the explicit picker. Crucially, **`always` is not an
alias-match**: it is a *wholesale union* — `_always_included_lore_ids` grabs every always-policy entry
and adds it independent of any mention — and today that union lives **only inside `_relevant_lore`**
(the render channel).

Three failures fall out of the split:

- **`always` is silently dropped for most chats.** The send channel does auto-matching only; it never
  performs the wholesale `always` union. A brainstorm/create chat (`revise-entry.md`, which never calls
  `relevant_lore()`) therefore sees no `always` entries — the dogfooding symptom. The writer marked two
  notes Always precisely so they would *always* be present; the app dropped them.
- **A deliberately lore-free prompt is impossible.** Because `expand_context` runs unconditionally, a
  prompt that omits `relevant_lore()` — an author's deliberate "this prompt uses no lore" — still gets
  auto-matched lore injected by the backend. The author's choice is overridden.
- **The same node can be gathered twice, unreconciled.** For roleplay, an entry can land in *both* the
  rendered system prompt (channel 1) and the send-time journal block (channel 2), and because the
  system prompt is opaque the backend cannot subtract one from the other.

What is **not** broken: per-entry `context_policy` is honoured on the send path. `_alias_match`'s
`!= "auto"` skip applies transitively — the depth-1 pass is another `_alias_match` over the matched
entries' bodies — so `never` and `manual_only` are excluded there, in fact more strictly than
`_relevant_lore`'s own chokepoint (`_never_lore_ids`), which filters `never` only. The defect is that
the second selector is **ungated and `always`-blind**, not that it disobeys policy.

## Intent

**Lore enters a chat through one function — `relevant_lore()` — whose result is a single set,
deduplicated by id, and whether it runs at all is the prompt's choice.**

- **One function, one dedupped set.** `relevant_lore()` is the sole lore selector. Its result is the
  union of every route by which a node can be in context — explicitly picked (`context_items`), auto
  text-matched, or wholesale-included by `always` — **minus** `never`/`manual_only`, **keyed by id so a
  node reached by several routes at once appears once.** A set has no duplicate members; that is the
  only dedup this design contains, and it is correctness, not reconciliation.
- **One gate.** Whether a prompt sees lore is the author's choice, expressed by *using* the function.
  If `relevant_lore()` does not run, the set is never built and nothing injects lore. If it runs, the
  send-time accumulation feeds it as an input, not as a rival second selector.

## Anti-goals (what this must not do)

- **No two independent selectors reconciled after the fact.** The failure this ADR removes is *two*
  selections — render-time and send-time — that the backend must reconcile across an opaque string it
  cannot read. The fix is to have **one** selector. Deduplicating that one selector's result by id is
  the opposite of the problem, not an instance of it: it is how a set is built.
- **No static text-scan for the gate.** Deciding lore-intent by grepping a template for `relevant_lore(`
  is the reachability problem: the helper can sit behind `{% if … %}`, inside an `{% include %}`d
  snippet, three conditionals deep. Intent is read from *execution*, never from the source text.
- **No new user-facing lore knob.** The gate is not a checkbox the writer toggles; calling
  `relevant_lore()` *is* the declaration of intent, and the stored signal is populated by observing that
  call. (The signal is stored — the "explicit" half — but never hand-set.)
- **No change to per-entry `context_policy` semantics.** `auto`/`always`/`never`/`manual_only` keep their
  meanings; this ADR changes *where and how many times* they are interpreted, not what they mean. In
  particular `always` stays a wholesale union and is **not** turned into a match — that would silently
  demote it to a fancy `auto`.
- **The send path does not select in parallel.** Its jobs stay: call the provider, enforce AI policy
  (fails-closed), persist chat state, tier the envelope for cache coherence. Its per-turn accumulation
  (`expand_context`) becomes an *input* to the one selector, gated on the same signal — never a second
  block assembled independently of it.
- **No re-agonizing the stable-tier tradeoff.** The gate signal is stable-tier state and inherits the
  staleness-until-refresh property already accepted for the 1-hour cache (§6). It is not a new caveat.
- **The two adjacent bugs are named, not fixed here** (§Deferred): `_relevant_lore`'s structural
  chokepoint leaks `manual_only`; the manual picker enforces no policy.

## User journey

**A — the world context that was set up to always be present.** The writer authors two `lore:note`s —
"Feral Line: Urban Bestiary universe" and "Premise" — and sets each to **Context policy = Always**,
exactly so every conversation carries them. They open a character and start an AI **create-character**
brainstorm. The create prompt uses lore (it calls `relevant_lore()`), so the set is built; its
**wholesale `always` union** pulls both notes in, mentioned or not. The model brainstorms the
protagonist already knowing the world and the premise. *(Today: both notes are dropped, because the
create prompt's channel never performs the `always` union.)*

**B — a node included two ways at once.** The writer has an Always note ("Premise") and *also* pins it
explicitly in the context picker for this chat. `relevant_lore()` gathers it via the union **and** sees
it among the explicit `context_items`; keyed by id, it lands in the result **once**. *(No double
paragraph, because the one function dedupes its own output.)*

**C — the prompt that must stay clean.** The writer authors a mechanical prompt — a pure style pass —
that deliberately does **not** call `relevant_lore()`. The gate is off. No lore is injected, by the
template or the backend. The pass sees only what the author put in front of it. *(Today: impossible —
`expand_context` auto-injects lore into it regardless.)*

## Decision

### 1. `relevant_lore()` is the one selector; its result is dedupped by id

There is a single lore selection, and it is `relevant_lore()`. Its result is a set of lore ids, keyed
by id, so a node reachable by more than one route contributes one member. The send path *drives and
persists* the inputs and formats the result through the existing `_format_lore_block` (ADR-0006), but
it does **not** run a second matcher whose output is unrelated to what the prompt asked for. The code
already leans this way: `_relevant_lore` in chat-session mode **reads the journal that `expand_context`
populated** rather than re-deriving (`helpers.py`) — so the send-time accumulation is already an *input*
to the helper, not a peer. This ADR makes that the whole story: **`relevant_lore()` gathers, dedupes,
and renders; `expand_context` only feeds its journal input.**

### 2. The gate is the runtime execution of `relevant_lore()`

A chat carries a persisted **`lore_enabled`** signal, set as a **side effect of `relevant_lore()`
executing** during the chat's render: the helper records its own invocation on the render context, and
the chat-creation render captures that into `lore_enabled` (chat-session state, not a user-facing
metadata field — exact storage slot is implementation, per ADR-0005's lesson). This is the mixture of
*derive* and *explicit*: an explicit stored flag whose value is derived from actual execution, so it
can never drift from the template — it *is* the template running — and it catches the cases a static
scan misses (the fired conditional branch, the snippet reached through `{% include %}`).

- **Gate off** (`relevant_lore()` never executed) → the set is never built; nothing injects lore.
- **Gate on** → the set is built (§3), and the send-time accumulation runs to feed it (§5).

### 3. The set is `{explicit ∪ auto ∪ always} − {never, manual_only}`, keyed by id

When the gate is on, the one selection unions every route a node can be in context by, keyed on id:

- **explicit** — the chat's `context_items` picks.
- **`auto`** — alias text-matches (`_alias_match`), plus the existing one-hop textual expansion
  (`_textual_one_hop`), itself auto-gated transitively.
- **`always`** — the **wholesale union** (`_always_included_lore_ids`), independent of any mention or of
  depth-1. This is the substantive fix: the union is now part of the one selection, so it fires for
  *every* lore-enabled chat, not only those whose template happened to call the helper.

`never`/`manual_only` are then excluded (the `!= "auto"` gate already does this on the auto path). Because
the result is **keyed by id**, a node reached by several of these routes at once — the Always note the
writer also pinned in the picker (Journey B), or an entry already carried in a prior turn's journal —
appears exactly **once**. Realized against what is already accounted for: the backend knows every id in
play (`context_items` and the prior journal are the `in_scope` set `expand_context` already subtracts),
so the union minus `in_scope` yields each node once. The ordering is load-bearing — union first, then
subtract — which is exactly where today's `direct_ids` sits.

Because `always` enters by union and not by the matcher, the `_alias_match` `!= "auto"` skip stays
correct and is **not** loosened to admit `always` — doing so would make Always mean "always, but only
when mentioned."

### 4. `expand_context`'s unconditional run is collapsed into the gate

`expand_context` no longer runs on every send. It runs **iff `lore_enabled`**, and its detections feed
the journal that `relevant_lore()` reads (§1) — they are inputs to the one dedupped set, never a second
block assembled beside it. This deletes the parallel, ungated channel outright, which is what makes both
the lore-free-prompt guarantee (Journey C) and the disappearance of the unreconciled double-inclusion
fall out: with one function producing one keyed-by-id result, there is nothing left to reconcile.

### 5. The result is placed once, in the volatile tier

> **⚠ Superseded — see `docs/design/context-caching.md` §7.** "Single placement in
> the *volatile* tier" is wrong against the provider cost model: it pushes stable
> content into the 5-minute tier and re-bills its cache-write premium whenever the
> tier changes (up to ~5× on Anthropic for a slow turn cadence). The corrected rule
> is **"placed once *per stability tier*"**, where the tier is decided **per turn by
> each entry's revision** — unchanged-since-last-turn → a **1-hour** stable block,
> new-or-changed → a **5-minute** volatile block — via the session baseline, not a
> static policy label. One selector, one dedupped set, each node once; only the
> placement is tiered by freshness. Everything else in §5 and the rest of this ADR
> (§1–4, 6) is unchanged and correct.

Conversation-aware lore is *volatile* — the set grows as later turns mention new entities — so the
rendered lore belongs in the short-TTL tier, re-derived each send from `relevant_lore()`'s current
result, not baked into the long-TTL system prompt. One selection, one placement. The exact block
structure is left to implementation (ADR-0005); the binding constraints are: single placement, volatile
tier, formatted through `_format_lore_block`, and — because `relevant_lore()` is the sole renderer —
nothing else emits a lore block that would need reconciling against it.

### 6. The gate signal is stable-tier state and inherits the existing freshness contract

`lore_enabled` is captured at the chat-creation render and persisted; the send path never re-renders the
template (the system prompt is opaque — §Context), so the flag is not re-evaluated per turn. A prompt
whose `relevant_lore()` is gated on something that *changes across turns* (`{% if turn > 3 %}`) will not
re-flip mid-conversation. **This is the same staleness already accepted for any object in the 1-hour
cache tier** — altered after it is cached, it is stale until the tier is rebuilt/cache-broken — and it
self-heals on the same boundary. Documented here by reference to that decision, not re-litigated;
realistic prompts either use lore or do not.

### 7. The one rule

> Whether a conversation sees lore is the prompt's choice, expressed by using `relevant_lore()` and read
> from its execution. *What* it then sees is that one function's result — every route a node can enter
> by, unioned and keyed by id, minus never/manual — computed once. The send path feeds and persists that
> result; it never makes a second one.

## Why / rejected alternatives

- **Shallow fix: add `relevant_lore()` to `revise-entry.md`.** Fixes brainstorm and nothing else.
  Rejected: it special-cases one template to hide a general gap
  (`feedback_dont_special_case_to_hide_a_general_gap`) — every future prompt must remember the call — and
  it leaves the ungated, `always`-blind send channel in place, so the lore-free-prompt violation and the
  unreconciled double-inclusion remain.
- **Backend force-attaches `always` on every send.** The first "deep" idea. Rejected: it *destroys*
  Journey C — a prompt deliberately written lore-free would still receive the always-notes — and, by
  keeping the render channel's own `always` union, it reintroduces exactly the two-selector reconciliation
  this ADR removes.
- **Static detection — scan the template text for `relevant_lore(` and store a flag.** Rejected: the
  reachability problem (§Anti-goals). A conditional or an `{% include %}`d snippet makes the source text
  a wrong predictor of what runs. Observing execution dissolves the guess.
- **A user-facing lore on/off knob on the prompt/chat.** Rejected as the *primary* mechanism: it invents
  a new concept the writer must learn and keep in sync with the template, and it can disagree with what
  the template actually does. Kept only as the *stored form* of the derived signal (§2).
- **Two selectors plus a reconciliation step to strip the overlap.** Rejected: the backend cannot read
  the opaque system prompt to know what the render channel already emitted, so the reconciliation is
  unreliable at the boundary. Collapsing to one selector whose result is a set (§1/§3) makes the overlap
  unrepresentable rather than subtracted.
- **Re-render per turn to keep the gate fresh.** Rejected on two counts: the send path receives the
  system prompt as an opaque string and does not re-render; and the staleness it would chase is the same
  one already accepted for the stable cache tier (§6), not worth a per-turn render cost.

## Consequences

- **New:** a persisted `lore_enabled` signal on the chat, populated by instrumenting `relevant_lore()` to
  record its execution and capturing it at the creation render; the wholesale `always` union moved into
  the one selection; `expand_context` gated on `lore_enabled` and demoted to a journal-input feeder.
- **Removed:** `expand_context`'s unconditional, prompt-independent run as a *separate* lore block — and
  with it the lore-free-prompt violation and the unreconciled double-inclusion (both gone because there
  is now one keyed-by-id result, no second block to reconcile).
- **Reused, not rebuilt:** `_alias_match` / `_textual_one_hop` (auto matching), `_always_included_lore_ids`
  (the union, now inside the one selection), `_format_lore_block` (formatting, ADR-0006), the
  `in_scope` subtraction (now the dedup point for the union too), the chat/journal storage (ADR-0051),
  the `create_environment_for_project` env that already accepts a `journal`.
- **Behaviour change to a public helper:** `relevant_lore()` gains a side effect (it flags intent), folds
  in explicit picks and the `always` union, and returns a set dedupped by id. Strictly *more* correct for
  author templates: before, an `always` note appeared only if your template called the helper; now it
  appears whenever the prompt is lore-enabled, once, however many routes reach it. Pre-1.0, no migration
  (`feedback_no_pre_1_0_migrations`).
- **Unchanged:** per-entry `context_policy` meanings; `never`/`manual_only` exclusion on the auto path;
  the scene-authoritative and as-of read models (ADR-0055).

## Deferred / adjacent (named, not blockers)

- **`_relevant_lore` leaks `manual_only` via structural refs.** Its chokepoint (`_never_lore_ids`) filters
  `never` only, so a `manual_only` entry pulled in via an `entity_ref`/structural expansion can reach a
  rendered prompt. Its own issue.
- **The manual picker enforces no `context_policy`.** `context_items` (`ChatSessionContextItem`,
  `models/ai.py`) are stored and rendered with no policy check, so a `never` entry can still be manually
  attached; enforcing picker visibility is a frontend concern. Its own issue.
- **Per-turn gate refresh** (re-evaluating `lore_enabled` mid-conversation) — deferred behind the §6
  freshness contract; revisit only if a real prompt needs a turn-varying gate.

## Suggested slicing (indicative, not decided here)

1. **The `always` union in the one selection** — the substantive bug fix (#1016's symptom):
   `relevant_lore()` / the send-time selection performs the wholesale `always` union, dedupped by id
   against explicit picks and the journal. Independently valuable; makes the two Always notes appear.
2. **The gate** — instrument `relevant_lore()` to record execution; persist `lore_enabled`; gate
   `expand_context` on it and demote it to a journal-input feeder; delete the separate unconditional
   block. Delivers Journey C and removes the double-inclusion.
3. **Placement/tiering cleanup** — ensure the one dedupped result is placed once in the volatile tier and
   `relevant_lore()` is the sole renderer, retiring any now-redundant path.
