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

In a scene, type `/mutate`, pick the entry, pick the field(s), and enter the new value(s). It drops
**one** small marker (a violet **⤳** pill) at the cursor — one authored change is one **unit**,
however many fields it touches (a promotion = rank + title + uniform → one pill, showing a `·3`
count). You can **name** a change ("Honor's promotion") — purely a memory aid to recognise it
later; leave it blank and it labels itself ("rank → Captain", or "3 changes").

Click a pill to edit the **whole unit**: add or remove field changes, change values, rename it, or
delete it. Each field change inside a unit keeps its own identity — you can still end one of them
on its own later (see closing, below).

The marker lives in the scene, so moving or deleting the scene moves or deletes its changes — there
is nothing separate to keep in sync. In the Markdown file a unit is a single readable comment,
whether it changes one field or five.

## Seeing the timeline

Open the lore entry. When it has changes, a **scrubber** appears along the bottom of the card —
**one stop per unit** (one authored change), not one per field, so the stops stay meaningful; the
tooltip lists what changes there. Pick a stop and the whole card shows the entry **as of that
point** — title, body, and every field reflect their effective values there, with changed fields
marked in the mutation violet and a small **⤳**. Slide back to the start to edit the base
(book-start) values again. This is your trust surface: you can *see* "Honor as of Scene 5" and
confirm nothing from the future has leaked backward. The rail's Mutations list mirrors the same
stops, one row per unit.

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

## Appending, and why fragments must stand alone (v1.1)

Text fields (including an entry's body) can take an **Append** change instead of a replace: the
fragment is added after whatever the field says at that point.

Collections (tags, references, multi-selects) are simpler than that: you just **edit the list**.
The `/mutate` dialog shows the field's normal widget, pre-filled with what the list *effectively
contains at that point in the story*; add and remove items as usual. Small `+item` / `−item` chips
under the widget show exactly what will be recorded — you author the edit, the app derives the
add/remove records. Ending (closing) a unit later reverts those records like any other change.

Collections are always authored (and stored in mutation sets) as **per-item add/remove** — there is
no whole-list "replace" in the UI. That is deliberate: a whole-list value packs several members into
one comma-joined marker value, which cannot round-trip a member that itself contains a comma. If you
**hand-write** a `op=replace` marker on a collection field, url-encode any comma inside a member
(`%2C`); each add/remove marker carries a single member and needs no such care.

There is one contract to write by: **every appended fragment must stand alone.** Each change is an
independent interval — it can be *closed* (ended) on its own, at any later point in the story.
If fragment B leans on fragment A ("She trusts John." → "But only him."), closing A leaves B
reading nonsense — the app resolves the remaining fragments correctly, but it cannot know that B's
*meaning* depended on A. Write each append as if its neighbors might not be there, or author
dependent changes as **one** named unit (one `/mutate`, several fields).

Closing honours the same shape: `/mutate close` lists the open changes **by unit** — picking a
unit ends everything it changed, in one gesture, while a multi-field unit can be expanded to end
just one of its rows (the werewolf's mid-transform clue can outlive the transform).

Collections are safer: adds and removes combine as set operations, so closing any one of them
still leaves a coherent set. The stand-alone rule matters mainly for appended prose.

> A real fix (declared dependencies between changes, cascading closes) is deliberately deferred to
> the v2 linked-mutations design — tracked in
> [#73](https://github.com/antoncl/local-writing-app/issues/73).

## Reusing a set of changes (v1.1)

A recurring transformation (a werewolf's dusk change: appearance + abilities + name) can be saved as
a **mutation set** and re-applied to any character in one step, instead of retyping it. See the
v1.1 notes; the short version: mark a change "reusable" when you author it, or manage sets in the
Mutations list, then `/mutate` → pick a character → **apply a set**.
