# ADR-0055: A time-aware conversation reads its subject as-of a scene and stages a mutation the writer places

- Status: **Accepted** — 2026-08-14 (approved by Anton; authored by Claude). Grew out of the ADR-0054
  conversations/impersonate work when the question "how well does this hold up against inheritance,
  overrides, mutations and time-awareness?" exposed that the loop is timeline-blind.
- Follows: ADR-0013 (time-travel-aware lore — the subject *has* a timeline), ADR-0042 (the edit
  gesture — **§5, new mutation points are authored in prose only**), ADR-0046 (a brainstorm chat
  commits a change back to an entry), ADR-0051 (a node owns its conversations; a chat references its
  subject), ADR-0054 (a prompt picks a disposition and an optional commit — impersonate + `offer_on`),
  ADR-0001 (the scene is authoritative; narrative position *is* file position), ADR-0011 (a mutation
  set is a stamp, not a live link), ADR-0016 (the mutation unit + row shape), #62 (reusable mutation
  sets).
- Governed by: `docs/design/design-language.md` (consumes the settled `⤳` mutation mark).
- Citations pinned to `master@490dcc8`.

## Context

ADR-0054 shipped conversations on a card: **impersonate** (chat first-person with a `lore:character`)
and `offer_on` (which prompts a node's Conversations ＋New offers). ADR-0046 shipped the commit — a
brainstorm chat writes a change back to an entry.

ADR-0013 established that a lore entry is **time-travel-aware**: a character's `title`, `body`,
`aliases`, and every field can differ across the manuscript, driven by `<!-- mutate: -->` carrier
markers authored inline in *scene* bodies and resolved by `effective_state(entity, scene, position)`
(`services/project/lore_mutations.py`). "Who Mira is" at Chapter 2 and at Chapter 40 genuinely differ.

Both halves of the conversation loop ignore that timeline:

- **Read.** impersonate resolves the character through the flat `entry()` helper
  (`services/ai/helpers.py`) → `read_lore_entry` (`services/project/lore.py`), which returns **base
  state (stop 0 = book-start)** with no scene anchor. A character who is renamed, cursed, or rewritten
  mid-story is impersonated as their *first-introduction* self — the least useful default.
- **Write.** The ADR-0046 commit writes the lore file's base front-matter + body via `save_lore_entry`
  and is scene-blind. It cannot express "this changes *as of* a scene" — that is a mutation, and a
  mutation lives in a scene.

The obvious fix — have the commit mint a marker into a scene — is **forbidden by ADR-0042 §5**: new
mutation points require a prose cursor, and a card/chat has none; inventing a manuscript position
card-side is exactly what the scene-authoritative model (ADR-0001) was chosen to avoid. There is, and
should be, no programmatic "create a mutation from the entry" path — the mutation write surface is only
update/delete of *existing* rows (`lore_mutations.py`), and new points are born only by the `/mutate`
dialog inserting a pill at a real cursor in a scene.

So the loop is not just missing a feature; it silently lies about the timeline, and the naive fix
violates a foundational ADR. This ADR settles both halves without touching that foundation, and it
reuses the object the project already has for a position-free bundle of field changes — the **mutation
set** (#62) — rather than inventing a parallel one.

## Intent

Make a conversation tell the truth about the timeline:

1. it **reads** its subject as the subject was *at a chosen point in the story*, and
2. when it produces a timeline change, it **stages** that change as a position-free **mutation set** the
   writer later **places** in a scene — so the change becomes real exactly where the writer says it
   happens.

The unifying rule, which both halves obey:

> **The AI authors a change's content; the writer authors its position.**

## Anti-goals (what this must not do)

- **No card-side position invention.** The AI never writes a `<!-- mutate: -->` marker. ADR-0042 §5 /
  ADR-0001 stand untouched; the marker is still born in prose, at a real cursor, by the writer.
- **No second variant of a mutation set.** A staged change is a *mutation set* — the same noun a writer
  already curates — distinguished only by an **optional entity pin**, never a parallel "staged
  mutation" kind with its own storage, pane, and apply flow.
- **No new mutation storage grammar.** The set already carries `MutationSetRow{field, op, value}` rows
  and already has an apply-into-scene flow. Placement mints an ordinary carrier.
- **The read side never writes.** Resolving a subject as-of a scene is a pure read; it does not create
  or move a marker.
- **Base/canon commits are unchanged.** Correcting a character's canonical (atemporal) definition still
  writes the entry directly, as ADR-0046 does today.
- **Not read-side hierarchy scrubbing.** "Show me this entry as the *series* sees it" stays deferred
  (ADR-0042 §9). The only axis this ADR makes a conversation aware of is the *manuscript*.

## User journey — Mira becomes a werewolf

1. The writer opens **Mira** (a `lore:character`) while drafting Chapter 2 and starts an **Impersonate**
   conversation. It reads Mira *as of* the writer's current point — pre-curse Mira — and answers in
   that voice. Impersonating her here does not leak the werewolf she has not yet become.
2. Later, the writer starts a **committing brainstorm** on Mira: "how does her lycanthropy manifest?"
   They shape it with the AI over several turns.
3. **Commit** does not touch a scene. It **stages a mutation set pinned to Mira**: `{condition:
   werewolf; body += transformation notes}`, with *no* position — the same object the writer could have
   hand-authored from Mira's card. It appears as a *pending* set on Mira's card (and in the Mutations
   pane), and the **chat now owns it**.
4. A week of writing later, the writer **reopens that brainstorm**. It does not start blank: the pinned
   set is resolved from the chat's reference, shown, and seeded into the prompt context, so the AI
   continues — "we established Mira turns at the blood moon; let's tighten the first change" — instead
   of relitigating.
5. The writer reaches the transformation scene. In prose, `/mutate` offers Mira's pending set (already
   pinned to Mira); the writer **places it** at the moment of transformation. The carrier marker is born
   there, in the scene, at a real cursor.
6. From that scene onward Mira *is* a werewolf everywhere the effective state is read — a later
   impersonate speaks as the werewolf; one anchored before it still speaks as human. The loop told the
   truth.

## Decision

### 1. A conversation reads its subject as-of a scene

The **as-of anchor** is the point in the manuscript at which a conversation reads its subject — the
lore card's scrubber position, attached to a conversation instead of the card. A subject is
time-travel-aware (ADR-0013): who Mira *is* differs across the story, and `effective_state(entity,
scene, position)` computes her title/body/fields as of any point. A subject-anchored prompt
(impersonate, and any `chat_panel` prompt offered on a time-travel-aware subject) resolves the subject
through `effective_state` **at its anchor**, not the flat `entry()` base read — which is always
book-start (stop 0). The anchor is a scene (optionally a prose position), carried on the conversation.

- **The anchor is the subject's time-travel slider.** The character card already carries the ADR-0013
  scrubber; a conversation reads the subject at the slider's current stop, and moving the slider
  re-anchors — the writer picks the version with the same control they already use to *view* it. No
  separate "as of" picker. (A scene-launched conversation defaults its anchor to that scene.)
- The anchor is a property of the conversation, resolved at send time. Its rest value is the slider's
  position — never stop 0 (book-start), which is today's silent-wrong default.

This is a pure read and reuses ADR-0013 machinery the lore card already drives.

### 2. A committing conversation stages a mutation set pinned to its subject

When a conversation's commit expresses a **timeline** change (as opposed to a canonical correction —
§6), it produces a **mutation set** carrying `MutationSetRow{field, op, value}` rows, **pinned to the
conversation's subject**.

- It has **no scene and no position**. The AI proposes *what* changes and *to whom*, never *where*.
- It is an ordinary mutation set — created through the same path a writer's set uses — with the entity
  pin set. The commit persists it via `create_mutation_set_entry`; nothing in that path references the
  manuscript.
- Because set-save validates no rows (§Resolved), the commit **validates the AI-proposed rows against
  the subject's type** — the field/op rules the marker validator already defines — so a set can never
  carry a field or op that would be rejected when the writer later places it. This reuses ADR-0046's
  "validate a structured AI result" role.

### 3. One mutation set, entity binding optional, authored from the entity

There is **one** mutation-set model, not two. A mutation set gains an **optional `target_entity`**
alongside its existing `target_entry_type` (`models/entries.py: MutationSetEntry`):

- **Unset** → the reusable, type-scoped template of today (#62): applicable to any entity of
  `target_entry_type`, entity chosen at apply time. Unchanged.
- **Set** → an *entity-pinned* set: this change, about this character. On apply it pre-fills its entity
  rather than asking, and it is not offered as a generic template for other entities.

A staged commit is simply the pinned mode; a hand-authored "change to Mira" is the same object. The
row shape, storage kind (`mutation_set:mutation_set`), pane, and apply flow are all shared — the pin is
one field, not a new grammar.

**The pin is a `metadata` `entity_ref`, not a top-level field like `target_entry_type`.** That choice
does double duty for free: edge extraction emits a **set→subject edge** (kind-neutral, §Resolved), so
the subject's reverse index lists its pending sets the same way it lists its chats — and the set enters
the reference-integrity machinery, so deleting the subject *purges* the pin rather than leaving it
silently dangling (§Resolved contrasts this with `target_entry_type`, which is top-level and does go
stale).

**The natural authoring home for a set is the lore entity.** Creating or editing a set *from* the
character card pins it to that entity by construction, so the "author from the entity" gesture and the
"entity pin" are one fact. The card thereby becomes the coherent home for the subject's whole timeline
story: **read** effective state as-of (the ADR-0013 scrubber), **author** proposed changes (pinned
sets), and **see what is pending** via that set→subject reverse edge. The Mutations pane remains the
management surface and the home for reusable, un-pinned templates.

### 4. The chat owns its pinned set as a durable, resumable work-product

The chat references its pinned set the same way it already references its `subject` — a second
`entity_ref` on `chat:chat_session` (fields today: `["subject", "color"]`, `default_schema.py`), which
the id-keyed reference graph extracts as an ordinary edge (ADR-0051, #194).

- **Durable, not ephemeral.** Unlike today's in-memory commit proposal
  (`stores/entryProposal.svelte.ts`, discarded on abandon), the set is a persisted node, so it survives
  closing the chat.
- **Resume, not restart.** Reopening the conversation resolves the referenced set, surfaces it, and
  **seeds it into the prompt context**, so the AI continues refining the same change.
- A conversation may own more than one pinned set over its life; each is an edge.

### 5. The writer places the pinned set into a scene

Placement is the terminal, prose-side step and reuses the existing "apply a saved set" flow
(`MutationAuthoringForm` → `applyMutationUnitDraft` → `insertContent`, `lib/editor-core/mutationNodes.ts`):
the set's rows stamp as one mutation unit at the writer's cursor, and an ordinary carrier marker is born
there. Because the set is entity-pinned, the entity is pre-filled rather than re-chosen.

A **pinned** set is a one-off: placing it **marks it placed** — it drops out of the card's *pending*
list and is retained as the chat's provenance, never deleted (§Resolved explains why the chat's edge
forbids deletion). A **reusable** (un-pinned) set is untouched by apply, exactly as today. This is the
one behaviour apply gains: today it is a pure read of the set, so the pinned path adds a single
write-back to flip the set's state; reusable application keeps zero writes. Until placed, a pinned set
changes nothing — the subject's effective state is untouched, so a conversation anchored after the
intended point does not yet see it.

### 6. Canonical (atemporal) commits keep the direct-to-entry path

A commit that corrects the character's canonical definition — "she was always left-handed" — is not a
timeline change and writes the entry's base directly, exactly as ADR-0046 does today. Whether a given
commit is *timeline* (§2) or *canonical* is the author's choice at commit time, surfaced in the review
UI; it is the same content, two destinations.

### 7. The one rule

> A conversation may read its subject at any point and propose any change, but it may never assert
> *where* a change takes effect. The writer authors position — as the read anchor on the way in, and
> as the placement cursor on the way out.

## Why / rejected alternatives

- **Mint a marker into a scene from the commit (scene-end placement).** The first idea, and the reason
  this ADR exists. Rejected: it is precisely the card-side position invention ADR-0042 §5 forbids —
  `END_OF_SCENE` is a *resolution* default, not an authoring position, and inventing a manuscript point
  without a cursor is what the scene-authoritative model (ADR-0001) was chosen to avoid.
- **A distinct "staged mutation" kind, separate from mutation sets.** Tempting, to keep one-off entity
  proposals from cluttering the reusable-templates pane. Rejected: it forks the same noun into two
  variants with duplicate storage, pane, and apply paths. A set already *is* a position-free bundle of
  field-change rows; the only thing it lacked was an entity pin, which §3 adds as one optional field.
- **Stage the change in a *type-scoped* set (no entity pin).** The zero-model option. Rejected: it loses
  the entity (the artifact forgets it is about Mira), invites applying it to the wrong character, and
  cannot be the resumable work-product a chat owns for a specific subject.
- **Give impersonate a `scene_ref` input and resolve `entry()` against it.** Solves only the read half,
  by extending the flat `entry()` accessor to thread a scene — duplicating the `effective_state`
  resolution the lore card already owns. §1 reuses that path instead.
- **Keep the commit's proposal ephemeral (today's in-memory patch).** Rejected by the Mira journey: a
  conversation that forgets the set it authored the moment it closes cannot be resumed.
- **A conversation always commits at "current" (end-of-book).** Rejected: it collapses the timeline the
  whole feature exists to respect — a change authored at Chapter 40 is not the same as one that takes
  effect from Chapter 2.

## Consequences

- **New:** an optional `target_entity` on `MutationSetEntry` (pin) + its apply-time pre-fill; a `placed`
  state on a pinned set + the single write-back on apply that sets it; a second `entity_ref` on
  `chat:chat_session` for the chat→set edge; an entity-side "new/edit set" authoring affordance on the
  lore card; an "as of" anchor on a conversation; context seeding of a resumed conversation's pinned
  set; the commit's timeline branch, which creates a pinned set and validates its AI-proposed rows
  against the subject's type.
- **Reused, not rebuilt:** the entire mutation-set model and its CRUD (`mutation_sets.py`),
  `effective_state` (read), the `MutationSetRow` row shape and the apply-into-scene flow
  (`mutationNodes.ts`), the reference graph (edge extraction + `conversationsFor` neighbours), and the
  ADR-0046 commit/review scaffold.
- **Untouched:** the mutation carrier grammar and scene-authoritative model (ADR-0001/0042 §5); the
  reusable (un-pinned) behaviour of existing sets (#62); base/canon commits (ADR-0046); read-side
  hierarchy scrubbing (deferred).
- **The lore card surfaces its pending pinned sets** via the set→subject reverse edge (§3), the same
  reverse-index mechanism that already lists a node's chats; the Mutations pane keeps reusable
  templates. Placement removes a set from "pending."
- **Impersonate's `.md` changes** from a flat `entry(input.entry)` read to an as-of resolution; the
  built-in prompt and the `offer_on` machinery (ADR-0054) are otherwise unchanged.

## Resolved on review

Three mechanics that were open in the first draft, verified against `master@490dcc8`:

- **The chat→set edge is an existing shape — one schema field, no graph work.** `mutation_set` is
  already a first-class graph node (`references.py`: `NodeFamily("mutation_set", …)`, in `by_id` and
  `REFERENCE_BEARING_KINDS`), and both edge extraction (`_edges_from_field`) and the reverse map
  (`rebuild_reverse_edges`) are **kind-neutral** — they key on the target id, never its kind, which is
  exactly how the chat→lore `subject` edge already works. So §4 needs no index or graph change: add one
  `entity_ref` field to `chat:chat_session`'s field list, precisely as `subject` was added (#89).
- **A pinned set is a full peer of an in-scene mutation, and the AI's rows are validated at stage
  time.** The set editor and the `/mutate` marker dialog build their field roster from the **same**
  `buildFieldOptions` (intrinsic `title`/`body` + the type's schema fields; collection add/remove) — so
  a set row already represents everything a marker can. There is no coverage gap and no "subset first".
  The real catch is the reverse: set-save runs **no** row validation (`mutation_sets.py`), and
  `save_scene` doesn't validate markers either — only `validate_project` does. Because a staged set is
  AI-authored, the commit validates its rows at stage time (see §2), reusing the field/op rules the
  marker validator (`_validate_scene_mutations`, which explicitly permits `title`/`body`) already
  defines — so a placed marker can never be born invalid.
- **Placement keeps the set, marked placed — it does not delete it.** Apply is a pure read today (no
  `placed`/`used` state on `MutationSetEntry`, no back-link from a placed marker to its set), so *both*
  "retire" and "keep" are net-new. Keep wins on the chat-ownership ground: a chat *references* its
  pinned set (§4), so deleting it on placement would strand that edge and erase the resume history ("we
  staged this; it's real at Chapter 30"). A placed pinned set therefore gains a `placed` state (drops
  from *pending*, stays as provenance); a reusable set is untouched, as today.
- **A stale target-type or field is silent staleness — and pinned sets inherit exactly that; only the
  subject pin does better.** This lifecycle edge is not new — it already applies to every set. For any
  set today, deleting its `target_entry_type` or a row's `field` cascades nothing: a set's target/rows
  live in top-level front-matter (not `metadata`), so schema-delete propagation, reference purge (#345),
  and `validate_project` — all of which touch only `metadata` `entity_ref` fields — structurally never
  see them. The only effects are deferred: a stale-target set silently drops from the `/mutate` picker
  (a harmless orphan), and a stale-field row is carried verbatim into the marker on apply, then draws an
  advisory *scene* warning (`_validate_scene_mutations`), never a set warning. A pinned set inherits this
  unchanged for its `target_entry_type` and rows. Its **subject** pin is the one exception that behaves
  *better*: as a `metadata` `entity_ref` (§3), deleting the subject *purges* the pin like any other
  reference rather than leaving it silently dangling.

## Deferred (post-v1, not blockers)

- **Nice-to-haves, deferred:** whether a placed set records the *scene* it was placed into (for a
  "placed at ‹scene›" tell), and whether a stale-*field* row in a pending pinned set is actively
  surfaced on the card rather than only warned at apply — both are refinements over the existing
  silent-staleness behaviour, not blockers.
- **A legible change-point list on the card** (a named "became a werewolf / lost an arm" list, plus the
  reusable sets applicable to this type) as an *alternative* to the positional slider for both anchoring
  and applying — a new card surface, deferred and evaluated on its own; the slider (§1) covers the
  anchor for v1.

## Suggested slicing (indicative, not decided here)

1. **Read half** — the as-of anchor + `effective_state` resolution for impersonate. Self-contained,
   independently valuable, no new storage.
2. **Entity pin + entity-side authoring** — `target_entity` on the set, apply-time pre-fill, and the
   "new/edit set" affordance on the lore card. Useful on its own (hand-authored pinned sets), no AI.
3. **Chat owns the set** — the chat→set edge + resume seeding into context.
4. **Commit → stage** — the timeline branch of the ADR-0046 commit produces a pinned set the chat owns.
