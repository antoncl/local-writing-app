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

1. The writer presses Propose on The Implant's review item. A conversation opens from
   `Follow a change`, the composer holding the source before and after as today. The Context
   door shows one tier row: The Implant, volatile on the first turn, with no "lore-enabled"
   annotation.
2. The writer sends. The meta line shows the lore fit with nothing left out; the journal stays
   empty, because no detection ran. The model names the difference and quotes the one
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
