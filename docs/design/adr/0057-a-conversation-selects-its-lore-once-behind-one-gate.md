# ADR-0057: A conversation selects its lore once, and the prompt gates it by using `relevant_lore()`

- Status: **Proposed** — 2026-08-15 (authored by Claude; awaiting Anton's approval). Origin: dogfooding
  — a create-character brainstorm ignored two `lore:note`s the writer had marked **Context policy =
  Always**. Tracing the drop surfaced not a missing feature but a *second*, ungated lore-selection
  channel on the send path that the render-time channel never reconciles with.
- Follows: ADR-0006 (lore context is resolver-mediated at the `_format_lore_block` formatter), ADR-0026
  (type-aware Jinja helpers — `relevant_lore()` is one), ADR-0051 (a node owns its conversations —
  chats are first-class subject-referencing nodes), ADR-0055 (a conversation reads as-of a scene; the
  send-time envelope assembly).
- Governed by: the layered context envelope's **cache-coherence tradeoff** — a stable (long-TTL) tier
  and a volatile (short-TTL) tier, an object placed in the stable tier is stale-until-refresh
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
- **Latent double-inclusion.** For roleplay, an entry can land in *both* the rendered system prompt
  (channel 1) and the send-time journal block (channel 2); nothing deduplicates them.

What is **not** broken: per-entry `context_policy` is honoured on the send path. `_alias_match`'s
`!= "auto"` skip applies transitively — the depth-1 pass is another `_alias_match` over the matched
entries' bodies — so `never` and `manual_only` are excluded there, in fact more strictly than
`_relevant_lore`'s own chokepoint (`_never_lore_ids`), which filters `never` only. The defect is that
the second selector is **ungated and `always`-blind**, not that it disobeys policy.

## Intent

**Lore enters a chat through exactly one gate the prompt controls, and is selected exactly once.**

- **One gate.** Whether a given prompt sees lore is the prompt author's choice, honoured by every
  channel. Gate off → nothing injects lore (a truly lore-free prompt is expressible). Gate on → the
  selector runs.
- **One selection.** A single policy-complete selection produces the in-scope lore for a send —
  `auto` by alias match, `always` by wholesale union, `never`/`manual_only` excluded — placed once.
  There is no second channel re-selecting lore that the first must then be reconciled against.

## Anti-goals (what this must not do)

- **No second selection channel, and therefore no dedup.** The repair is to *collapse* the two channels
  into one, never to keep both and subtract the overlap. If a design needs a dedup step it is selecting
  the same lore twice — the defect, not the fix.
- **No static text-scan for the gate.** Deciding lore-intent by grepping a template for `relevant_lore(`
  is the reachability problem: the helper can sit behind `{% if … %}`, inside an `{% include %}`d
  snippet, three conditionals deep. Intent is read from *execution*, never from the source text.
- **No new user-facing lore knob.** The gate is not a checkbox the writer toggles; calling
  `relevant_lore()` *is* the declaration of intent, and the stored signal is populated by observing that
  call. (The signal is stored — the "explicit" half — but never hand-set.)
- **No change to per-entry `context_policy` semantics.** `auto`/`always`/`never`/`manual_only` keep their
  meanings; this ADR changes *where and how many times* they are interpreted, not what they mean. In
  particular `always` is **not** turned into a match — that would silently demote it to a fancy `auto`.
- **The send path does not select.** Its jobs stay: call the provider, enforce AI policy (fails-closed),
  persist chat state, tier the envelope for cache coherence. "Decide which lore is relevant" is not among
  them.
- **No re-agonizing the stale-tier tradeoff.** The gate is stable-tier state and inherits the
  staleness-until-refresh property already accepted for the 1-hour cache (§6). It is not a new caveat.
- **The two adjacent bugs are named, not fixed here** (§Deferred): `_relevant_lore`'s structural
  chokepoint leaks `manual_only`; the manual picker enforces no policy.

## User journey

**A — the world context that was set up to always be present.** The writer authors two `lore:note`s —
"Feral Line: Urban Bestiary universe" and "Premise" — and sets each to **Context policy = Always**,
exactly so every conversation carries them. They open a character and start an AI **create-character**
brainstorm. The create prompt uses lore (it calls `relevant_lore()`), so the gate is on; the one
selector runs and its **wholesale `always` union** pulls both notes in, mentioned or not. The model
brainstorms the protagonist already knowing the world and the premise. *(Today: both notes are dropped,
because the create prompt's channel never performs the `always` union.)*

**B — the prompt that must stay clean.** The writer authors a mechanical prompt — a pure style pass —
that deliberately does **not** call `relevant_lore()`. The gate is off. No lore is injected, by the
template or the backend. The pass sees only what the author put in front of it. *(Today: impossible —
`expand_context` auto-injects lore into it regardless.)*

## Decision

### 1. Lore is selected once; the send path transmits, it does not select

There is a single policy-complete selection that yields the in-scope lore id-set for a send. The send
path (`_prepare_chat_send_payload`) *drives and persists* that selection and formats it through the
existing `_format_lore_block` (ADR-0006), but it no longer runs an **independent** matcher whose result
is unrelated to what the prompt asked for. The pre-existing coupling makes this natural: `_relevant_lore`
in chat-session mode already **trusts the journal `expand_context` populated** rather than re-deriving
(`helpers.py`) — so the code already treats the send-time expander as the de-facto selector and the
helper as a renderer of it. This ADR formalizes that: **`expand_context` is the one selector; the helper
renders the selection into the prompt.**

### 2. The gate is the runtime execution of `relevant_lore()`

A chat carries a persisted **`lore_enabled`** signal. It is set as a **side effect of `relevant_lore()`
executing** during the chat's render: the helper records its own invocation on the render context, and
the chat-creation render captures that into `lore_enabled` on the chat (chat-session state, not a
user-facing metadata field — exact storage slot is implementation, per ADR-0005's lesson). This is the
mixture of *derive* and *explicit*: an explicit stored flag whose value is derived from actual execution,
so it can never drift from the template — it *is* the template running — and it catches the cases a
static scan misses (the fired conditional branch, the snippet reached through `{% include %}`).

- **Gate off** (`relevant_lore()` never executed) → the selector does not run; nothing injects lore.
- **Gate on** → the selector runs (§3).

### 3. One selector interprets all four policies, in one place

When the gate is on, the single selection is:

- **`auto`** — included when the scanned text matches (`_alias_match`, unchanged), plus the existing
  one-hop textual expansion (`_textual_one_hop`), itself auto-gated transitively.
- **`always`** — included by **wholesale union** (`_always_included_lore_ids`), independent of any
  mention or of depth-1. This is the substantive fix: the union moves onto the single selection path so
  it fires for *every* lore-enabled chat, not only those whose template happened to call the helper.
- **`never` / `manual_only`** — excluded from the automatic selection (the `!= "auto"` gate already does
  this on this path).

Because `always` enters by union and not by the matcher, the `_alias_match` `!= "auto"` skip stays
correct and is **not** loosened to admit `always` — doing so would make Always mean "always, but only
when mentioned."

### 4. `expand_context`'s unconditional run is collapsed into the gate

`expand_context` no longer runs on every send. It runs **iff `lore_enabled`**, and when it runs it is
`always`-complete (§3). This deletes the second, ungated channel outright — which is what makes both the
lore-free-prompt guarantee (Journey B) and the disappearance of double-inclusion fall out, with no dedup
step. The manual picker's `context_items` continue to be honoured as explicit author choices,
independent of the gate (they are not policy-filtered today; that gap is §Deferred, unchanged here).

### 5. The selection is placed once, in the volatile tier

Conversation-aware lore is *volatile* — it grows as later turns mention new entities — so the selected
lore block belongs in the short-TTL tier, not baked into the long-TTL system prompt. One gated selection,
one placement. The exact block structure is left to implementation (ADR-0005): the binding constraints
are single-placement, volatile-tier, and formatted through `_format_lore_block`.

### 6. The gate is stable-tier state and inherits the existing freshness contract

`lore_enabled` is captured at the chat-creation render and persisted; the send path never re-renders (the
system prompt is opaque — §Context), so the flag is not re-evaluated per turn. A prompt whose
`relevant_lore()` is gated on something that *changes across turns* (`{% if turn > 3 %}`) will not
re-flip mid-conversation. **This is the same staleness already accepted for any object in the 1-hour
cache tier** — altered after it is cached, it is stale until the tier is rebuilt/cache-broken — and it
self-heals on the same boundary. It is documented here by reference to that decision, not re-litigated;
realistic prompts either use lore or do not.

### 7. The one rule

> Whether a conversation sees lore is the prompt's choice, expressed by using `relevant_lore()` and read
> from its execution; *what* it then sees is one policy-complete selection — auto by match, always by
> union, never/manual excluded — computed once. The send path carries and persists that selection; it
> does not make a second one.

## Why / rejected alternatives

- **Shallow fix: add `relevant_lore()` to `revise-entry.md`.** Fixes brainstorm and nothing else.
  Rejected: it special-cases one template to hide a general gap
  (`feedback_dont_special_case_to_hide_a_general_gap`) — every future prompt must remember the call — and
  it leaves the ungated, `always`-blind send channel in place, so the lore-free-prompt violation and the
  double-inclusion remain.
- **Backend force-attaches `always` on every send.** The first "deep" idea. Rejected: it *destroys*
  Journey B — a prompt deliberately written lore-free would still receive the always-notes — and it
  recreates the exact double-inclusion that needs dedup, because the render channel still also unions
  `always`.
- **Static detection — scan the template text for `relevant_lore(` and store a flag.** Rejected: the
  reachability problem (§Anti-goals). A conditional or an `{% include %}`d snippet makes the source text
  a wrong predictor of what runs. Observing execution dissolves the guess.
- **A user-facing lore on/off knob on the prompt/chat.** Rejected as the *primary* mechanism: it invents
  a new concept the writer must learn and keep in sync with the template, and it can disagree with what
  the template actually does. Kept only as the *stored form* of the derived signal (§2).
- **Dedup the two channels.** Rejected: it is scar tissue over selecting the same lore twice. Collapsing
  to one selector (§4) removes the duplication at the source, so there is nothing to reconcile.
- **Re-render per turn to keep the gate fresh.** Rejected on two counts: the send path receives the
  system prompt as an opaque string and does not re-render; and the staleness it would chase is the same
  one already accepted for the stable cache tier (§6), not worth a per-turn render cost.

## Consequences

- **New:** a persisted `lore_enabled` signal on the chat, populated by instrumenting `relevant_lore()` to
  record its execution and capturing it at the creation render; the wholesale `always` union moved onto
  the single selection path; `expand_context` gated on `lore_enabled`.
- **Removed:** `expand_context`'s unconditional, prompt-independent run — and with it the lore-free-prompt
  violation and the roleplay double-inclusion (resolved as a side effect, no dedup written).
- **Reused, not rebuilt:** `_alias_match` / `_textual_one_hop` (auto matching), `_always_included_lore_ids`
  (the union, now on the one path), `_format_lore_block` (formatting, ADR-0006), the chat/journal storage
  (ADR-0051), the `create_environment_for_project` env that already accepts a `journal`.
- **Behaviour change to a public helper:** `relevant_lore()` gains a side effect (it flags intent) and its
  `always` union is unified onto the single selection rather than being render-only. Strictly *more*
  correct for author templates: before, an `always` note appeared only if your template called the
  helper; now it appears whenever the prompt is lore-enabled. Pre-1.0, no migration
  (`feedback_no_pre_1_0_migrations`).
- **Unchanged:** per-entry `context_policy` meanings; `never`/`manual_only` exclusion on the auto path;
  the manual `context_items` picker; the scene-authoritative and as-of read models (ADR-0055).

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

1. **The `always` union on the send path** — the substantive bug fix (#1016's symptom): `expand_context`
   performs the wholesale `always` union. Independently valuable; makes the two Always notes appear.
2. **The gate** — instrument `relevant_lore()` to record execution; persist `lore_enabled`; gate
   `expand_context` on it; delete the unconditional run. Delivers Journey B and removes double-inclusion.
3. **Placement/tiering cleanup** — ensure the one selection is placed once in the volatile tier and the
   render channel renders (not re-selects), retiring any now-redundant path.
