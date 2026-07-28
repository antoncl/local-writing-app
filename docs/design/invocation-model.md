# Design note: how the app invokes features (#543)

- Status: **Proposal for direction** — not accepted, no ADR number yet. Graduates to ADR-0047
  once the model in §3 is settled. Nothing here is a work order; §5 (re-homing) is *illustration
  of the consequence*, not a committed mapping.
- Framed from the #543 diagnosis Anton stated: the issue has **two root causes**, not one surface to
  tidy.

> **Code references.** Behaviours are named by component/symbol, not line, and are true of `4c30885`
> (2026-07-28). A later reader should re-verify against the tree, not this note.

## 1. Why this exists — the diagnosis

#543 reads as "the settings dialog and the top-left project menu are unfriendly." That is the
*symptom*. The two causes underneath it:

1. **The app never decided how a feature gets invoked.** The only invocation surface is a handful of
   buttons in `TopBar.svelte` (Project, Detail Types, Assistants, Layout, theme, ⚙). There is no
   general answer to *"where does a command live?"* — so every feature that needed a trigger and
   didn't rate its own top-bar button got shoved into the **Project pane** (`Project.svelte`), which
   is why that pane now carries identity, cost, Validate, inheritance, the child roster, AI policy,
   Chats, Health Check, Prompts, and Mutations. The pane isn't overloaded through bad discipline;
   it was **the only surface with room**.

2. **Settings — project and machine — are genuinely user-hostile,** so they can't be the relief
   valve either. `MachineSettingsDialog.svelte` is one long scroll mixing four unrelated concerns
   (filesystem root, AI credentials, writing-surface prefs, a colour-palette editor), titled
   "Machine Settings" but opening with the line "Your AI subscriptions." You cannot move the
   crammed-in things "into settings" until settings is something worth moving into.

The order matters: **cause 1 is upstream of both junk drawers.** Deciding settings' structure before
deciding how you *reach* settings — and everything else — just relocates the drawer. So this note
settles the invocation model first, and treats the settings redesign and the Project-pane
de-cramming as **consequences** of it.

## 2. Intent and anti-goals

**Intent.** Give the app one predictable answer to "how do I invoke a feature," such that (a) a
writer can find any command without hunting, (b) the Project pane and the settings scroll each have
a place to shed what doesn't belong, and (c) the answer stays quiet enough for the *writing-desk*
design language (ADR-0030): invocation is chrome, not furniture.

**Anti-goals** — things this note is explicitly *not* trying to do, so a later thread doesn't drift
into them:

- **Not** a redesign of any individual feature's UI (the snapshot strip, the view designer, the
  create wizard), and **not** the design of the document-import feature itself — only the
  recognition that import must stop hiding behind Validate and get its own home. Only *where and how
  you invoke* features.
- **Not** a command-line/DSL power surface. The audience is a novelist, not an IDE user.
- **Not** a keyboard-shortcut scheme. Accelerators can layer on later; they are not the model.
- **Not** a re-plumbing of *what* each feature does or where its data lives (machine-vs-project
  split is already clean on the data axis; only the *surfacing* is tangled).
- **Not** a migration concern — pre-1.0, no compatibility shims.

## 3. The decision — the invocation model

A writer holds roughly five mental buckets: *which project am I in* (navigation), *act on this
project*, *act on this thing I've selected*, *how the app looks/behaves* (settings), *arrange my
workspace* (layout). The model maps invocation onto those buckets with **two primary surfaces plus
one deferred accelerator**:

### 3a. A primary **application menu** — the home for global and project-scoped commands

A **single `≡` app-menu button** anchored top-left near the wordmark. Chrome decision: it is the one
deliberate exception to the app's otherwise-quiet glyph treatment — as the primary way into every
command it must be **more visible than the current glyph usage**, not another faint icon. A light
menubar (File/Project/View…) was considered and rejected: it reads heavier than the writing-desk
language wants. The menu is the one place that answers "what can I do right now," organised by
bucket:

- **App / machine settings** — appearance, AI credentials, storage root (§5).
- **Navigation** — open/switch project, new project, layout presets.
- **This-project actions** currently scattered as top-bar buttons and Project-pane sections: open
  the project node, Detail Types, Assistants, **project settings (AI policy, inheritance)**,
  Validate, Health Check, Prompts, Mutations. Project-scoped *settings* — AI policy and inheritance —
  are **actions on the menu, not pane content**.

This is the single decision that gives *both* junk drawers an exit. The Project pane keeps what is
genuinely **content to look at** (identity, cost breakdown, the child roster as navigation); the
**actions** move to the menu.

### 3b. **Contextual actions** — the home for commands scoped to a selected node/pane

Operations that act on a *specific* thing (a scene, a lore entry, a view, a pane) belong on or
beside that thing — a row action / context affordance — not in a global menu where they'd be
disabled 90% of the time. This is where much of the Project pane's node-scoped machinery actually
belongs, and it composes with the existing `NodeRow` vocabulary
(`decisions_ui_widget_taxonomy`).

The division of labour is the load-bearing rule:

> **Global and project-scoped verbs → the app menu (3a). Node/pane-scoped verbs → contextual
> actions (3b).** A verb's scope decides its home; nothing lives in two places.

### 3c. A **command palette** — deferred accelerator, not part of this decision

A `Ctrl-K`-style palette scales endlessly at near-zero visual weight, but discoverability is poor
for a prose audience, so it is **not** the primary surface. Recorded here only to state it is a
*possible later layer over the same command registry*, and **explicitly out of scope** for #543. No
mechanism is reserved for it now (per ADR failure pattern P4 — don't build for a surface that
doesn't exist).

### 3d. Rejected alternatives

- **Palette-first** (Ctrl-K as the primary surface). Rejected: a novelist won't discover invisible
  commands; it optimises for the power user this app isn't for.
- **Keep growing top-bar buttons.** Rejected: it's the status quo that produced the problem; the bar
  is a 40px strip already mixing five concerns.
- **A second/third pane per feature area.** Rejected: panes are for *content you dwell in*, not
  command surfaces; it would relocate the cramming from one pane to several.
- **Leave actions in the Project pane, just tidy them.** Rejected: it treats the symptom, leaves
  cause 1 unaddressed, and the next feature re-crams the pane.

## 4. User journeys (the model, walked)

- **"I want to work on a different book."** App menu → Recent / Open / New. (Today: top-left
  switcher ▾ — this part already works and is *kept*, folded under the menu's navigation bucket.)
- **"I want to change my AI key / text size / theme."** App menu → Settings → the right tab (§5).
  One door, predictable interior.
- **"I want to edit this lore entry's fields with AI"** (or rename it, snapshot it, delete it).
  Contextual action on the entry's row/editor — never a global menu item.
- **"I want to see this project's cost / who it inherits from."** Project pane — it stays the place
  you *look*; the *actions* it used to host (Validate, Health Check, Prompts…) moved to the menu.
- **"I want the Research layout."** App menu → Layout presets (today's `Layout ▾`, rehoused).

## 5. Consequence — where today's crammed surfaces land

*Illustrative, to prove the model absorbs the mess — not a committed per-item mapping. The exact
groupings are settled per slice in §6.*

**Settings** (the #543 half named first) becomes a properly-structured surface reached from the app
menu, retitled honestly, organised by concern instead of one scroll:

- **AI** — provider subscriptions, adopting the **wizard's add-a-provider model as the single way to
  handle keys**. The flat password-list in `MachineSettingsDialog` is retired; today's two API-key
  surfaces collapse to one — the wizard's. Ollama host lives here too.
- **Appearance** — text size, paragraph alignment, first-line indent, theme (its setting finally
  gets a home; the quick-toggle can stay in the chrome), and a **reworked** colour palette. The
  palette is *not* a simple re-home: at its current size it is unalignable with almost any layout we
  might pick, so a compact rework is a **prerequisite** to it living here (§6).
- **Storage** — the projects folder / inheritance root, as the single canonical editor (the New
  Project wizard's duplicate root-picker links to it rather than forking a parallel copy).

**Two items need rework, not just re-homing:**

- The **colour palette** — too large to align with any menu/settings layout until it's made compact.
- **Validate** — the odd one out. Where the other entries are actions or configurations, Validate
  today **bundles two separable concerns**: it *sanity-checks the project's data* (files/nodes are
  the source of truth and the user may hand-edit them, so an integrity pass is a real need), **and**
  it is the app's **document-import vehicle**. Its rework is an *unbundling*: the integrity check is
  a project action; **import is its own feature** — a headline 0.8.0 item (Markdown import) that no
  one would find hidden behind a "Validate" button, so it earns a discoverable home of its own.

The invocation model decides only *that* these are surfaced here, not how they finally look — each
is its own small design problem.

**Top bar** sheds its middle cluster: Project / Detail Types / Assistants stop being loose buttons
and become menu entries under "this project"; Layout presets move under the menu; navigation
(wordmark, breadcrumb, switcher) and the theme quick-toggle stay.

**Project pane** keeps identity, cost, and the child roster (content/navigation); its action
sections (Validate, Health Check, Prompts, Mutations, AI policy, inheritance setup) move to the menu
or to contextual actions per their scope (§3b).

**De-duplication that falls out for free:** the projects-folder editor (today in *both* settings and
the wizard), the "Contains" child roster (today in *both* the switcher and the Project pane), and
the inheritance declaration (today in *both* the breadcrumb→pane and the wizard) each collapse to one
home once there's a canonical place to point at.

## 6. Slicing

One work lane, vertical slices, each its own issue filed only when the last lands
(`feedback_vertical_slices_one_issue_at_a_time`). Provisional order — the app menu comes first
because it's the surface everything else sheds *into*:

1. **The app menu shell + command registry** — the invocation surface itself, initially just
   re-homing the existing top-bar buttons (Project, Detail Types, Assistants, Layout) with no new
   features. Proves the model end-to-end with minimal risk.
2. **Settings redesign** — restructure `MachineSettingsDialog` into AI / Appearance / Storage,
   reached from the menu, retitled. **AI keys unify to the wizard's provider model** here (the
   settings password-list is retired). Depends on the palette rework (2a) before Appearance can host
   it.
   - **2a. Colour-palette rework** — a compact, alignable palette editor. Prerequisite for slice 2's
     Appearance tab; self-contained, so it can proceed in parallel.
3. **Project-pane de-cramming** — move its action sections (Validate, Health Check, Prompts,
   Mutations, AI policy, inheritance) to the menu / contextual actions per scope; the pane keeps
   identity, cost, and the child roster. **Validate is unbundled here** into a project-data
   integrity action and a separately-surfaced **document import** (the import *feature* itself is a
   headline 0.8.0 item tracked on its own, not designed in this note).
4. **De-duplication** — collapse the projects-folder, "Contains", and inheritance editors to single
   homes.

Sequencing is governed by **file contention** as much as dependency: slice 1 is mostly
`TopBar.svelte` + a new menu component + a registry; slice 2 is `MachineSettingsDialog.svelte`;
slice 3 is `Project.svelte`. Largely disjoint, so they *could* interleave — but one lane, so they
sequence.

## 7. Settled, and what's still open

Folded in from review:

- **Menu chrome:** single `≡` button — but **more visible than the app's current glyph usage** (it's
  the primary way in); menubar rejected.
- **AI keys:** the **wizard's** provider model is canonical; the settings password-list is retired.
- **Project pane's borderline bits:** AI policy and inheritance **are actions** (menu), not pane
  content. The pane keeps identity, cost, and the child roster.
- **Palette and Validate need rework, not just re-homing** (§5) — each its own small design problem.

Still genuinely open:

- **Modal vs. pane** for a given surface — **deliberately unresolved, and may vary from place to
  place**: settings might be a pane, a lighter action a modal. Decided per surface at its slice, not
  globally here.
