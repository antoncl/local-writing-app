# ADR-0092: What a send carries — declared picks, automatic lore, and the three words a prompt has for them (a summation)

- **Status:** Accepted — 2026-09-23, Anton Lauridsen; text by Claude from a fact-finding pass
  with Anton on the first live run of ADR-0091, revised against two cold implementing
  threads' findings before acceptance (PR #2150). **A summation, qualified by §7.** §§1–6 decide nothing new: they
  gather, into one document, what the send path does today with the lore a prompt names and
  the lore the app finds on its own — decisions that live across ADR-0057, ADR-0060, ADR-0075,
  ADR-0084 and ADR-0086 and had no single home, so "does `use()` turn on automatic lore?" had
  no answer a reader could find, and a built-in was written on the wrong answer. §7 makes the
  two decisions the facts forced: the automatic gate opens only on the call that asks for it,
  and that call is renamed for what it does. §8 records one deferral with the constraints
  found while sizing it. Acceptance alone starts nothing; each slice gets its own issue and an
  explicit go.
- **Consolidates:** ADR-0057 (the one gate, the one selector), ADR-0060 §2/§5 (`use()`, the
  volatility hint, `use_lore()` as the rename of 0057's emitting `relevant_lore()`), ADR-0075
  (detection surfaces and the matcher), ADR-0084 (cache strategy per model), ADR-0086 and its
  Amendment 1 (declared versus inferred, the budget, reach, the fit order, the journal's
  identity), ADR-0067 Amendment 2 (the commit turn's `used` mode), ADR-0091 §4 (the Propose
  message). Relates: ADR-0049 (built-ins are Library files), ADR-0087/0088 (snapshots and
  compare mode), #2143 (the finding that prompted this), #2142 and #2147 (two surface defects
  fixed on the way, recorded here as rules), #2148 (the writer-facing guide, after this).
- **Words used here.** A *pick* is an entry a prompt names with `use()`. *Automatic lore* is
  what the app adds on its own once a prompt asks for it. *Declared* and *inferred* are
  ADR-0086's two halves of one send; §7.1 narrows what "declared" means when automatic lore
  is off. The *gate* is two things that this document keeps apart: the per-render **slot**
  (`lore_invoked`, set while a template renders) and the per-chat **flag** (`lore_enabled`,
  captured from the slot and persisted). A *surface* is a text the name matcher scans. The
  *journal* is the chat's append-only record of what automatic detection noticed and why. A
  *block* is one placed, cacheable unit of context on the wire; a *tier* is a block's cache
  class.
- **Verified against `cd000dd7` (2026-09-23).** Symbols first, line numbers second.

## 1 — A send carries two halves of lore, and one flag decides whether the second runs

Every chat turn that reaches a model carries, besides the system prompt and the transcript, a
set of lore entries the backend selects, deduplicates by id, renders as XML and places in
cache-tiered blocks (`_lore_cache_blocks`, `backend/app/services/ai/chat.py`, calling
`_budgeted_lore_tiers` in `lore_selection.py`). ADR-0086 split that set in two:

- **Declared** — the chat's `use()` picks, the anchored scene's own reference fields, and every
  entry whose context policy is *always*. Never dropped, never counted against the budget.
- **Inferred** — what automatic detection and expansion found (§3), fitted to the assistant's
  budget in the fit order of §4. This is the half a writer means by "the AI pulled that in".

One flag on the chat, `lore_enabled`, is read three times on a send
(`expand_and_prepare_chat_blocks`, `chat.py`): to resolve the chat's scene at all, to run
detection and the tiered placement on an ordinary turn (`lore_mode == "implicit"`), and to
place the picks on the commit turn (`lore_mode == "used"`, ADR-0067 Amendment 2). So today
the flag gates the declared half as much as the inferred one. It is captured from the
template's slot: authoritatively at the lock render, and before the lock by every estimate
fetch (`chatEstimate.svelte.ts`, `mayCaptureLoreGate`). The slot is set if the template
called `use_lore()` — **or `use()`**. That second clause is ADR-0060 §2's "using a node means
the chat is lore-enabled", and it is the fact §7 changes: today no prompt can place a pick
without also opening automatic selection, which is how ADR-0091's built-in, meant to check
one entry against a change, was handed seven.

## 2 — The three words a prompt has, and what none of them does

- **`use(node)`, `use(node, "stable" | "volatile")`** (ADR-0060 §2/§5, `helpers._use`): "also
  include this node." Emits nothing; records the resolved id (every id, for a multi-pick
  input) on the chat as `used_node_ids`, and the optional hint as `used_node_hints`. The pick is
  declared. The hint is a prior on which cache tier the block starts in and never overrides the
  per-revision check (§5). Picks are exact: they are not seeds for expansion (§3); an author who
  wants a pick's neighbours loops its refs and picks them.
- **`use_lore()`** (ADR-0060 §2, `helpers._use_lore`; the rename of ADR-0057 §2's emitting
  `relevant_lore()`): the gate-only declaration. Emits nothing; sets the slot. The emitting
  form was retired because its output would have been frozen into the prompt and
  double-counted against the placed blocks. Its name reads as a sibling of `use()` and says
  nothing about *automatic*; §7 renames it.
- **`entry(x)`, `original(x)`** and the rest of the vocabulary (`docs/prompts/reference.md`)
  render values into the prompt text; they place nothing and set nothing. `entry(x)` is the
  node as of the prompt's scene, `original(x)` the node at book start. **Nothing reaches a
  snapshot** (ADR-0087's store): a prompt cannot render or place an entry as it was at a
  captured moment. That is why ADR-0091 §4's Propose message carries the source's before and
  after as text in the first user turn — two full renders in a turn that, under a provider
  with cache breakpoints, is cached only if a later breakpoint lands after it — and why the
  matcher then journals every entry that text names. §8 records what placing a snapshot would
  take.
- **None of them sets up caching.** Caching happens on the send path for every block the
  backend places, declared or inferred, by revision and by the assistant's cache strategy
  (ADR-0084). The hint on `use()` biases a tier; nothing in a template creates a breakpoint.

## 3 — What automatic detection scans, and how it expands

**Detection** compiles one name matcher from every lore entry's title and aliases as of the
anchored scene (`_build_scene_matcher`), minus entries whose policy is *never* or
*manual only*, and runs it over three surfaces in one pass per turn
(`_detect_and_persist_journal`, `chat.py`), journaling each hit with its source:

- the last user message — `user_message`;
- the fully rendered, locked system prompt, on the first turn — `rendered_prompt`;
- the anchored scene's own prose surface: its body plus the value of every `long_text` field
  on its type, each text scanned on its own, never concatenated — `scene_prose`
  (`_scene_prose_ids`, `_prose_texts`). Never single-line text, titles or aliases. A chat with
  no scene has no third surface.

The matcher's boundary is ADR-0075 §3's `[A-Za-z0-9_']` on both sides, so an underscore is a
word character; a name in markdown italics, `_The Implant_`, never matched on the backend,
which scans raw markdown, while the editor scans rendered text where italics are marks.
Since #2142 both matchers **mask emphasis underscores** to spaces inside the scan, same length
in and out, so positions still address the original text and the ADR-0085 corpus is
untouched. The boundary class is unchanged; the surface was brought level.

**Depth-one textual expansion**, journaled as `depth1_expansion`: the prose surface of every
detected entry — body plus `long_text`, the same collector as detection since #2147, one text
at a time — is scanned once with the same matcher. What that finds is not rescanned; depth is
strictly one, to stop cascades in cross-referenced lore.

**One structural hop**, offered as `structural_hop`: each seed's reference fields — top-level
entity refs and lists, and the reference members of a group-list item, through the one
traversal the reference index walks — are followed once. Manual-only entries are not fanned
in by this route.

**Seeds** for both hops are the scene's own references, every *always* entry, and every
detection. A pick is not a seed; a pick that is also detected in a surface seeds like any
detection, which is how a message naming the dependent pulls in the dependent's neighbours.

## 4 — The assistant's two settings shape the inferred half only

- **Lore budget** (`ai_lore_budget_tokens`, default 16 000; `0` = declared only). Whole
  entries, first-fit in the fit order, measured with the one token estimator every profile
  uses; applied after selection and before tiering; the send reports `lore_fit` (used,
  budget, kept, left out) on the response, the stream's `done` line and the persisted message.
- **Lore reach** (`ai_lore_expansion`: "One hop", the default, or "Named only"). Applied at
  selection, never at detection: "Named only" drops the `depth1_expansion` journal entries
  and skips the structural hop; the journal still records the depth-one detections and the
  Context door still shows them as noticed.
- **Fit order** (ADR-0086 §1, `lore_budget.py` `_SOURCE_RANK`): distance from the author's own
  words — `user_message`, `rendered_prompt`, `scene_prose`, `depth1_expansion`, then
  `structural_hop`; within a source, latest-journaled first, then id. The budget drops the
  structural hop first.

Neither setting touches a pick, a scene reference or an *always* entry. The assistant is the
one place reach and budget live (ADR-0086 rejected declaring them on the prompt); this ADR
keeps that.

## 5 — Placement, dedup, tiers, and the journal's shape

- **One deduped set, keyed by entry id.** Picks join the selector's direct channel and
  dedupe against detections by id (`_select_lore`, `_Candidates.offer`, `lore_selection.py`);
  an id reachable both ways is declared. Every entry renders once, as the XML
  `_render_lore_entries` produces; a `never` entry is dropped whichever route offered it, a
  pick included.
- **Two tiers per turn** (`_tier_lore_ids`, `lore_selection.py`): unchanged since the session
  baseline → stable, new or changed → volatile. The `use()` hint biases the start —
  "volatile" pins; "stable" holds unless the entry actually changed — and never rides stale
  bytes. Stable blocks are placed first; the provider profile assigns each tier its TTL and
  caps breakpoints (ADR-0084). The commit turn (`used` mode) is the one untiered placement:
  the picks alone, one block, no baseline commit.
- **The journal is append-only across the session**, so the cache breakpoint after it can
  ratchet forward as it grows (`ChatSessionJournalEntry`, `backend/app/models/ai.py`). Its
  identity is `(entry_id, source)`, not `entry_id`: a later, better-ranked mention of an
  already-journaled id appends a second entry, and the selector keeps the best-ranked
  candidate per id (ADR-0086 Amendment 1). Title and type are snapshotted at detection so the
  door keeps showing what the writer saw.

## 6 — The case that exposed the gap

ADR-0091's built-in `Follow a change` opens a conversation on a dependent with the source's
before and after in the first message, and its job is to check that one entry. Its template
placed the dependent with `use(e)`; that set the slot; the message named the source and the
entries the source names; detection journaled them; depth-one expansion added their
neighbours; seven entries stood beside the one the role named, and two models of different
sizes reviewed all seven. Dropping `use_lore()` from the template changed nothing, because
`use()` had set the slot already (#2143) — and the built-in includes the `Relevant lore`
snippet, whose own `use_lore()` sets it again the moment the writer picks an extra entry. Two
levers exist today, both on the assistant: a budget of `0`, or "Named only". Neither is where
a prompt author would look, and neither should be needed to say "just this entry".

## 7 — Decisions

### 7.1 `use()` places; it does not set the slot

> **Qualified by Amendment 1 (draft):** *always* entries are placed whether or not automatic
> lore runs, unless the prompt calls `no_lore()`. The first bullet's "not the *always*
> entries" is withdrawn, and the third bullet's signal "tier rows present, annotation absent"
> now means picks or *always* entries placed. Scene references stay as written.

The slot is set by the automatic-lore call alone. ADR-0060 §2's "using a node means the chat
is lore-enabled" is withdrawn, and `lore_enabled` comes to mean exactly "automatic lore is
on". What follows, stated for each place the flag is read today:

- **A send with picks and the flag off places the picks, minus `never`, and nothing else.**
  Not the scene's references, not the *always* entries: those are ADR-0086's declared sources
  only when automatic lore runs — this narrows 0086 §1's table by reference, and
  `_select_lore` gains a declared-only mode (picks in, inferred empty) rather than a second
  path. The picks are tiered, committed against the session baseline and recorded in
  `seen_revisions` exactly as on a gated turn; `lore_fit` is reported with nothing left out.
  The chat's scene is resolved whenever there are picks or the flag is on, so a pick renders
  as of the chat's scene either way.
- **The commit turn keys on the picks, never on the flag.** Today `lore_mode == "used"` is
  entered on `lore_enabled`; under this decision a `use()`-only prompt would otherwise commit
  with no entry at all. ADR-0067 Amendment 2 is amended by reference: "the picks through the
  one selector's `used` mode" holds; the condition is `used_node_ids`.
- **The preview mirrors the send.** The estimate computes the pick-only tiers when the slot
  is off and there are picks, without running detection, so the Context door shows the picks'
  tier rows before the first send and the estimate counts them. The preview's `lore_enabled`
  is false for such a prompt, and the door's "lore-enabled" annotation is absent: tier rows
  present, annotation absent, is the signal for "picks placed, automatic off".
- **The `Relevant lore` snippet stops setting the slot.** It becomes what its name says, the
  writer's explicit extra picks; a prompt that wants automatic lore says so itself. The two
  built-ins that include it already do. A writer's own prompt that relied on the include
  alone to open automatic lore changes behaviour; the reference's description of the snippet
  says so, and the deprecation notice of §7.2 is not the place for it because nothing is
  renamed there.
- **Chats locked before this change keep their flag.** A chat locked from a `use()`-only
  prompt carries `lore_enabled: true` under the old meaning and keeps automatic lore until it
  is cleared and relocked; for such a chat the estimate, which re-renders the live prompt,
  shows pick-only tier rows while the send still runs automatic lore. Bounded to those
  chats, documented, not migrated; Clear unlocks.

### 7.2 `use_lore()` becomes `auto_lore()`

The name says what the call does. The old name stays as an alias for a deprecation period:
rendering a template that calls `use_lore()` still sets the slot and adds one entry to the
render's `warnings` — produced by a render-time slot the preview reads back, once per render
however many times the alias is called — reading "`use_lore()` is now `auto_lore()`; rename
it — the old name is removed at 1.0". It rides `warnings` wherever they already show: the
chat's meta line on every estimate, the inputs dialog, the prompt editor's preview, the
one-shot generate. That is the danger register on every turn of every chat bound to such a
prompt; it is loud on purpose and costs the author a two-second rename.

The vocabulary reference (`docs/prompts/reference.md`, the gate-enforced surface) lists
`auto_lore()` in the Helpers table and `use_lore()` in a new **Deprecated** table, which the
vocabulary gate accepts as registered and the generator marks `deprecated`, so the editor's
completion stops offering the old name while the reference still shows it. The built-ins
switch to the new name. The removal at 1.0 is one checklist: the alias in `helpers.py`, the
Deprecated row, the generated manifest and guides bundle, and the docs that teach the call
(`docs/prompts/helpers.md`, `guide.md`, `template-language.md`, `preview.md`, `README.md`,
`docs/roleplay.md`, `docs/design/context-caching.md` §4, which is already stale on the
picks' field name). No storage changes; no migration.

## 8 — Deferred, with its constraints: placing an entry at a snapshot

> **Discharged by ADR-0093 (2026-09-23):** the carrier is `use(node, snapshot=id)`; each
> constraint below has its home in ADR-0093 §5.

A prompt that could place the source's before-state as a block would let ADR-0091 §4's
message shrink to its question. It is deferred, not sketched, until the message's cost bites
on a live project; the sizing pass found the constraints any such design must meet, and they
are recorded here so its ADR starts from them rather than from a guess:

- **Dedup.** Keyed by entry id the before would collapse into the after (Anton's catch); the
  key must be the entry and the snapshot together, and every consumer that treats a placed id
  as a node id must know the difference.
- **Storage.** The send re-renders nothing and reads only what the lock persisted, so a
  snapshot pick is a new persisted field on the chat, not "no storage".
- **Layers.** ADR-0087's store holds one lane's file; on a layered project the before-state is
  the fold ADR-0091 §1 defines, so the placement folds, and a bare snapshot id addresses one
  lane.
- **Identity.** A snapshot id alone names nothing; the store is keyed by entity, so the
  template needs the source's id beside the snapshot's.
- **Not stable by construction.** The renderer resolves references live (titles, summaries,
  healed refs), so a snapshot element's bytes can change between turns; stable placement is a
  bet to bound by the same revision rule as any block, not a property.
- **Not a wire block.** Provider breakpoints are capped; a snapshot state is an element in
  the stable tier, labelled for the Context door, which today names rows by roster title.
- **ADR-0091 §4** ("no prompt variable, no vocabulary registration") is what such an ADR
  amends.

## Anti-goals

> **Qualified by Amendment 1 (draft):** not calling `auto_lore()` now gives a prompt its picks
> *and* the *always* entries. A prompt gets its picks alone by calling `no_lore()`.

- **Not a change to detection.** The surfaces, the matcher and the parity gate are ADR-0075's
  and stay; §3 records them.
- **Not reach or budget on the prompt.** The assistant remains the one place (ADR-0086); a
  prompt gets "picks only" by not calling `auto_lore()`, which is a different thing from a
  budget of zero — that keeps the scene's references and *always* entries — and needs no
  setting.
- **Not retrieval.** A better selector is a later decision, as ADR-0086 said.
- **Not a new surface for the writer.** The Context door, the meta line and the preview strip
  already show what was placed and why; the rename shows there as a warning.
- **Not the snapshot carrier.** §8 records it; nothing here builds it.

## Why / rejected alternatives

> **Reversed in part by Amendment 1 (draft):** the rejection of keeping *always* entries on a
> pick-only send is withdrawn; it stands for the scene's references. The "declared only"
> switch rejected below now exists as `no_lore()`, because not calling `auto_lore()` no longer
> keeps a prompt free of lore.

- **Keep `use()` setting the slot and fix the built-in with wording.** Rejected by use: two
  models ignored a scope sentence in favour of the seven entries in front of them. What a
  model is given decides more than what it is told.
- **A per-call reach on `use()`.** Rejected: it would reopen ADR-0086's one-place rule, and it
  cannot address the case anyway, since the entries arrived through the gate, not through
  the pick's neighbours.
- **A prompt-level "declared only" switch.** Rejected as redundant once §7.1 holds: not
  calling `auto_lore()` is the switch, and it is the one a prompt author already understands.
- **Keep the scene's references and `always` entries on a pick-only send.** Rejected: they
  are automatic lore by any writer's reading — the app added them — and a prompt that did not
  ask for automatic lore would get some anyway; ADR-0086's table is narrowed, not broken.
- **Rename without a deprecation period.** Rejected: writers' own prompts are files in their
  projects; a silent break is the worst outcome and a warning costs nothing.
- **Hide the deprecation from the meta line.** Rejected: a notice that shows only in the
  prompt editor reaches the author who never opens it; every turn is the nudge.
- **Decide the snapshot carrier here.** Rejected: twenty-three open points and three false
  premises in the first draft; a deferral that records constraints is safe, a sketch is not.

## Consequences

- **Storage:** none. `lore_enabled`'s meaning narrows; a chat persisted with it on keeps its
  stored behaviour (§7.1, last bullet). No new fields; no migration.
- **API / wire:** the preview response's `lore_enabled` is false for a pick-only prompt, and
  its `cache_blocks`, `lore_fit` and `estimated_tokens` carry the picks the send will place;
  `warnings` carries the deprecation notice.
- **Prompt vocabulary:** `auto_lore()` added; `use_lore()` moved to a Deprecated table the
  gate accepts and the completion hides; the generated manifest and guides bundle
  regenerated; the docs above updated.
- **Built-ins:** `Revise entry` and `Roleplay` switch to `auto_lore()`; `Relevant lore` drops
  its gate call; `Follow a change`'s comment becomes literally true.
- **Frontend:** copy only — the Context door's "invoked use_lore()/use()" title, the composer
  bar's and the chat view's comments, the lock helper's comment; no logic changes, since the
  lock and the estimate keep reading `lore_enabled`.
- **Tests:** the slot set by `auto_lore()` and not by `use()` (several existing assertions
  invert, including the one whose docstring argued the coupling was correct); a `use()`-only
  chat places its picks with the flag off, tiered and committed, and again on the commit turn
  (a wire test that the pick reaches the provider's system blocks); the preview for a
  pick-only prompt carries the picks and `lore_enabled: false`; the alias sets the slot and
  emits the notice once; `auto_lore()` emits none; the built-in bodies; the vocabulary gate
  and generator on the Deprecated table.
- **Could a user author this?** Yes: a writer's prompt calls `use()` without `auto_lore()` for
  a pick-only chat, and the deprecation tells them about the rename where they type.

## Slices

1. **S1 — the slot and the pick-only send.** §7.1: the slot, the declared-only mode in the
   selector, the three flag reads in the send, the preview's mirror, the snippet. Closes
   #2143. Amends ADR-0086 §1 and ADR-0067 Amendment 2 by reference.
2. **S2 — the name.** §7.2: `auto_lore()`, the alias and its notice, the Deprecated table and
   the gate, the generated artifacts, the built-ins and the docs.

The two are one lane; S1 first, because S2's notice text names a call whose meaning S1 fixes.
#2148 (the writer-facing guide with diagrams) follows acceptance of this ADR and derives from
it.

## The journey that defines done

> **Qualified by Amendment 1 (draft):** in steps 1 and 5, the project's *always* entries are
> placed beside the pick unless the prompt calls `no_lore()`; Amendment 1 has its own journey.

1. The writer presses Propose on The Implant's review item. A conversation opens from
   `Follow a change`, the composer holding the source before and after as today. The Context
   door shows one tier row: The Implant, volatile on the first turn, with no "lore-enabled"
   annotation.
2. The writer sends. The meta line shows the lore fit and no "left out" segment, because
   nothing was; the journal stays empty, because no detection ran. The model names the difference and quotes the one
   sentence in The Implant that must change.
3. In the writer's own prompt, `use_lore()` still works; the meta line says it is now
   `auto_lore()` on every turn until the writer renames it, and the editor's completion
   offers only the new name.
4. A brainstorm from `Revise entry` behaves as today: `auto_lore()` sets the slot, the scene's
   references, the *always* entries and the detections arrive within the budget, and the
   door shows why each one is there.
5. A prompt that calls `use(inputs.picks)` and nothing else gets exactly its picks, minus any
   `never` entry, whatever the assistant's reach and budget say — on every turn and on the
   commit.

## History

Written after ADR-0091's first live run, where a built-in designed to check one entry was
given seven, and the fix the issue named — dropping `use_lore()` — turned out to change
nothing, because `use()` set the same slot. Anton's recollection of the two calls was the
opposite of the code's, and the code's own comments had it right in five places and nowhere
a reader would look first. Two cold implementing threads planned the first draft's slices:
the first found that the commit turn keys on the flag and that ADR-0086 counts the scene's
references as declared; the second found twenty-three open points in a snapshot-placement
decision, three of them on false premises. §7 was narrowed to what the facts force and §8
keeps the rest as constraints. ADR-0075 is the precedent for what this document is: a
gathering, a bounded forward step, and a place a cold thread can start from.

## Amendment 1 — *always* entries travel without automatic lore; a prompt can say it is lore-free

- **Status:** Draft — awaiting review (2026-10-01). Issue: #2393.
- **Supersedes by reference:** ADR-0057 §2 Journey C ("the prompt that must stay clean") and
  that ADR's rejected alternative "Backend force-attaches `always` on every send". A lore-free
  prompt stays possible, but it is declared, not inferred from what the prompt leaves out.
- **Verified against `12a9168c` (2026-10-01, master after `v0.9.6`).** Symbols first, line
  numbers second.

### What prompted it

A writer keeps an entry called *Narration Conventions* — sentence and paragraph structure, how
to handle interiority — with its context policy set to *always*. It is an instruction, not
world lore, and the prompts that write or revise prose need it most. Opening `Revise plot
card`, the Context door shows the system block and nothing else. That is correct under §7.1:
*always* entries are placed only when a prompt calls `auto_lore()`, and among the built-ins
only `Revise entry` and `Roleplay` do. The field's own description says *"'always' (every
request)"* (the `context_policy` field in `backend/app/services/project/default_schema.py`).

A second gap sits on the inline surfaces (Tighten grammar, Expand, Describe, Rephrase,
Show don't tell, Roleplay, Finalize roleplay). They run one-shot through
`POST /api/ai/generate/stream`, which builds the request from the rendered system prompt alone
(`system_prompt_cache_blocks`, `backend/app/routers/ai.py:704`; the non-streaming
`/api/ai/generate` at `:481` does the same and has no frontend caller). No lore is placed on
that path. `build_preview` computes the `send_lore_*` tiers when a template asks for lore, and
the routes discard them. So a pick made in the "Relevant lore" box of Expand, Describe or
Show don't tell never reaches the model, and `Roleplay`'s `auto_lore()` does nothing there.

The same complaint, *always* notes not reaching the model, is what ADR-0057 was written for.
It fixed the gate and set Journey C beside it: a prompt that does not ask for lore gets none,
so a pure style pass sees only what its author put in front of it. A style pass is where the
writer now needs the conventions. The two declarations conflict, one on the entry and one on
the prompt, and this amendment decides which wins by default and how the other says so.

### Why §7.1's rejection does not hold for *always* entries

§7.1 rejected keeping *always* entries on a pick-only send because they are automatic lore
"by any writer's reading — the app added them". That holds for the scene's references: the app
followed a field the author filled for another purpose. It does not hold for *always*
entries. The author set the policy on the entry, which is the most direct declaration the app
has.

The failure §6 records came from entries the author never asked for: what detection noticed
and what the one-hop expansion reached from it. Placing an entry is bounded by what the author
marked. Expanding from it is not, and that is where the seven entries came from. This
amendment separates the two. *Always* entries are placed without automatic lore, and they
seed the expansion only when automatic lore runs.

### Decision

1. **The selector's declared-only mode includes the *always* entries.** `_select_lore` with
   `automatic=False` (`lore_selection.py`) returns the picks and the *always* entries, minus
   `never`, with inferred empty. It reads both sets from the one `_lore_policy_ids` scan it
   already makes (today it reads only `never`, through `_never_lore_ids`, which delegates to
   that scan). No detection and no expansion run. The automatic mode is unchanged.
   `_never_lore_ids` stays, because the commit turn's `used` mode reads it.
2. **Ordinary chat turns place them** (`lore_mode == "implicit"`,
   `expand_and_prepare_chat_blocks` in `chat.py`). Today a turn with automatic lore off and no
   picks skips lore entirely (no scene read, no selection). It now takes the declared-only
   path whenever the project has an *always* entry and the chat is not lore-free.
   - To decide that before the scene read, the send makes the policy scan once, at the top,
     and passes the result down through `_lore_cache_blocks` and `_budgeted_lore_tiers` to
     `_select_lore`, so the turn reads the policies once on this path.
   - With nothing to place (no *always* entry, no picks, automatic lore off) the turn still
     skips lore, and `lore_fit` stays `None`. The models document `None` as "not lore-enabled".
   - The chat's scene is resolved for such a turn as it is for picks, so the entries render
     as of the chat's scene.
   - Automatic turns are unchanged. Their policies are still read more than once, because the
     name matcher makes its own scan.
3. **`no_lore()` declares a prompt lore-free.**
   - **Setting it.** It is a new prompt word that sets a render slot, as `auto_lore()` sets
     `lore_invoked`.
   - **Who wins.** The contradiction is settled at the source, when the preview reads the
     slots back after the render (`_annotate_rendered_from_env`, `preview.py`). If both calls
     ran, `lore_invoked` is cleared, so `lore_enabled` is captured false. `no_lore()` wins
     because lore-free is the safe reading of a contradiction, and a research prompt must not
     leak.
   - **The warning.** One entry is added to `warnings`: "`no_lore()` and `auto_lore()` are
     both called; this prompt is lore-free". The render cannot know which call came first, so
     the warning is added after it.
   - **Where it lives.** The value travels as `lore_free` on the preview response, is captured
     by the lock render and the estimate beside `lore_enabled`, and is persisted on the chat
     as a new optional field (absent meaning false).
   - **What it does on a send.** A lore-free chat gets no *always* entries. The send also
     treats a stored `lore_enabled` as off when `lore_free` is set, so a chat persisted
     inconsistently cannot leak.
   - **Picks still work.** A pick the prompt makes itself with `use()` is still placed,
     because the prompt asked for that entry by name.
4. **The commit turn is unchanged:** picks only (`lore_mode == "used"`, ADR-0067 Amendment 2,
   including the extraction retry). It transcribes a conversation that already carried the
   standing entries, so placing them again is noise on the turn that must read the draft.
5. **One-shot runs place declared lore only: the picks and the *always* entries.**
   - **No automatic lore.** It belongs to a conversation, which has a journal to detect into
     and a session to cache against; a one-shot has neither.
   - **A flag on the request.** `build_preview` today computes full automatic tiers for a
     template that calls `auto_lore()`. So the generate routes ask for declared-only tiers
     through a new `PreviewRequest` field, and send those tiers after the system block
     instead of discarding them.
   - **What changes per prompt.** A one-shot from a `no_lore()` prompt places its picks only.
     `Roleplay`'s `auto_lore()` stays inert on this path, as it is today, and the detection
     work the routes now compute and throw away for it stops.
   - **No lore limits needed.** Declared lore is never budgeted, so the generate routes need
     none.
   - **Finalize roleplay** carries the *always* entries. It writes the scene's prose, which is
     what *Narration Conventions* is for.
6. **The chat preview mirrors the chat send.**
   - **When tiers appear.** The preview computes tiers when the template invoked automatic
     lore or placed picks (`_annotate_rendered_from_env`, `preview.py`). That condition gains
     "or the project has an *always* entry and the prompt is not lore-free", decided from one
     policy scan passed down as on the send.
   - **The response.** It carries `lore_free` beside `lore_enabled`.
   - **The Context door.** Tier rows present with the "lore-enabled" annotation absent now
     reads "picks or *always* entries placed, automatic lore off". A lore-free chat shows a
     "lore-free" annotation.
   - **Over budget.** If the *always* entries alone exceed a non-zero budget, the door and the
     meta line show the existing "declared lore … over the budget" line (ADR-0086 §5). That is
     correct, though new on prompts that never mentioned lore.
7. **The policy's description says what happens:** *always* entries are sent with every
   prompt unless the prompt is lore-free, and the step that saves a chat's result carries only
   what the chat picked.

### Where it does not reach, and why

- **Chats without a prompt** (freeform, from the Chats pane) are unchanged and place no lore.
  The Context door's estimate needs a prompt to render (`chatEstimate.svelte.ts` returns early
  without one), so placing entries there would send what the door cannot show. They are a
  separate decision, and Decision 7's wording is about prompts.
- **A chat request with no stored chat** (the legacy path in `expand_and_prepare_chat_blocks`)
  places no lore today and is unchanged.
- **The roleplay family** (`Roleplay`, `Impersonate`, `Finalize roleplay`) is not redesigned
  here; that redesign is pending. They get the *always* entries like any prompt. Two effects
  are known and left to it:
  - `Impersonate` renders its character inline as of a hidden `as_of` input rather than
    picking it (`impersonate.md`). If that character is itself *always*, the lore block also
    carries it at book start, two states of one character.
  - The prompt-invocation dialog's estimate for `Roleplay` keeps showing automatic tiers the
    one-shot run does not send. Today it shows them and nothing is sent at all.

### Anti-goals

- **Not the scene's references.** They stay automatic-only, as §7.1 says.
- **Not expansion or detection without `auto_lore()`.** An *always* entry seeds the one-hop
  expansion only on a send where automatic lore runs.
- **Not automatic lore on one-shot runs.**
- **Not a budget on *always* entries.** They remain declared: never dropped and never counted
  (ADR-0086 §1).
- **Not a second policy value, and not a per-entry exception.** Whether an entry is wanted
  depends on the prompt, so the prompt says so (`no_lore()`), not the entry.
- **Not world lore for Expand and Describe.** Whether those prompts should also get the lore
  they *name* is a separate decision.

### Costs, accepted

- **Focused prompts carry them too.** `Follow a change`, built to check one entry, will place
  the *always* entries beside it. An author who marks world entries such as characters as
  *always* will see them in that check: the shape of §6, but caused by the author's own
  declaration and shown in the Context door. The label promises it, and a prompt that must
  stay focused can call `no_lore()`.
- **A policy scan where none runs today.** `_lore_policy_ids` goes through
  `list_lore_entries`, which reads each lore file whole (body included) and is not cached. It
  now runs on several paths, in projects with no *always* entry too:
  - chat turns with automatic lore off;
  - one-shot runs;
  - every chat preview render: the prompt editor's live preview, each estimate refetch, and
    the lock render.

  If it shows on a large project, how to make it cheaper is a separate decision.
- **Chats already locked change from their next turn.**
  - A chat locked before this change has no `lore_free` field. It reads as not lore-free and
    starts receiving the *always* entries. No migration; Clear relocks.
  - Likewise, the estimate re-renders the live prompt. A locked chat whose prompt has since
    gained `no_lore()` shows "lore-free" in the door while its send still places the *always*
    entries, until it is cleared and relocked. This mirrors §7.1's last bullet.

### Rejected

- **A second policy value** ("Every prompt" beside "Always, with automatic lore"). It gives the
  writer two near-identical options to tell apart, and it puts on the entry a choice that
  depends on the prompt.
- **A snippet each built-in includes to place the *always* entries.** Every writer's own
  prompt that does not include it would still drop them, and the label would still be wrong.
  ADR-0057 rejected "add the call to each template" for the same reason.
- **Opt-in instead of opt-out** (*always* entries only on prompts that ask). That is today's
  behaviour with a new word, and the default would still contradict the label.
- **Skip an *always* entry that is the chat's subject.** It would stop `Impersonate`'s
  duplicate only when the chat was launched from that character. The character is a prompt
  input, not the subject, so the rule misfires for other launches. In automatic mode it would
  also remove the subject from the expansion's seeds. It is a special case standing in for
  "an entry the prompt renders itself", which the app cannot see.
- **Automatic lore on one-shot runs.** It would turn `Roleplay`'s inert `auto_lore()` into
  detection and expansion on every beat, uncached, which is the §6 failure at a higher rate.
- **Fix only the description.** Honest, but it leaves *Narration Conventions* unable to reach
  an inline prompt at all, and a chat prompt only by turning on automatic lore, the one thing
  this ADR set out to make unnecessary.

### Consequences

- **Storage:** one new optional field on the chat, `lore_free`. Absent reads as false, which
  is the behaviour Decision 2 defines, so no migration.
- **API / wire:**
  - Chat turns and one-shot runs carry declared lore tiers when there is something declared to
    place.
  - `PreviewRequest` gains the declared-only field the generate routes set.
  - The preview response (`AIPreviewResponse`, `RenderedTemplate`) gains `lore_free`, and its
    `cache_blocks` and `estimated_tokens` include the *always* entries.
  - `SaveChatSessionRequest` gains `lore_free`. `None` means preserve, as for `lore_enabled`.
- **Prompt vocabulary:**
  - `no_lore()` is added to the Helpers table in `docs/prompts/reference.md`.
  - The generated manifest and guides bundle are regenerated.
- **Frontend.** `lore_free` follows every step `lore_enabled` takes:
  - the lock render's capture (`promptTemplateLock.ts`);
  - the estimate's capture (`chatEstimate.svelte.ts`);
  - and in `ChatBodyView.svelte` its state, the reset when the chat changes, the hydrate from
    the stored chat, the save, and the lock.

  A save always sends the hydrated value, so a missed hydrate would reset a lore-free chat on
  its first save. The Context door gets it as a prop through the composer bar, for the
  "lore-free" annotation and the tooltip on tier rows.
- **Docs and comments that state the old rule:**
  - `docs/ai-context.md`: the picks-only sentences, "calls neither sends no lore at all", and
    the *Always include* line.
  - The `context_policy` field's description and its comment in `default_schema.py`.
  - Docstrings: `expand_and_prepare_chat_blocks`, `PreparedChatTurn`, `_lore_cache_blocks`,
    `_select_lore`, `_budgeted_lore_tiers`, `_preview_lore_tiers` and
    `_annotate_rendered_from_env`.
  - The comment on `ChatSession.lore_enabled` in `backend/app/models/ai.py`, which cites
    Journey C.
- **Tests:**
  - **Invert:**
    - `test_lore_cache_blocks.py::test_gate_off_places_no_lore`: its fixture's *always* entry,
      Premise, is now placed.
    - `test_a_pick_only_chat_places_its_picks_with_the_flag_off`: still excludes the scene
      mention and the structural reference, but now includes Premise.
  - **Stay:**
    - `test_the_commit_turn_keys_on_picks_not_the_flag`;
    - `test_used_mode_sends_only_the_chats_own_picks_and_leaves_the_chat_as_found`;
    - `test_lore_gate.py::test_lore_invoked_false_when_helper_absent`.
  - **Comments or docstrings that cite Journey C or "lore-free", updated:**
    - `test_lore_gate.py`;
    - `test_ai_preview.py::test_preview_reports_lore_disabled_when_helper_absent`;
    - `test_ai_chat.py::test_lore_gate_off_injects_no_lore` (its fixture has no *always* entry);
    - the "stays lore-free" wording in `test_builtin_library.py`, now that "lore-free" means
      `no_lore()`.
  - **New:**
    - `no_lore()` sets `lore_free`, clears `lore_invoked` with one warning when both are
      called, and still places a `use()` pick;
    - a lore-free chat places no *always* entry;
    - a chat stored with both flags set sends no automatic lore;
    - a turn with nothing declared keeps `lore_fit` `None`;
    - a one-shot generate places an *always* entry on the wire, per provider, beside
      `test_provider_system_blocks_reach_wire.py`, and places no automatic lore from a
      template that calls `auto_lore()`;
    - the chat preview of a prompt with neither call shows the *always* entry's tier row;
    - `ChatBodyView` hydrates `lore_free`, so a reopened lore-free chat saves it back.

### Slices

1. **S1 — chats and the preview.** Decision items 1, 2, 3, 4, 6 and 7, with the docs and tests
   above.
2. **S2 — one-shot runs.** Decision item 5.

They are one lane, S1 first, because S2 sends the declared tiers whose contents S1 defines.

### The journey that defines done

1. The writer sets *Narration Conventions* to *Always include* and opens `Revise plot card` on
   a card not yet in a scene. The Context door shows System and one lore row listing
   *Narration Conventions*, with no "lore-enabled" annotation.
2. The writer sends. No "left out" segment appears on the meta line, and the journal stays
   empty because no detection ran.
3. The writer commits the card. The commit turn carries no lore, since the chat made no picks.
4. In the editor, the writer selects a paragraph and runs Tighten grammar. The request carries
   *Narration Conventions* and no other lore, checked on the outgoing request.
5. The writer authors a research prompt that calls `no_lore()` and opens a chat from it. The
   Context door shows System alone with a "lore-free" annotation, and the send carries no
   lore. The writer closes and reopens the chat, sends again, and it is still lore-free.
6. A `Revise entry` brainstorm behaves as it did before this amendment.
7. The writer sets *Narration Conventions* back to *auto*. None of steps 1–4 carry it unless a
   prompt with `auto_lore()` detects it.
