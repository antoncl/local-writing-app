# ADR-0055: A time-aware conversation reads its subject as-of a scene and stages a mutation the writer places

- Status: **Proposed** — 2026-08-14 (Claude, for Anton's review). Grew out of the ADR-0054
  conversations/impersonate work when the question "how well does this hold up against inheritance,
  overrides, mutations and time-awareness?" exposed that the loop is timeline-blind.
- Follows: ADR-0013 (time-travel-aware lore — the subject *has* a timeline), ADR-0042 (the edit
  gesture — **§5, new mutation points are authored in prose only**), ADR-0046 (a brainstorm chat
  commits a change back to an entry), ADR-0051 (a node owns its conversations; a chat references its
  subject), ADR-0054 (a prompt picks a disposition and an optional commit — impersonate + `offer_on`),
  ADR-0001 (the scene is authoritative; narrative position *is* file position), ADR-0016 (the mutation
  unit + row shape), #62 (reusable mutation sets).
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
violates a foundational ADR. This ADR settles both halves without touching that foundation.

## Intent

Make a conversation tell the truth about the timeline:

1. it **reads** its subject as the subject was *at a chosen point in the story*, and
2. when it produces a timeline change, it **stages** that change as a position-free artifact the writer
   later **places** in a scene — so the change becomes real exactly where the writer says it happens.

The unifying rule, which both halves obey:

> **The AI authors a change's content; the writer authors its position.**

## Anti-goals (what this must not do)

- **No card-side position invention.** The AI never writes a `<!-- mutate: -->` marker. ADR-0042 §5 /
  ADR-0001 stand untouched; the marker is still born in prose, at a real cursor, by the writer.
- **No overloading reusable mutation sets.** A staged change is a *one-off, entity-specific* proposal;
  a mutation set (#62) is a *reusable, type-scoped* template. They are different nouns and must not
  share a container, or the sets pane fills with un-reusable AI one-offs and forgets which character a
  change is for.
- **No new mutation storage grammar.** The staged artifact reuses the existing row shape
  (`MutationSetRow{field, op, value}`) and the existing apply-into-scene flow. Placement mints an
  ordinary carrier.
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
3. **Commit** does not touch a scene. It **stages a mutation**: `Mira → {condition: werewolf; body +=
   transformation notes}`, pinned to Mira, with *no* position. It appears in the Mutations pane as a
   *proposed* change for Mira, and the **chat now owns it** — the conversation references the staged
   mutation.
4. A week of writing later, the writer **reopens that brainstorm**. It does not start blank: the staged
   mutation is resolved from the chat's reference, shown, and seeded into the prompt context, so the AI
   continues — "we established Mira turns at the blood moon; let's tighten the first change" — instead
   of relitigating.
5. The writer reaches the transformation scene. In prose, `/mutate` offers the staged Mira mutation
   (already pinned to Mira); the writer **places it** at the moment of transformation. The carrier
   marker is born there, in the scene, at a real cursor.
6. From that scene onward Mira *is* a werewolf everywhere the effective state is read — a later
   impersonate speaks as the werewolf; one anchored before it still speaks as human. The loop told the
   truth.

## Decision

### 1. A conversation reads its subject as-of a scene

A subject-anchored prompt (impersonate, and any `chat_panel` prompt offered on a time-travel-aware
subject) resolves the subject through `effective_state(entity, scene, position)`, not the flat
`entry()` base read. The resolution point is an **"as of" scene** carried on the conversation.

- **Default anchor** is the writer's current manuscript position if the conversation is launched from a
  scene, else **end-of-book (the subject's current self)** — never stop 0 (book-start), which is
  today's silent-wrong default.
- The writer may **override** the anchor ("as of …") from the Conversations surface. The anchor is a
  property of the conversation, resolved at send time.

This is a pure read and reuses ADR-0013 machinery the lore card already drives.

### 2. A committing conversation writes only a *staged mutation*

When a conversation's commit expresses a **timeline** change (as opposed to a canonical correction —
§6), it produces a **staged mutation**: a position-free, entity-pinned artifact carrying
`MutationSetRow{field, op, value}` rows — the same row shape the in-scene `/mutate` dialog authors.

- It has **no scene and no position**. The AI proposes *what* changes and *to whom*, never *where*.
- It is **pinned to a specific entity** (the conversation's subject), unlike a reusable set.
- The commit persists it via a create call; nothing in that path references the manuscript.

### 3. The staged mutation is a distinct artifact, not a reusable set

A reusable mutation set (#62) is type-scoped (`target_entry_type`) and reusable by design — it
deliberately drops the entity, to be bound at apply time. A staged mutation is the opposite: **a
one-off pinned to one entity**. It is therefore a **distinct node kind**, surfaced in the Mutations
pane as *proposed* (separate from reusable templates), reusing the set's row shape and its
apply-into-scene flow but not its identity.

### 4. The chat owns its staged mutation as a durable, resumable work-product

The chat references its staged mutation the same way it already references its `subject` — a second
`entity_ref` field on `chat:chat_session` (fields today: `["subject", "color"]`,
`default_schema.py`), which the id-keyed reference graph extracts as an ordinary edge (ADR-0051, #194).

- **Durable, not ephemeral.** Unlike today's in-memory commit proposal
  (`stores/entryProposal.svelte.ts`, discarded on abandon), the staged mutation is a persisted node,
  so it survives closing the chat.
- **Resume, not restart.** Reopening the conversation resolves the referenced staged mutation, surfaces
  it in the UI, and **seeds it into the prompt context**, so the AI continues refining the same change.
- A conversation may own more than one staged mutation over its life; each is an edge.

### 5. The writer places the staged mutation into a scene

Placement is the terminal, prose-side step and reuses the existing "apply a saved set" flow
(`MutationAuthoringForm` → `applyMutationUnitDraft` → `insertContent`, `lib/editor-core/mutationNodes.ts`):
the staged mutation's rows stamp as one mutation unit at the writer's cursor, and an ordinary carrier
marker is born there. Because it is entity-pinned, the entity is pre-filled rather than re-chosen.

Placing a staged mutation **marks it placed** (it becomes provenance of the now-real marker); it is no
longer a pending proposal. Until placed, it changes nothing — the subject's effective state is
untouched, so a conversation anchored after the intended point does not yet see it.

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
- **Stage the change as a reusable mutation set.** The plumbing fits (a set is position-free and has an
  apply flow), and it is the tempting zero-model option. Rejected: a set is *type-scoped and reusable*;
  forcing a one-off entity-specific proposal into it loses the entity (the artifact forgets it is about
  Mira), invites applying it to the wrong character, and clutters the reusable-templates pane. §3 keeps
  the noun honest.
- **Give impersonate a `scene_ref` input and resolve `entry()` against it.** Solves only the read half,
  and by extending the flat `entry()` accessor to thread a scene — duplicating the `effective_state`
  resolution the lore card already owns. §1 reuses that path instead.
- **Keep the commit's proposal ephemeral (today's in-memory patch).** Rejected by the Mira journey: a
  conversation that forgets the mutation it authored the moment it closes cannot be resumed, and the
  writer loses the work between the brainstorm and the scene where it belongs.
- **A conversation always commits at "current" (end-of-book).** Rejected: it collapses the timeline the
  whole feature exists to respect — a change authored at Chapter 40 is not the same as one that takes
  effect from Chapter 2.

## Consequences

- **New:** a staged-mutation node kind (entity-pinned, position-free, row-shaped) with create/read/list
  and a "placed" transition; a second `entity_ref` on `chat:chat_session` for the chat→staged-mutation
  edge; an "as of" anchor on a conversation; context seeding of a resumed conversation's staged
  mutation.
- **Reused, not rebuilt:** `effective_state` (read), the `MutationSetRow` row shape and the
  apply-into-scene flow (`mutationNodes.ts`), the reference graph (edge extraction + `conversationsFor`
  neighbours), and the ADR-0046 commit/review scaffold.
- **Untouched:** the mutation carrier grammar and scene-authoritative model (ADR-0001/0042 §5); reusable
  mutation sets (#62); base/canon commits (ADR-0046); read-side hierarchy scrubbing (deferred).
- **The Mutations pane grows a second section** — *proposed* (entity-pinned, one-off) alongside
  *reusable sets* — or the proposed items live on their subject card. Which surface is §-open (below).
- **Impersonate's `.md` changes** from a flat `entry(input.entry)` read to an as-of resolution; the
  built-in prompt and the `offer_on` machinery (ADR-0054) are otherwise unchanged.

## Open questions (to settle before slicing, not in this ADR)

- **Default anchor for a card-launched conversation** with no current scene: end-of-book (current self)
  is proposed; confirm, and confirm the override affordance's home on the Conversations surface.
- **Surface for a staged mutation:** the Mutations pane's *proposed* section, the subject card, or
  both. It has two natural homes (the mutation system and the entity it targets).
- **Field coverage:** whether a staged mutation may carry intrinsic `title`/`body` rows
  (`INTRINSIC_MUTABLE_FIELDS`) and collection ops, matching the in-scene authoring surface, or a subset
  first.
- **Whether placement retires or keeps** the staged node (provenance vs. cleanup), and what happens to a
  staged mutation whose subject or target field is later deleted.

## Suggested slicing (indicative, not decided here)

1. **Read half** — the as-of anchor + `effective_state` resolution for impersonate. Self-contained,
   independently valuable, no new storage.
2. **Staged-mutation artifact** — the node kind + create/list + the chat edge (no placement UI yet).
3. **Commit → stage** — the timeline branch of the ADR-0046 commit produces a staged mutation; resume
   seeds it into context.
4. **Placement** — the staged mutation offered in the scene `/mutate` flow, entity pre-pinned; "placed"
   transition.
