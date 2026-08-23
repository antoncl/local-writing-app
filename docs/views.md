# Views

Every list in the app — your scenes, your characters, your research — is produced
by a **view**: a small query that decides *which* items appear and *how* they're
ordered and grouped. Most of the time you'll use the built-in views without
thinking about it. When you want something more specific — "just my draft scenes,
grouped by point-of-view character" — you build a view in a visual designer, by
wiring a few boxes together. No code.

This guide covers the view designer as it ships today.

## Views live on a pane

A view is always *about* one kind of thing — scenes, or lore, or research — and
you pick and build views from the pane that shows that kind. Beside a pane's **+**
button is the view switcher: a **▤ ▾** button. Click it to:

- switch between the **built-in** views and any you've saved,
- **⧉ Duplicate** a view (the only action on a built-in — a great way to start),
- **✎ Edit** or **× Delete** one of your own views, or
- choose **New view…** to open the designer with a blank canvas.

Every kind ships a **Default view**; chats also get **All chats** and **Openable
chats**. Built-ins can't be edited in place — duplicate one and edit the copy, or
start fresh with **New view…**.

> A view you build from the Draft pane is a view *over scenes*; one built from the
> Lore pane is *over lore*. The designer shows this fixed anchor at the top as
> **"Views over &lt;kind&gt;"**. You can't retarget a view to a different kind —
> build it from the pane that shows what you want.

## The designer at a glance

Opening a view shows three columns:

- **Parameters** (left) — any inputs you've exposed, so you can try values live.
- **The canvas** (center) — where you wire the query together.
- **Preview** (right) — the live result as you build, with a running count.

Above the canvas is a palette tray, grouped **Sources** and **Operations**. Add a
node by clicking its chip — it drops onto the canvas — or by dragging it out.

Each node has small **connection points** on its sides: **inputs** on the left,
**outputs** on the right. You build a query by **wiring** nodes together — drag
from one node's output point to the next node's input point, and a line appears
linking them, so the first node feeds the second. Everything flows toward a single
node labelled **View result** — whatever reaches it is what the pane shows.

To remove a connection, click the **✕** at its midpoint (or select the line and
press **Delete**).

The mental model is a pipeline, left to right:

> **a Source** (what to start from) → **Operations** (narrow it, combine it, sort
> it) → **View result** (what you see).

If the canvas is empty, start by dragging a **Source** in, then wire operations
toward **View result**.

## Start with a Source

Two nodes begin a query:

- **All** — every item of the kind (all scenes, all characters…). The usual
  starting point.
- **Hand-picked** — a fixed list you choose by hand. Use it when a view is really
  just "these specific items, in this order."

## Filter — the workhorse

**Filter** keeps or drops items by a rule. Drop it after a Source and wire them
together. Each Filter has:

- a **Keep / Drop** toggle — keep the matches, or throw them out; and
- a **predicate** — what to match on:
  - **Type is** — a single entry type (e.g. only *Chapter* nodes).
  - **Type & subtypes** — a type and everything under it (shown only when the kind
    has more than one type).
  - **Field** — any field on the item: its **tags**, a **select** like *Status*, a
    reference field, even the title. Pick the field, then an operator — **any of**,
    **none of**, **is set**, **is empty** — and the value(s).

Examples:

- *Draft scenes*: **All** → **Filter** (Keep · Field · `Status` · **any of** ·
  Draft).
- *Everything except antagonists*: **All** → **Filter** (Drop · Field · `tags` ·
  **any of** · antagonist).

**Chaining Filters is "and."** Wire one Filter into another and an item must pass
both — "Draft **and** POV is Honor" is just two Filters in a row.

## Combine sets

When you need "and / or / but-not" across two *separate* branches, use the set
operations. Each takes two inputs:

- **Union** — items in either branch (an "or").
- **Intersect** — items in both.
- **Difference** — items in the first branch but not the second.
- **Complement** — everything of the kind *except* the input.

Chaining Filters covers most "and" cases; reach for these when the two sides are
genuinely different queries you want to fold together.

## Shape the result

A few operations don't change *which* items appear, only how they're presented or
what they point at:

- **Sort** — order the result by a field.
- **Field of** — follow a reference field to *other* items. From a set of scenes,
  "Field of → POV" gives you the POV characters they point at; the **References**
  direction instead gives you what points *back* (backlinks).
- **Highlight** — tint matching rows a colour, to make them stand out in the list.
  (One catch: Highlight needs a real, narrowed set to act on — put it after a
  Filter, not straight onto **All**, or the colour is dropped.)

## Nest — build a tree

**Nest** turns flat lists into a tree by following the links between your lore.
Wire your top-level items into its **parents** input and the candidates into
**children**; Nest attaches each child under the parent it references. Configure:

- the **link field** to follow,
- the direction — **Child → parent** or **Parent → children**, and
- whether to match **By reference** (the actual link) or **By title**.

To go deeper than one level, wire Nest's output back into its own **parents** input
— it recurses down the chain. A second **orphans** output collects any children
that didn't match a parent, so nothing silently disappears.

Example: characters nested under their faction, factions under their region — a
browsable org chart of your world, straight from the reference fields you already
filled in.

## Group the output

Grouping happens on the **View result** node itself, not as a separate box. On it
you can add named **groups** (each is one of the node's input points — drag to
reorder them, and their order is the order they appear). Each group's **Organize** section lets you
choose one or more fields to **group by**, in order, and an **A–Z** toggle for how
the buckets are sorted.

So "draft scenes, grouped by POV character" is: **All** → **Filter** (Status =
Draft) → **View result**, with a group-by of `POV` on the result.

## Parameters — one view, many answers

Instead of hard-coding a Filter's value, you can **promote it to a parameter**:
click the small **Parameter** control on a Filter's value slot. The value then
disappears from the query and reappears in the **Parameters** strip — in the
designer while you build, and above the list whenever the view is used.

This turns "scenes where POV is Honor" into "scenes where POV is **⟨pick one⟩**":
one saved view you point at any character, choosing in the param strip without
reopening the designer. Filter slots — the type, the type-and-subtypes, and field
values — are what you can promote.

## Save, name, and reuse

The designer **autosaves** as you work; there's no save button. A new view starts
titled *"New view"* — rename it by editing the **pane title** at the top of the
view's editor, the same way you'd rename any node. Your saved views then appear in
that pane's **▤ ▾** switcher for good, ready to pick, **✎ Edit**, **⧉ Duplicate**,
or **× Delete**. Like everything else, a view is just a small file in your project
(under `views/`).

## Where to go next

Views reward a little experimentation — duplicate a Default view, add a Filter,
and watch the Preview count change. From here:

- **[Custom fields](#guide:custom-fields)** — the fields you filter and group by
  are yours to define; add the ones your book needs.
- **[Getting started](#guide:getting-started)** — the wider tour, if you skipped
  ahead.
</content>
