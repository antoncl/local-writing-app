# Mid-scene lore changes (mutations)

> User guide. *This feature ships across 0.4.0 (v1.0 landed; v1.1 in progress).* Design lives in
> `docs/design/mid-scene-lore-mutations.md` (+ the v1.1 doc and ADRs) — you don't need it to use the
> feature.

## What this is

Your lore entries store a *current* value — a character's rank, a location's owner, what a detective
knows. But stories move through time, and an earlier scene should not be written as if it knows the
*later* value: Chapter 1 should see Commodore Honor, Chapter 10 Captain Honor, and Chapter 3 must
never learn it was the butler.

A **mutation** records a change **at the point in the prose where it happens**. From that point
forward (in manuscript order), anything the AI reads about that entry sees the new value; anything
before it still sees the old one. You write the change once, where it occurs, and every
generation is given only what is knowable at *its* place in the book.

## Recording a change

In a scene, type `/mutate`, pick the entry, pick the field(s), and enter the new value(s). It drops a
small marker (a violet **⤳** pill) at the cursor. One `/mutate` can set several fields at once (a
promotion = rank + title + uniform). You can **name** a change ("Honor's promotion") — purely a
memory aid to recognise it later; leave it blank and it labels itself ("rank → Captain").

The marker lives in the scene, so moving or deleting the scene moves or deletes its changes — there
is nothing separate to keep in sync.

## Seeing the timeline

Open the lore entry. When it has changes, a **scrubber** appears along the bottom of the card. Drag
it and the whole card shows the entry **as of that point** — title, body, and every field reflect
their effective values there, with changed fields marked in the mutation violet and a small **⤳**.
Slide back to the start to edit the base (book-start) values again. This is your trust surface: you
can *see* "Honor as of Scene 5" and confirm nothing from the future has leaked backward.

## How resolution works — and its one limit

**Read this if you rename anything.** For every field *except names*, resolution is exact and
position-aware: prose before a change sees the old value, prose after it sees the new one, down to
the point in the scene where the marker sits.

**Names are the exception.** The app auto-detects when you *mention* an entry by name or alias
(so it can quietly hand the AI the right context). When you **rename** an entry — its title or an
alias — that detection resolves **one scene at a time**:

- In every scene **before** the rename's scene, the entry is detected under its **old** name; in
  every scene **after**, under its **new** name. This is correct and automatic.
- **Only inside the single scene where the rename happens**, detection uses one name for the whole
  scene. So a mention on the "early" side of the rename marker, *in that one scene*, may be
  recognised under the new name (or vice-versa).

This affects **only** the automatic name-detection/highlighting, **never your text** and never the
values the AI is given for a field. It is deliberately scoped this way (the alternative is a large
cost for a rare case). If you want a rename to read exactly on both sides *within its own scene*,
split the scene at the rename, or record the rename at the very start/end of the scene.

> This limit is called out here rather than left implicit; when authoring a name/alias change the
> `/mutate` form also flags it inline with a link back to this section.

## Reusing a set of changes (v1.1)

A recurring transformation (a werewolf's dusk change: appearance + abilities + name) can be saved as
a **transformation set** and re-applied to any character in one step, instead of retyping it. See the
v1.1 notes; the short version: mark a change "reusable" when you author it, or manage sets in the
Transformations list, then `/mutate` → pick a character → **apply a set**.
