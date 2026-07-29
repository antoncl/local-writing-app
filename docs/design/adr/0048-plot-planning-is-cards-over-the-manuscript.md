# ADR-0048: Plot planning is a board of card nodes over the manuscript, written through reviewable patches

- Status: **Accepted** — 2026-07-29 (Anton, PR #659).
  Prepared from the evaluation of the `plotting` branch and the architecture comparison against
  ADR-0046, both reviewed by Anton in session. Three of his review decisions are folded in as
  settled: the card↔scene cardinality (§1), the **board is a singleton in v1** (§3), and the
  ordered-list field type **holds groups** and is **gated on UX mockups** when its phase starts
  (§6, S2).
- Feature: unfiled — issues to be filed per slice on approval (§8). This ADR is the architecture and
  the plan of record those issues share.
- Follows: **ADR-0046** (the propose → review → adopt → commit loop this ADR generalizes; its
  amendment history and anti-goals apply here unless §5 says otherwise), ADR-0047 (feature
  invocation: app menu + contextual actions), the class–instance model (`kind:entry_type` → fields),
  ADR-0042 (layered schema — plot fields are ordinary layered definitions).
- Reference implementation: branch **`origin/plotting` @ `6e588af`** (2026-07-28). It is treated as
  a quarry, not a base: proven content and algorithms are ported from it (§9), its write mechanism
  and interior data model are not. It forked at #500, one commit before master's #501 revert removed
  the `plotting:*` taxonomy; that taxonomy stays dead (§Anti-goals).

> **Code references.** This ADR describes roles and behaviours, not call sites. Claims about
> *current* behaviour were verified against master **`f1ef558`** (2026-07-29) and the branch commit
> above, and are true of those trees only. A reader arriving later should re-verify before acting,
> and should treat a disagreement with the code as evidence the ADR aged, not that the code is wrong.

## Context

The goal, unchanged since the branch was started: a planning surface in the spirit of Plottr and
Scrivener's corkboard, adapted to this app — local-first, file-based — with an AI partner that can
*reason about the proposed plot* and give qualified feedback, not just generate text.

The `plotting` branch proves the goal is reachable and settles several questions for good: structure
templates work best as **diagnostic lenses** (questions a draft must answer), not fill-in-the-slots
forms; the AI needs a **semantic packet** of the plan (never canvas coordinates), **spoiler-scoped**
to a point in the story, with the author able to preview exactly what the model sees; and a chat that
proposes concrete, applicable changes is the interaction writers actually want.

The same evaluation found the branch un-mergeable as built, for reasons that are architectural, not
cosmetic. Its cards, claims, plotlines, and relationships live inside one board document, invisible
to the node index, the reference graph, and the schema — so the branch re-implements integrity,
reverse lookup, and AI apply logic that the app already owns for nodes. Its AI write path — a
machine-readable block embedded in the visible chat reply, regex-parsed, applied by a row of
per-suggestion buttons — solves the same problem ADR-0046 has since solved better: one validated
patch, staged review, per-field adoption, a single write. And it still carries the pre-revert
`plotting:*` types plus pre-1.0 compatibility shims this repo forbids.

Meanwhile ADR-0046 shipped for lore. Its loop — an ideation chat that commits a whole-entry patch,
validated per field against the schema, reviewed frozen, adopted per field, written once — is
node-shaped, not lore-shaped: nearly all of it parameterizes to any schema-typed node.

One genuine gap in the platform surfaced during planning: the metadata field catalog has **no
ordered-list type**. A plot claim ("this card performs *this beat*, this strongly, because…") is a
small record, and a card carries several in a meaningful order. That missing primitive is a
prerequisite (§6), not a plot-local hack.

## Goals

What a writer can do when this is done — each one is a promise the implementation must keep:

1. **Plan on a board of cards** — before writing, while writing, or thirty scenes in. A board over
   an existing draft starts populated from the book, not blank.
2. **Plan what never gets written.** Backstory, off-page events, and material for later books are
   cards that need no scene — the plan is allowed to know more than the manuscript shows.
3. **Let one scene carry many beats.** Several cards can point at the same scene; a climax that
   pays off three threads is three cards, one scene.
4. **Try a story shape on for size.** Templates (three-act, hero's journey, mystery fair-play, …)
   are lenses that ask whether the draft answers their questions — never forms demanding to be
   filled in.
5. **Track your own threads.** Plotlines are created ad hoc, named and colored by the writer, and
   visible at a glance on the board.
6. **Brainstorm with an AI that has actually read the plan** — scoped so it cannot spoil the story
   past a chosen point — and receive critique and concrete proposals. Every proposal is reviewed
   and adopted by the writer, change by change; nothing is ever written silently.
7. **Extend it like anything else in the app.** Cards and plotlines are ordinary entries: writers
   can add their own fields, sub-types, and views, and every future app feature that works on
   entries works on them.

## Anti-goals

What this feature must never become — the lines that hold when surprises push:

1. **Scenes never grow planning fields.** The manuscript stays clean; the plan reaches it only
   through attachments. A writer who never opens the board never sees a trace of it.
2. **No second AI write mechanism.** All AI-proposed changes ride the one propose → review → adopt →
   commit loop, app-wide. If plot needs something the loop can't express, the loop is extended —
   never bypassed.
3. **The AI never wires links.** Attaching cards to scenes, and any other cross-reference, is the
   writer's hand. (The one bounded exception is §4's beat claims, and the ADR says exactly why.)
4. **No timeline engine, for now.** Plotline color, tinting, and filtering carry "see the threads";
   a lanes-and-columns grid is a possible future feature, not a debt of this one.
5. **No free-form arrows, for now.** An arrow that carries no meaning is worse than no arrow; edges
   return only when they mean something (as real references with semantics).
6. **Opening a project never writes to it.** Built-in content is seeded when a project is created,
   and by explicit action — never as a side effect of reading.
7. **No parallel taxonomy.** The reverted `plotting:*` types stay dead; the `plot` kind defined
   here is the only home for plot concepts.

## Decision

### 1. A card is a node; a scene may realize zero or many cards

A **card** is a unit of story function — "this happens, and it does this job for the story" — and is
a first-class node (`plot:card`, sub-typeable like any entry type). Its fields: a synopsis, a primary
plotline (reference), its claims (§4), and an **optional reference to a scene**.

The cardinality is settled: **0..n cards per scene, 0..1 scene per card.** A card without a scene is
backstory or not-yet-written material. Several cards on one scene are several beats realized in one
stretch of prose. Attachment is always the writer's act (anti-goal 3): *realize* creates a scene from
a card and attaches it; *attach* binds a card to an existing scene via a picker.

Because cards are nodes, everything the app owns applies for free: identity, atomic writes, the node
index and reference graph (a deleted scene visibly dangles its cards' attachments), layered schema
extension, search, and the AI patch loop (§5).

### 2. A plotline is an entry the writer creates at will

`plot:plotline`: a name, a color, a description. Writers create them ad hoc; cards reference one as
their primary plotline. The board renders the color as chips and card tints, with a
highlight-by-plotline filter. Because a plotline is an ordinary typed entry, the AI can draft one
through the existing new-entry branch of the patch loop with zero new machinery — "brainstorm a
subplot for the sister" is the same flow as brainstorming a new character.

### 3. The board itself holds presentation only

`plot:board` is a layout document: card positions, per-column ordering, collapsed groups, viewport.
It owns **no story data**. **In v1 the board is a singleton** — one board per book, opened (or
created on first open) by the single board action; no board management UI. The node model tolerates
more than one, but surfacing that is a future decision, not a v1 obligation. Columns are projected from the manuscript structure (acts/chapters);
dragging a chapter on the board performs a real structure move via the existing mutations; cards
land in columns via their scene's slot, or directly (planned, unwritten), or in a backstory lane
(unattached, unplaced). Templates (`plot:template`) and their per-book instances
(`plot:template_instance`) are nodes, as on the branch, with instance-to-template links as real
reference metadata. Card order within a column lives in the board document as long as it is
presentation; the moment order becomes story-meaningful it moves onto the card (§6 makes that
possible), and that move is an ADR amendment, not a quiet migration.

### 4. Claims are ordered structured field values, validated against a closed roster

A **claim** — "this card *satisfies* / *foreshadows* / *subverts* beat X, this strongly, because…" —
is an item in an ordered-list field on the card (§6). Its beat pointer is validated against the
closed roster of beats from the book's instantiated templates.

This is the one sanctioned carve-out from ADR-0046's "the AI never proposes references" rule, and it
is bounded by what motivated that rule: a wrong open-world entity ref is a *silent* mis-link, but a
beat claim is **closed-world** (the legal targets are enumerable and validated on return) and
**loud** (the adopt flip shows the target beat by name). Claim types start minimal — only the values
the diagnostics and prompts actually exercise — and widen when a workflow demands it, not before.

### 5. One AI write path: the ADR-0046 loop, generalized, plus patch sets

The lore loop's seams are parameterized from "lore" to "any schema-typed node": the brainstorm
store, the proposal controller, the validate endpoint, the launch conventions. Card-level and
beat-level brainstorms are then ordinary instances of the loop — launched from the board with the
target riding in as a hidden input, committed as one validated patch, reviewed frozen with per-field
flips, written once.

Board-level review needs the loop's only genuine extension: the **patch set** — the finalize
contract may return a *list* of (target card → patch) plus new-entry drafts (cards, plotlines),
each element validated exactly as a single patch is, staged as a queue, reviewed target by target
through the existing surfaces, each committing through its own single write. No new diff mechanism,
no new mutation endpoint, no new review UI shape — a plural container around the singular loop.

The read side ports from the branch: the semantic context packet with spoiler gating anchored on a
scene, omission counts, prompt helpers, and the author-visible "what the AI sees" preview — with
scene summaries reaching the packet through attachments, and the manuscript-order walk unified onto
the shared traversal instead of adding another derivation.

### 6. Prerequisite: an ordered-list field type

The metadata catalog gains one type: an **ordered list whose items are records of existing scalar
types** — and an item shape must be able to be a **group**: the schema's existing named field
groups serve as item shapes, so a shape is defined once and reused, not re-declared inline per
list. It gets the full uniform treatment — layered schema merge, validation reusing the per-scalar
validators, one row-based add/remove/reorder widget used identically across default/options/value
surfaces, and AI proposability defined as per-item validation with per-item drops so it slots into
the patch loop with no special casing. Claims are the driving consumer; open-questions lists and
aliases justify it independently of plot.

It lands first because everything downstream leans on it — and **its slice starts with UX
mockups**: the editing widget for an ordered list of records is the least precedented surface in
this plan, so the design is iterated as mockups (per the ADR-0044 precedent) and agreed before the
widget is built. The mockups also settle exactly how groups serve as item shapes. That work waits
until the slice is reached; nothing upstream depends on its answers.

### 7. What is deliberately dropped from the branch

Named here so their absence is legible as decision, not loss: the `<plot_suggestions>` text
protocol, its parser, echo-filter, and apply buttons (superseded by §5); the plot logic embedded in
the shared chat transcript; claim extras with no workflow behind them (`confidence`, free-form
labels, unused type values); free-form relationship edges (anti-goal 5); the `plotting:*` taxonomy
(anti-goal 7); the legacy-shape validators, dual representations, and rewrite-on-open seeding
(anti-goal 6); native browser prompt/confirm dialogs; and the unrelated read-only-prompts rider,
which master has since solved on its own.

### 8. Slicing — the plan of record

Each slice is one PR-sized lane of work, lands green through all gates, and leaves master shippable.
Purpose and "done means" are binding; internal ordering may flex (see *How this plan bends*).

**Phase 0 — this document.**
- **S0. ADR-0048 accepted.** Done means: Anton has approved, open comments resolved, issues filed
  per slice.

**Phase 1 — foundations (each useful on its own).**
- **S1. Gates see `.css`.** The file-size and style-token guards cover `.css` files. Done means: the
  demonstrated blind spot is closed on master before any plot code arrives.
- **S2. Ordered-list field type** (§6). Opens with the UX mockup pass; the widget is built to the
  agreed mockup. Done means: a schema author can define one (including a group as the item shape),
  a writer can edit one, validation and AI proposability work per item, and no existing field
  behaviour changed.
- **S3. The patch loop generalizes** (§5, first half). Done means: lore behaves byte-for-byte as
  before, but the loop's seams take a node kind as a parameter; no plot code yet.

**Phase 2 — the plot data model.**
- **S4. The `plot` kind**: templates, template instances, plotlines, and the layout-only board node;
  the 14 templates and guides ported; seeding on create only. Done means: the nodes exist, are
  indexed, referenced, and schema-extensible, with the branch's behavioral tests ported and passing.
- **S5. Cards** (§1): the `plot:card` type with synopsis, plotline, claims, and scene attachment;
  the *realize* and *attach* operations; **seed-from-manuscript** as an explicit action creating one
  attached card per existing scene. Done means: a mid-draft project reaches a fully populated card
  set in one action; scenes are untouched.
- **S6. The context engine** (§5, read side). Done means: prompts can render the packet, spoiler
  gating is pinned by tests that assert what is *absent*, and the walk is the shared one.

**Phase 3 — the board.**
- **S7. Board canvas MVP**: projection of structure + cards, drag as structure/placement mutations,
  backstory lane, stacked cards per scene. Presentation state in a rune-store controller; styles in
  scoped component blocks; app dialogs, not browser ones. Done means: arranging the plan works
  end-to-end with no AI involved.
- **S8. Templates on the board**: instantiation, per-beat editing, guides. Done means: the branch's
  template journey works on the new model.
- **S9. Plotlines visible**: creation via normal entry surfaces, color chips, tints, filter.
  Done means: goal 5 is observable on the board.
- **S10. Diagnostics**: untagged cards, unsupported claims, unclaimed beats, overload — client-side,
  ported. Done means: the board shows them and they feed S11's launch points.

**Phase 4 — the AI partner.**
- **S11. Single-target brainstorms**: plot prompts join the prompt taxonomy; card/beat/untagged
  launch points open patch-committing chats; claims propose per §4. Done means: a card assist
  round-trips — launch, discuss, commit, review flips, adopt, one write.
- **S12. Patch sets and the board audit** (§5, second half). Done means: a whole-board review lands
  as a reviewable queue of per-card patches and drafts, and goal 6 is fully delivered.

**Phase 5 — close-out.**
- **S13. Retire the branch**; file the deferred futures as issues (meaningful edges, timeline view,
  undo revisited against snapshots). Done means: `origin/plotting` is archived and nothing refers to
  it as pending work.

Sequencing: one work lane, queued behind in-flight ADR-0046/0047 slices. S1 is independent and may
land any time. S2 and S12 are the two substantial builds; S4–S6 are disciplined porting; the rest
are small to medium.

## How this plan bends

A plan this long **will** meet surprises. The rule for absorbing them:

- **Binding:** the Goals, the Anti-goals, and the Decision sections (§1–§7). These say what must be
  true when the feature ships, and what must never become true on the way.
- **Flexible:** the slicing (§8). Slices may split, merge, reorder, or grow intermediate steps
  freely, provided each landed PR keeps master shippable and crosses no anti-goal. Discovering that
  a slice was mis-sized is normal and needs no ceremony beyond saying so in the PR.
- **A surprise that argues against a binding item stops the work.** The move is to amend this ADR —
  with the evidence, before coding around it — never to leave the ADR asserting one architecture
  while the code quietly builds another. The cardinality correction in §1 is the worked example:
  the model bent *before* implementation because the argument was made where the plan lives.
- The salvage manifest (§9) is advisory: if a ported piece fights the new model, rebuilding it is
  always in scope.

## Why / rejected alternatives

- **Cards as scenes** (one node serving both roles) — rejected on three grounds: scenes would gather
  planning fields most never use (violates anti-goal 1); the cardinality is wrong — one scene may
  realize several beats, so card:scene must be n:1, not 1:1; and backstory needs cards with no scene
  at all. The plan and the manuscript are distinct layers with writer-made links between them.
- **Merge the branch, then refactor in place** — rejected: it puts two AI write mechanisms and two
  data models live simultaneously, and history shows in-place refactors under a live feature stall.
  The branch is worth more as a quarry than as a base.
- **Keep the suggestion-block pipeline for plot only** — rejected: it duplicates the 0046 loop with
  weaker validation, machine syntax in human transcripts, and a three-way prose/parser/filter
  contract; maintaining both indefinitely is the worst outcome.
- **Cards inside the board document** (the branch's model) — rejected: an interior invisible to the
  node index and reference graph forces the feature to re-implement integrity, reverse lookup, and
  apply logic the app already owns, and blocks user extension of card fields.
- **Claims as loose text on cards** — rejected: the AI's most valuable act is connecting a card to a
  beat with a stated strength and reason; that connection must be structured enough to validate and
  to flip in review, which is exactly what §4 + §6 provide.

## Consequences

- The `plotting` branch retires. Its templates, guides, context engine, diagnostics, layout math,
  and behavioral tests live on (§9); its write path and interior model do not.
- The platform gains two durable primitives justified beyond plot: the ordered-list field type and
  the patch set. Every future kind gets the propose/review/adopt loop for free.
- Scenes stay clean, by contract. The manuscript's file format is untouched by this entire feature.
- The cost is real: roughly 13–16 working sessions across the slices, and the honest new-design
  risks are concentrated in S2 (a new field type through every uniform surface) and S12 (multi-
  target review UX). Both sit behind gates of accepted design, not discovery-during-port.
- Some branch capabilities return later or not at all: relationship edges, a timeline view, and
  undo (to be re-judged against single-commit writes plus snapshots) are future issues, deliberately
  out of scope here.

## Open — to settle at implementation

- The S2 mockup pass settles the list-editing UX and the exact mechanics of groups as item shapes.
- The final claim-type roster for S4/S11 (start minimal; widen on demand).
- Where seed-from-manuscript and "open plot board" live in the ADR-0047 invocation model (app menu
  vs contextual action) — decided when S5/S7 are filed.
- Whether card ordering ever becomes story-meaningful (then it moves onto the card, per §3).

## Test surface

- **S2**: the list type across all three uniform surfaces; per-item validation and per-item AI
  drops; layered merge of item schemas.
- **S3**: the lore suite unchanged and green is the acceptance test.
- **S4–S6**: ported behavioral tests, especially spoiler gating pinned by absence assertions;
  seeding writes on create only — and a test that *opening* writes nothing.
- **S5**: cardinality invariants (n cards → one scene; attachment survives scene moves; dangling
  attachment on scene delete is visible, not silent).
- **S11–S12**: round-trip tests in the 0046 style — garbled and partial patches surface, dropped
  fields are named, nothing writes before adopt, one write per commit; patch sets validate and fail
  per element, never as a batch.
