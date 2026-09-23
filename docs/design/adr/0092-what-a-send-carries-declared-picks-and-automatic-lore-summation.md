# ADR-0092: What a send carries — declared picks, automatic lore, and the three words a prompt has for them (a summation)

- **Status:** Proposed — 2026-09-23; text by Claude from a fact-finding pass with Anton on the
  first live run of ADR-0091. **A summation, qualified by §7.** §§1–6 decide nothing new: they
  gather, into one document, what the send path does today with the lore a prompt names and
  the lore the app finds on its own — decisions that live across ADR-0057, ADR-0060, ADR-0075,
  ADR-0084 and ADR-0086 and had no single home, so "does `use()` turn on automatic lore?" had
  no answer a reader could find, and a built-in was written on the wrong answer. §7 makes three
  decisions the facts forced: the automatic gate opens only on the call that asks for it, that
  call is renamed for what it does, and a prompt can place a snapshot of an entry beside the
  live one. Acceptance alone starts nothing; each slice gets its own issue and an explicit go.
- **Consolidates:** ADR-0057 (the one gate, the one selector), ADR-0060 §2/§5 (`use()`, the
  volatility hint, the retired emitting `relevant_lore()`), ADR-0075 (detection surfaces and
  the matcher), ADR-0084 (cache strategy per model), ADR-0086 and its Amendment 1 (declared
  versus inferred, the budget, reach, the fit order, the journal's identity), ADR-0091 §4 (the
  Propose message). Relates: ADR-0049 (built-ins are Library files), ADR-0087/0088 (snapshots
  and compare mode), #2143 (the finding that prompted this), #2142 and #2147 (two surface
  defects fixed on the way, recorded here as rules), #2148 (the writer-facing guide, after
  this).
- **Words used here.** A *pick* is an entry a prompt names with `use()`. *Automatic lore* is
  what the app adds on its own once a prompt asks for it. *Declared* and *inferred* are
  ADR-0086's two halves of one send: declared is never dropped, inferred fits a budget. The
  *gate* is the per-chat flag that lets automatic lore run. A *surface* is a text the name
  matcher scans. The *journal* is the chat's append-only record of what automatic detection
  noticed and why. A *block* is one placed, cacheable unit of context on the wire.
- **Verified against `cd000dd7` (2026-09-23).** Symbols first, line numbers second.

## 1 — A send carries two halves of lore, and one flag decides whether the second runs

Every chat turn that reaches a model carries, besides the system prompt and the transcript, a
set of lore entries the backend selects, deduplicates by id, renders as XML and places in
cache-tiered blocks (`_lore_cache_blocks`, `backend/app/services/ai/chat.py`). ADR-0086 split
that set in two:

- **Declared** — the chat's `use()` picks, the anchored scene's own reference fields, and every
  entry whose context policy is *always*. Never dropped, never counted against the budget.
- **Inferred** — what automatic detection and expansion found (§3), fitted to the assistant's
  budget in the fit order of §4. This is the half a writer means by "the AI pulled that in".

One flag on the chat, `lore_enabled`, decides whether the inferred half runs at all
(`chat.py`, the `lore_enabled and lore_mode == "implicit"` branches). It is captured at the
prompt's lock render from a slot the template sets (`helpers.py`, `lore_invoked`): the flag
is on if the template called `use_lore()` — **or `use()`**. That second clause is ADR-0060 §2's
"using a node means the chat is lore-enabled", and it is the fact §7 changes: today no prompt
can place a pick without also opening automatic selection, which is how ADR-0091's built-in,
meant to check one entry against a change, was handed seven.

## 2 — The three words a prompt has, and what none of them does

- **`use(node)`, `use(node, "stable" | "volatile")`** (ADR-0060 §2/§5, `helpers._use`): "also
  include this node." Emits nothing; records the resolved id (every id, for a multi-pick
  input) on the chat as `used_node_ids`, and the optional hint as `used_node_hints`. The pick is
  declared. The hint is a prior on which cache tier the block starts in and never overrides the
  per-revision check (§5). Picks are exact: they are not seeds for expansion (§3); an author who
  wants a pick's neighbours loops its refs and picks them.
- **`use_lore()`** (ADR-0057 §2, `helpers._use_lore`): the gate-only declaration. Emits
  nothing; opens the flag of §1. It replaced an emitting `relevant_lore()` whose output would
  have been frozen into the prompt and double-counted against the placed blocks. Its name
  reads as a sibling of `use()` and says nothing about *automatic*; §7 renames it.
- **`entry(x)`, `original(x)`** and the rest of the vocabulary (`docs/prompts/reference.md`)
  render values into the prompt text; they place nothing and open nothing. `entry(x)` is the
  node as of the prompt's scene, `original(x)` the node at book start. **Nothing reaches a
  snapshot** (ADR-0087's store): a prompt cannot render or place an entry as it was at a
  captured moment. That is why ADR-0091 §4's Propose message carries the source's before and
  after as text in the first user turn — two full renders in the one place that is never
  cached — and why the matcher then journals every entry that text names.
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
  dedupe against detections by id (`chat.py`, `_budgeted_lore_tiers`); an id reachable both ways
  is declared. Every entry renders once, as the XML `_render_lore_entries` produces.
- **Two tiers per turn** (`_tier_lore_ids`): unchanged since the session baseline → stable,
  new or changed → volatile. The `use()` hint biases the start — "volatile" pins; "stable"
  holds unless the entry actually changed — and never rides stale bytes. Stable blocks are
  placed first; the provider profile assigns each tier its TTL and caps breakpoints
  (ADR-0084).
- **The journal is append-only across the session**, so the cache breakpoint after it can
  ratchet forward as it grows (`ChatSessionJournalEntry`, `backend/app/models/ai.py`). Its
  identity is `(entry_id, source)`, not `entry_id`: a later, better-ranked mention of an
  already-journaled id appends a second entry, and the selector keeps the best-ranked
  candidate per id (ADR-0086 Amendment 1). Title and type are snapshotted at detection so the
  door keeps showing what the writer saw.

## 6 — The case that exposed the gap

ADR-0091's built-in `Follow a change` opens a conversation on a dependent with the source's
before and after in the first message, and its job is to check that one entry. Its template
placed the dependent with `use(e)`; that opened the gate; the message named the source and
the entries the source names; detection journaled them; depth-one expansion added their
neighbours; seven entries stood beside the one the role named, and two models of different
sizes reviewed all seven. Dropping `use_lore()` from the template changed nothing, because
`use()` had opened the gate already (#2143). Two levers exist today, both on the assistant: a
budget of `0`, or "Named only". Neither is where a prompt author would look, and neither
should be needed to say "just this entry".

## 7 — Decisions

1. **`use()` places; it does not open the gate.** The `lore_invoked` slot is set by the
   automatic-lore call alone. A pick is placed whenever the chat has `used_node_ids`, gate or
   no gate: the declared half of a send no longer depends on `lore_enabled`, which comes to
   mean exactly "automatic lore is on". A prompt that calls only `use()` gets its picks and
   nothing else; one that calls both gets what it gets today. The scene's own references and
   *always* entries stay with the automatic half, where ADR-0086 put them. ADR-0060 §2's
   "using a node means the chat is lore-enabled" is withdrawn.
2. **`use_lore()` becomes `auto_lore()`.** The name says what the call does. The old name
   stays as an alias for a deprecation period: rendering a template that calls `use_lore()`
   still opens the gate and adds a `warnings` entry the preview strip and the inputs dialog
   already show ("`use_lore()` is now `auto_lore()`; the old name is removed in 1.0"). The
   alias is removed at 1.0. The built-ins switch to the new name; a writer's own prompts
   keep working and are told. The vocabulary reference (`docs/prompts/reference.md`, the
   gate-enforced surface) lists `auto_lore()` and marks `use_lore()` deprecated; no storage
   changes, so no migration.
3. **A prompt can place an entry as it was at a snapshot.** `use(node, snapshot=id)` places
   the entry's state at that ADR-0087 snapshot as its **own block, keyed `(entry_id,
   snapshot_id)`**, rendered by the same lore XML with a `snapshot` attribute and the capture
   time, and it never dedupes into the live entry's block: the one-per-id rule of §5 is per
   key, and the live entry keeps the plain key. Anton's catch: keyed by id alone, the two
   would collapse to one. A snapshot block is stable by construction (its bytes cannot
   change) and is placed in the stable tier regardless of hint. `entry(x, snapshot=id)` is the
   rendering twin, for a template that wants the value in text. Under it, ADR-0091 §4's
   message shrinks to the question, the source's before and after ride as two cached blocks,
   and the matcher no longer journals what the message used to name. The Propose flow gains a
   hidden `baseline` input the review item seeds from its `source.snapshot_id`, the way it
   seeds `entry_type`; the built-in reads it. Read-only against the store; a missing
   snapshot renders nothing and adds a warning.

## Anti-goals

- **Not a change to detection.** The surfaces, the matcher and the parity gate are ADR-0075's
  and stay; §3 records them.
- **Not reach or budget on the prompt.** The assistant remains the one place (ADR-0086); a
  prompt gets "declared only" by not calling `auto_lore()`, which is a different thing from a
  budget of zero and needs no setting.
- **Not retrieval.** A better selector is a later decision, as ADR-0086 said.
- **Not a new surface for the writer.** The Context door, the meta line and the preview strip
  already show what was placed and why; the rename shows there as a warning.
- **Not a fold snapshot or a new store.** §7.3 reads ADR-0087's store as it is.

## Why / rejected alternatives

- **Keep `use()` opening the gate and fix the built-in with wording.** Rejected by use: two
  models ignored a scope sentence in favour of the seven entries in front of them. What a
  model is given decides more than what it is told.
- **A per-call reach on `use()`.** Rejected: it would reopen ADR-0086's one-place rule, and it
  cannot address the case anyway, since the entries arrived through the gate, not through
  the pick's neighbours.
- **A prompt-level "declared only" switch.** Rejected as redundant once §7.1 holds: not
  calling `auto_lore()` is the switch, and it is the one a prompt author already understands.
- **Rename without a deprecation period.** Rejected: writers' own prompts are files in their
  projects; a silent break is the worst outcome and a warning costs nothing.
- **Snapshot placement keyed by entry id.** Rejected, per §7.3: it would dedupe the before
  into the after.

## Consequences

- **Storage:** none. `lore_enabled`'s meaning narrows to "automatic lore is on"; a chat
  persisted with it on keeps behaving. No new fields; no migration.
- **API / wire:** the preview response's `lore_enabled` follows the narrowed meaning;
  `lore_fit` unchanged; snapshot blocks appear in the Context door like any placed block, with
  their snapshot named.
- **Prompt vocabulary:** `auto_lore()` added, `use_lore()` deprecated (alias + warning),
  `use(node, snapshot=)` and `entry(x, snapshot=)` added; the reference and the completion
  derive from it as ADR-0060 set up.
- **Built-ins:** every built-in that calls `use_lore()` switches to `auto_lore()`;
  `Follow a change` adopts §7.3 with a hidden `baseline` input.
- **Tests:** the gate slot set by `auto_lore()` and not by `use()`; a `use()`-only chat places
  its picks with the gate off; the alias opens the gate and emits the warning; the built-in
  contract tests follow the rename; a snapshot block keyed apart from its live entry, placed
  stable, absent snapshot → warning; the Propose message under §7.3 carries the question
  only; the wire test that system blocks reach the provider (the ADR-0075 lesson) extended to
  the snapshot block.
- **Could a user author this?** Yes, all three: a writer's prompt calls `use()` without
  `auto_lore()` for a pick-only chat, and `use(x, snapshot=…)` from any snapshot the foot dock
  shows.

## Slices

1. **S1 — the gate and the name.** §7.1 and §7.2 together: the slot, the send path's declared
   placement without the gate, the alias and warning, the reference, the built-ins. Backend
   with the preview and send tests; the frontend only where a lock-render field is read.
2. **S2 — the snapshot block.** §7.3: the two vocabulary additions, the keyed block, the
   stable placement, the Context door naming the snapshot, `Follow a change` and the Propose
   flow's hidden `baseline` input, the Propose message reduced to the question.

S1 is useful alone and closes #2143. #2148 (the writer-facing guide with diagrams) follows
acceptance of this ADR and derives from it.

## The journey that defines done

1. The writer presses Propose on The Implant's review item. A conversation opens from
   `Follow a change`; the composer holds one sentence: "Origin changed since the last
   propagation; what here needs to follow?" The Context door shows three blocks: The Implant
   (live), Origin (live), Origin at the propagation baseline of Monday, named as such.
2. The writer sends. The meta line reads three entries, none left out; the journal is empty,
   because the message named nothing. The model names the difference between the two Origin
   blocks and quotes the one sentence in The Implant that must change.
3. In the writer's own prompt, `use_lore()` still works; the preview strip says it is now
   `auto_lore()`. The writer renames it when convenient.
4. A brainstorm from `Revise entry` behaves as today: `auto_lore()` opens the gate, the scene's
   references, the *always* entries and the detections arrive within the budget, and the
   door shows why each one is there.
5. A prompt that calls `use(inputs.picks)` and nothing else gets exactly its picks, whatever
   the assistant's reach and budget say.

## History

Written after ADR-0091's first live run, where a built-in designed to check one entry was
given seven, and the fix the issue named — dropping `use_lore()` — turned out to change
nothing, because `use()` opened the same gate. Anton's recollection of the two calls was the
opposite of the code's, and the code's own comments had it right in five places and nowhere
a reader would look first. ADR-0075 is the precedent for what this document is: a gathering,
one bounded forward step, and a place a cold thread can start from.
