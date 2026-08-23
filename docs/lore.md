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
**Search entries, tags, aliases** box at the top filters as you type. A fresh
project shows *"No entries yet."*

The way entries are grouped and ordered is itself a **view**, and the pane's view
switcher lets you change it — see the **[Views](#guide:views)** guide.

## Add an entry

1. Click **+** (*Add entry*) at the top of the pane.
2. In the **New entry** popover, pick a type — **Character**, **Location**, or
   whatever your project defines. (If the list is empty, you haven't defined any
   types yet; see **[Custom fields](#guide:custom-fields)**.)
3. The entry is created — titled *"New Entry"* — and opens straight away, ready to
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

- **Type** — a select near the top shows the entry's type (Character, Location…).
  You set it when you create the entry, but you can **change it any time** here;
  the fields below update to match. **Edit type…** takes you to the type's
  definition (that's **[Custom fields](#guide:custom-fields)** territory).
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
aliases current so nicknames are caught.

## Tags

Tags are a light, cross-cutting way to organise — *protagonist*, *chapter-3*,
*needs-revision*. In an entry's **Details**, the tag field lets you type a tag and
press Enter (or comma) to add it, and Backspace to remove the last one; the **+**
button (*Add known tags*) offers tags already used elsewhere, so they stay
consistent.

To rename, merge, or recolour tags across the whole project, use **≡ menu →
Manage all tags…**.

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
