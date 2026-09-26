# Mid-scene lore changes (mutations)

> User guide — everything below is a shipped feature; you don't need any design docs to use it.

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

Each change is kept as a **mutation set**: a small file of its own (under `mutation-sets/`) that says
*what* changes. The scene holds only a one-line anchor that says *where*. So:

- **Click a pill to edit the change**: add or remove field changes, change values, rename it. This
  saves the mutation set; the scene itself is not touched. Each field change keeps its own identity,
  so you can still end one of them on its own later (see closing, below).
- **Moving prose moves the change.** Cut a paragraph and paste it elsewhere, and its pill moves
  with it. **Copying** prose copies the change: the pasted pill gets its own mutation set, so editing
  one never alters the other.
- **Deleting a pill removes the change from this scene**, not the change itself: the mutation set
  stays on the entry's card as *staged*, ready to be placed again (or deleted there). Undo brings the
  pill back. The pill dialog's **Remove from this scene** does the same.
- In the scene's Markdown file a change is one short comment naming its mutation set; the set's own
  file lists the field changes in plain YAML.

## Seeing the timeline

Open the lore entry. When it has changes, a **scrubber** appears along the bottom of the card —
**one stop per unit** (one authored change), not one per field, so the stops stay meaningful; the
tooltip lists what changes there. Pick a stop and the whole card shows the entry **as of that
point** — title, body, and every field reflect their effective values there, with changed fields
marked in the mutation violet and a small **⤳**. At the start of the scrubber you edit the base
(book-start) values.

At a later stop, **every field is editable in place, except the body and long-text fields** — the
header title, the rail, and the list tabs (including a relationship item's own detail line) all
edit in place. The body and any long-text field stay a read-only overlay there: each shows its
value **as of that point**, and their rows (a replace or an appended fragment) are edited through
the change's dialog instead — the pill dialog, or the mutation set editor. A short text field is
different: it edits like any other scalar, and a save there **replaces** its value at that stop
(removed when it matches the value without the set) — there's no append at a stop. Editing any
field at a stop changes **that stop's mutation set**, never the scene — so it's safe even while a
different scene has unsaved typing in it. This is your trust surface: you can *see* "Honor as of
Scene 5" and confirm nothing from the future has leaked backward. The rail's Mutations list
mirrors the same stops, one row per unit.

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

## Appending, and why fragments must stand alone

Text fields (including an entry's body) can take an **Append** change instead of a replace: the
fragment is added after whatever the field says at that point.

Collections (tags, references, multi-selects) are simpler than that: you just **edit the list**.
The `/mutate` dialog shows the field's normal widget, pre-filled with what the list *effectively
contains at that point in the story*; add and remove items as usual. Small `+item` / `−item` chips
under the widget show exactly what will be recorded — you author the edit, the app derives the
add/remove records. Ending (closing) a unit later reverts those records like any other change.

Collections are always authored (and stored in mutation sets) as **per-item add/remove** — there is
no whole-list "replace" in the UI. That is deliberate: a whole-list value packs several members into
one comma-joined value, which cannot round-trip a member that itself contains a comma. If you
**hand-edit** a mutation set file and write an `op: replace` row on a collection field, keep the
comma-joined form in mind; each add/remove row carries a single member and needs no such care.

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

## Reusing a set of changes

A recurring transformation (a werewolf's dusk change: appearance + abilities + name) can be saved as
a **template**: a mutation set with no character of its own, re-applied to any character in one
step instead of retyping it. Tick "Save as a reusable set" when you author a change, or manage sets
in the Mutations list, then `/mutate` → pick a character → **Apply a saved set**. Applying a template
copies it for that character; the template itself never changes.

A mutation set for a character is in one of two states, and the app works the state out from the
prose (there is nothing to toggle):

- **staged** — it is not in any scene yet. A brainstorm chat can *stage* a set onto its subject's
  card for you, and a pill you delete leaves its set staged.
- **active** — a scene holds its pill; it goes live in the story from that point forward. You
  **place** a staged set with `/mutate` → pick the character → **Apply a saved set**; the card itself
  cannot place a set, because only the prose knows *where*. Applying an active set again offers a
  choice: **Link** anchors the *same* set in this place too — edit it once, and the change applies
  everywhere it's linked; the pill then shows how many places (`⤳ Name · N places`), and both the
  pill dialog and the scrubber name the others. **Copy** places an independent copy instead, the way
  applying a template does.

These two words are the whole vocabulary: the thing is always a **mutation set**, never a "change",
"staged change", or "pending change"; and "active" here means *this set is placed* — distinct from
the timeline scrubber's "Changed by here", which is about a single value's effect at a point in the
prose, not about the set.
