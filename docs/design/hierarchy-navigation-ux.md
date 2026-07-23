# Hierarchy navigation UX — the two relations, the three lists, and the declaration step

> **Status: design, undecided.** Companion to **ADR-0039 Amendment 3** (Proposed), which asks whether
> the inheritance declaration is read transitively. Everything in §1 and §3 holds under **either**
> answer; §2 and §4 mark the places the answer changes something. Verified against `origin/master`
> at **`f743203`**, 2026-07-23. Nothing here is implemented, and nothing here touches PR #420.
>
> Governing memos: `decisions_ui_widget_taxonomy` (list/row treatments), `decisions_design_language`
> (§3 composition law, §4 the closed glyph lexicon and the separate annotation vocabulary),
> ADR-0044 §J (*a glyph marks what is true about the value; colour marks what is true about the view*).

## 1. The premise: three relations, currently two controls, currently one row treatment

An open project sits in three different relations to other projects, and the app conflates them.

| relation | question it answers | source of truth | can the target fail to open? |
|---|---|---|---|
| **Inherits from** | *what canon do I see?* | this project's declaration (+ its ancestors', if Amendment 3 is adopted) | no — filtered to folders with a manifest |
| **Contains** | *what is inside me?* | the filesystem (`_project_children`) | no — same filter |
| **Recently opened** | *where have I been?* | machine-global MRU in `%APPDATA%` | **yes** — #423 |

The first two are **structural**: they are properties of the shelf, they are verified against disk at
read time, and every target is guaranteed to open. The third is **historical**: it is a property of
this machine's past, it is not verified, and its rows go stale (#423 is exactly that). They currently
share one dropdown and one row treatment, which is why they read as one list — and why a stale recent
was reachable by a click that was aiming at a breadcrumb.

**The demarcation rule, stated once:**

> **Structure is chrome; history is a menu.** The chain and the roster are always-visible, always-live
> relations of the open project, and they render as *path* and *roster*. Recents is a machine
> convenience about the past, it renders as a *menu of worded actions*, and it never shares a section,
> a row treatment, or a trigger with either structural list.

Three consequences, each of which is a concrete change:

1. **Different triggers.** The path and its per-level roster belong to the crumbs; Recent / Open
   folder… / New project… belong to the identity button. Today the identity button opens a menu whose
   first section is Recent, which is what makes a one-crumb path read as a breadcrumb you can expand.
2. **Different row content.** A structural row is *title only* (+ its relation, when ambiguous): a
   child needs no path — it is inside you — and an ancestor needs no timestamp. A historical row keeps
   the path and the relative time it already renders (`TopBar.svelte:207-211`), because for history
   *which one and when* is the whole question.
3. **Different failure vocabulary.** A structural row cannot be dead. A historical row can, so it is
   the only one that gets a *missing* state and a remove affordance — which is #423's fix and is also
   what stops the two lists from ever being interchangeable again.

## 2. The breadcrumb (assumes #311 / PR #420 has landed; does not modify it)

`The Honorverse › Honor Harrington › [● On Basilisk Station ▾]`

**Unchanged from #420:** the path is the resolution-scope selector, not ADR-0042's authoring-layer
picker; it renders declared ancestors outermost-first with their manifest titles; it scrolls rather
than eliding; gaps stay legal so it is a path through the ancestry, not a walk of consecutive folders.
The `›`-in-the-lexicon question and the scroll-vs-elide question are #420's and are not re-opened here.

Three additions this design asks for:

**(a) An empty chain must say so.** Today a project that declares nothing renders no path, and the
lone identity button then reads as a one-item breadcrumb — the click that started this. The fix is an
explicit, quiet affordance in the path's place: `Inherits from nothing · set up…`, in `--text-muted`,
opening the declaration editor (§4). It states the model rather than looking like a rendering gap, and
it is the single highest-value change here, because after #318's default it will be **rare** — which
is exactly when an unexplained blank is most misread.

**(b) Each crumb carries that level's roster.** #420 already puts the *current* level's children in
the switcher menu (agreed while sizing, as a workaround for #417). Generalise it: a crumb's `▾` opens
that level's **Contains** roster, so descent is available from any level on the path without first
navigating to it. This is the round-trip fix, and it is a UI fix — it does not require descent and
ascent to be the same relation.

**(c) Under Amendment 3 only: the path may contain levels you did not choose.** *Recommended: do not
mark them in the bar.* The breadcrumb answers "where am I", and every crumb on it is equally really in
the chain; *how it got there* is a question about the declaration, and it belongs where the
declaration is edited (§4) and in the crumb's `title` tooltip (`Honorverse — implied via Honor
Harrington`). Two reasons to resist a visible mark: the glyph lexicon is closed and a crumb is an
affordance rather than a value, so the mark would have to be colour — and ADR-0044 §J reserves colour
for what is true about the *view*. Declared-vs-implied is true about the chain.

> **Option for Anton, if you want it visible anyway:** render implied crumbs in `--text-muted` and
> declared crumbs at normal weight. Cheap, readable, and it spends the colour axis on a value
> property — a small, deliberate exception to §J rather than an oversight. Say which.

## 3. The switcher, split

Today: one button → one menu → `Recent` section, then `Open folder…`, `New project…`, with #420
adding children into the same menu.

Proposed:

```
[ ● On Basilisk Station ▾ ]        ← identity + history
   ─────────────────────────
   Recent                          ← historical rows: title · …/path · 3d ago · ×
     Honor Harrington   …/honorverse/honor-harrington   3d ago
     ⚠ Honorverse       …/worktrees/…/honorverse        6d ago   (missing — × to remove)
   ─────────────────────────
   Open folder…
   New project…
```

```
Honor Harrington ▾                 ← a crumb: structure, for that level
   Contains
     On Basilisk Station
     The Honor of the Queen
   Inherits from
     The Honorverse
```

The identity button keeps history and the two worded actions and **loses** the child roster. Each
crumb gains a roster with **both** structural relations named — which is what makes the asymmetry
legible instead of confusing: *Contains* is what is inside this folder, *Inherits from* is what this
level declared, and a reader can see at a glance that the second is shorter than the first and why.

Row treatment, per the composition law: these are `NodeList` + `NodeRow` surfaces (a project *is* a
node kind), not bespoke menus. Structural rows carry the project colour dot the identity button
already uses; historical rows do not — the dot is a property of an open project, and a stale recent
may have none.

**The `⚠`/missing state and the `×` remove affordance on a recent row are #423's**, listed here only
to show where they land once the two lists stop sharing a treatment.

## 4. The declaration step in the create-project wizard (#318)

The wizard is where the declaration is made (ADR-0039 Amendment 1) and it is also where an author
learns that hierarchies exist. It reads `ProjectInfo.ancestors` — the whole enumeration with flags,
which is already on the wire and already shaped for exactly this (`models/project.py`, and the
`_ancestor_candidates_for_api` docstring says so).

**The step, non-transitive model.** One row per enumerated ancestor, outermost first, checkboxes:

```
Inherits from

  ☑ Shelf                     — not a project · organisational folder      (disabled)
  ☑ The Honorverse            — 1,240 lore entries · 8 prompts · 3 views
  ☑ Honor Harrington          — 312 lore entries · 2 views
  ─ this project ─
```

Three row states, which is the enumeration's own model: *project + declared* (ticked), *project +
available* (offerable), *not a project* (shown, disabled, and explaining itself — its presence is a
quiet warning that a folder up there is not what the author assumed).

**Under Amendment 3, a fourth state: implied.** Ticked, not editable, attributed:

```
  ☑ The Honorverse            implied · via Honor Harrington
  ☑ Honor Harrington          — 312 lore entries · 2 views
```

Attribution is the whole point of the row: without it, ticking one box makes two appear and the author
has no way to learn why. Unticking an implied row is deliberately **not** an affordance, because
Amendment 3 recommends against an `excludes:` key — the row's job is to explain, and the way to change
it is to untick the level that implies it. If that reads as a dead end in review, that is the honest
signal that exclusion is wanted after all, and it belongs in the amendment rather than in a wizard.

**The default is the fix for the empty-breadcrumb defect, and it is the cheapest change on this page.**
`create_project` writes no `inherits` today, so *every* project is flat.

- Non-transitive: pre-tick **every** ancestor project. Anything less makes the common shelf require
  N ticks, and the wizard should default to the shape the folder layout already implies.
- Transitive: pre-tick the **nearest** ancestor project; the rest arrive implied.

Either way the author sees a filled-in chain they can uncheck, rather than an empty one they must
discover. This requires `inherits` on `CreateProjectRequest` and a write in `_new_project_manifest`
— which is the smallest complete fix and does not wait for the wizard.

**Editable afterwards, in the same component.** ADR-0039 already requires it and
`UpdateProjectSettingsRequest.inherits` already carries it (`None` leaves alone, `[]` clears). Project
settings renders the identical row list; creating a book before its universe exists is normal, and the
"set up…" affordance from §2(a) lands here.

**The contribution counts are the part to cost before promising.** #318 asks for *"Honorverse — 1,240
lore entries, 3 views"* rather than bare paths, and it is the right instinct: the counts are what
teach the author what a tick *does*. But an exact count per candidate means an index build per
candidate, which is a per-keystroke cost in a modal. **Recommended: a cheap file count** — entries in
that layer's `lore/`, `prompts/`, `views/` — computed once when the step opens, labelled as an
approximation by being phrased as sizes rather than totals. If exact counts are wanted, they are a
separate endpoint and they wait for the #392 memo.

## 5. What this design does *not* settle

- **The mark for declared-vs-implied**, if Anton wants one in the bar (§2c) — it would want to be
  taken with #304 rather than beside it.
- **#417.** Descent from a crumb (§2b) makes the child roster reachable without the Project pane,
  which removes the *urgency* but not the defect: the pane can still vanish with no targeted opener,
  and the general fix is still option 3 in that issue.
- **#423's mechanics** — marking vs pruning, and whether the open path reports a 404 on a recent
  rather than only raising. This design says only that recents is the one list allowed to have a dead
  row, and therefore the one that needs the vocabulary for it.
