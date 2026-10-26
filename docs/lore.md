# Lore

**Lore** is your story's memory — the characters, places, factions, objects, and
ideas worth keeping straight. Each item is an **Entry**: a title, a Markdown body,
and whatever fields its type carries. Entries link to each other, and when you
turn AI on, they're the material it draws from — so the effort you put into lore
pays off both as a reference for you and as context for the model.

This guide covers day-to-day use of entries. Designing your own entry *types* and
fields is the **[Custom fields](#guide:custom-fields)** guide; letting a fact
*change* partway through the story is **[Mutations](#guide:mutations)**.

## The Lore pane

Open the **Lore** pane and you'll see your entries, grouped by type — all your
Characters together, then Locations, and so on, each group showing a count. A
**Search entries, #tags, aliases** box at the top filters as you type. A fresh
project shows *"No entries yet."*

The way entries are grouped and ordered is itself a **view**, and the pane's view
switcher lets you change it — see the **[Views](#guide:views)** guide.

## Add an entry

1. Click **+** (*Add entry*) at the top of the pane.
2. In the **New entry** popover, pick a type — **Character**, **Location**, or
   whatever your project defines. (If the list is empty, you haven't defined any
   types yet; see **[Custom fields](#guide:custom-fields)**.)
3. The entry is created — titled *"Untitled entry"* — and opens straight away, ready to
   rename and fill in.

> If AI is on, the popover also offers **Brainstorm new…** with a **✨ Draft
> &lt;Type&gt;** option, which drafts an entry *with* you in a chat instead of
> from a blank page.

## Write the entry

An open entry has three parts:

- A **Name** at the top — what the entry is called (used everywhere it's
  referenced, and for detecting mentions of it in your prose).
- A **Markdown body** — the description, history, voice, notes; write as much or
  as little as you like.
- A **Details** rail beside the body, holding everything structured about the
  entry.

## Details: type, fields, and aliases

The **Details** rail is where an entry's structured information lives.

- **Type** — the rail's head shows the entry's type as one line: its name
  (Character, Location…), its icon when the type has one, and a small caret.
  You set the type when you
  create the entry, but you can **change it any time**: click the head and pick
  another type; the fields below update to match. **Edit type…** at the foot of
  that list takes you to the type's definition (that's
  **[Custom fields](#guide:custom-fields)** territory).
- **Fields** — everything the type defines: tags, references, a colour, and any
  custom fields, grouped into sections.
- **Aliases** — a list of alternate names ("The Salamander" for a character named
  Ivo). Aliases matter beyond bookkeeping: the app watches your prose for each
  entry's **Name and its aliases**, so a character referred to by a nickname is
  still recognised — underlined in the editor, and offered as context to the AI.

## Link entries together

Relationships between entries are **reference fields**. Where a type has one (a
character's *home*, a scene's *POV*, a faction's *members*), Details shows a
picker: open it, choose the target entry (or several), and it's linked. Linked
entries show as rows you can click to jump straight to them.

Links are two-way to read. On any entry, the **References** section of Details
lists its **incoming** links — every entry that points *at* this one. So opening a
location shows you every character who calls it home, without your having to
maintain a list by hand. Those rows are clickable too; *"No incoming references."*
means nothing points here yet.

## Mentions in your prose

You don't need a special syntax to reference lore while writing. Type a
character's **Name** (or one of their aliases) in a scene and the app detects it
automatically, underlining the mention. This is also how the AI knows which
entries are relevant to what you're actually writing — it offers the entities it
found, so the model gets the right context without you attaching anything by hand.

There's no `[[wiki-link]]` or `@mention` to learn; just write, and keep your
aliases current so nicknames are caught. How those mentions turn into the lore
an AI chat receives — and the per-entry **Context policy** that keeps a spoiler
out of it — is covered in **[What the AI sees](#guide:ai-context)**.

## Notes the AI always sees

Some notes aren't about one thing in your world but about how all of it works: a
magic system, a calendar, how names are formed. Set such a note's **Context
policy** to *Always include* and the AI receives it with nearly every prompt,
whether or not anything names it (the exceptions are in
**[What the AI sees](#guide:ai-context)**).

**Naming conventions** are the common case. If you want the names the AI invents
to fit your world — how a family name is built, what ships or inns are called —
keep them in a note of their own and set it to *Always include*. Draft scene,
Continue and the brainstorm prompts then see it whenever they coin a name. Keep
naming out of a style note: a style note says how the prose reads, and the style
builder leaves naming out of it (see
**[How your prose is steered](#guide:prose-steering)**).

## Tags

Tags are a light, cross-cutting way to organise — *protagonist*, *chapter-3*,
*needs-revision*. A tag is an entry in its own right, of its own kind — a Tags
field on an entry just holds references to them. Open a Tags field's picker and
pick from the tags that already exist; type a name that matches nothing (case is
ignored) and the picker offers **Create "‹name›"** to mint it on the spot.

The **Tags** pane (**≡ menu → Manage all tags…**) lists every tag, grouped by
vocabulary, each with a count of how many entries carry it. From there you can
open a tag to rename it, recolour it, merge it into another tag, or delete it.
Merging keeps every entry that carried the old tag — they now read, filter, and
count as the tag you merged into.

## Organising a large world

Beyond grouping by type, the Lore pane's view switcher can filter, group, and even
**nest** entries into trees — characters under their faction, sub-locations under
a region — by following the reference fields you've filled in. That's all done
with **[Views](#guide:views)**; there are no folders to manage.

## Where to go next

- **[Custom fields](#guide:custom-fields)** — define the entry types and fields
  your world needs.
- **[Mutations](#guide:mutations)** — let a fact change partway through the story
  without leaking the future into earlier scenes.
- **[Views](#guide:views)** — filter, group, and nest your lore however you think
  about it.
