# ADR-0047: Feature invocation is an app menu plus contextual actions

- Status: **Proposed** — 2026-07-28 (framed by Anton from the #543 diagnosis; his steering folded in
  the same day: the wizard's AI-key model is canonical, the colour palette and Validate need rework
  not re-homing, the `≡` must be more visible than the app's usual glyphs, and AI-policy/inheritance
  are actions not pane content).
- Feature: #543. Implementation issues filed per slice **on approval** (§Consequences), not before.
- Narrative companion: [`../invocation-model.md`](../invocation-model.md) — the long-form design note
  this ADR crystallises. Read it for the user journeys and the full re-homing walk.
- Follows: ADR-0030 (the quiet-writing-desk design language — invocation is chrome, not furniture);
  the class–instance / `NodeRow` widget taxonomy (the vocabulary contextual actions compose onto).

> **Code references.** This ADR names roles and components, not line numbers. Claims about *current*
> behaviour are true of `4c30885` (2026-07-28); a later reader should re-verify against the tree.

## Context

The app has no decided answer to **"how does a user invoke a feature?"** The only invocation
surface is a handful of buttons in `TopBar.svelte` (Project, Detail Types, Assistants, Layout,
theme, ⚙). Consequences, both surfaced by #543:

- Every feature that needed a trigger and didn't rate its own top-bar button was pushed into the
  **Project pane** (`Project.svelte`) — now carrying identity, cost, Validate, the child roster, AI
  policy, inheritance, Chats, Health Check, Prompts, and Mutations. The pane is a junk drawer
  because it was the only surface with room.
- **Settings** (`MachineSettingsDialog.svelte`) is one long scroll mixing four unrelated concerns
  (storage root, AI credentials, writing-surface prefs, a colour-palette editor), titled "Machine
  Settings" but opening "Your AI subscriptions." It is too hostile to absorb the overflow.

The missing invocation model is **upstream of both** junk drawers: structuring settings before
deciding how features are reached would only relocate the drawer.

## Decision

### 1. Two primary invocation surfaces; scope decides the home

- **An application menu** is the home for **app-global and project-scoped** verbs: open/switch/new
  project, app/machine settings, layout presets, and the project-scoped commands currently scattered
  across the top bar and the Project pane (open project node, Detail Types, Assistants, project
  settings incl. **AI policy and inheritance**, Validate, Health Check, Prompts, Mutations).
- **Contextual actions** (on/beside a selected node or pane, composing the `NodeRow` vocabulary) are
  the home for verbs scoped to **a specific thing** — a scene, a lore entry, a view, a pane.

The load-bearing rule:

> **A verb's scope decides its home. Global/project-scoped → the app menu. Node/pane-scoped →
> contextual actions. Nothing lives in two places.**

This is the single decision that gives both junk drawers an exit: the Project pane keeps what is
*content to look at* (identity, cost, the child roster as navigation); its *actions* move to the
menu or to contextual actions per scope.

### 2. The menu is a single, deliberately-visible `≡` button

Anchored top-left near the wordmark. It is the **one exception** to the app's otherwise-quiet glyph
treatment: as the primary way into every command it must read as *more visible* than the app's usual
faint icons — an affordance, not another whisper.

### 3. Settings is a consequence, restructured by concern

Reached from the menu, retitled honestly, organised into **AI / Appearance / Storage** instead of
one scroll:

- **AI** adopts the **New Project wizard's provider-subscription model as the single way to handle
  keys**. The flat password-list in `MachineSettingsDialog` is retired; the two API-key surfaces
  collapse to one — the wizard's.
- **Appearance** holds text size, alignment, indent, theme (its setting finally gets a home; the
  quick-toggle stays in the chrome), and a **reworked, compact colour palette** (see §5).
- **Storage** is the single canonical projects-folder editor; the wizard's duplicate root-picker
  points at it rather than forking a parallel copy.

### 4. Validate is unbundled into an integrity check and document import

Validate is the odd one out — not an action or a configuration but **two separable concerns fused**:
it sanity-checks the project's data (files/nodes are the source of truth and the user may hand-edit
them, so an integrity pass is a real need) **and** it is the app's document-import vehicle. Its
rework splits them: the integrity check becomes a project action; **document import becomes its own
feature with its own discoverable home** — a headline 0.8.0 item (Markdown import) that no one would
find behind a "Validate" button. The import feature itself is tracked separately and **not designed
here**.

### 5. The colour palette is reworked, not merely re-homed

At its current size the palette editor is unalignable with almost any menu/settings layout, so a
**compact rework is a prerequisite** to it living in the Appearance tab. Its finished shape is a
separate design problem; this ADR decides only that it belongs in Appearance.

### 6. A command palette is out of scope

A `Ctrl-K`-style palette scales at near-zero visual weight but is undiscoverable for a prose
audience, so it is **not** a primary surface. It is recorded only as a *possible later layer over the
same command set*, and **no mechanism is reserved for it now** (ADR failure pattern P4 — build
nothing for a surface that doesn't exist).

## Rejected alternatives

- **Palette-first (Ctrl-K as primary).** A novelist won't discover invisible commands; it optimises
  for the power user this app is not for.
- **Keep growing top-bar buttons.** The status quo that produced the problem — a 40px strip already
  mixing five concerns.
- **A pane per feature area.** Panes are for content you dwell in, not command surfaces; this
  relocates the cramming from one pane to several.
- **Tidy the Project pane in place.** Treats the symptom, leaves the missing invocation model
  unaddressed, and the next feature re-crams the pane.
- **A light menubar (File/Project/View…).** Reads heavier than the writing-desk language wants; the
  single `≡` carries the same commands more quietly.

## Consequences

- The Project pane loses its action sections (they become menu/contextual actions) and keeps
  identity, cost, and the child roster.
- The top bar sheds its middle cluster (Project / Detail Types / Assistants / Layout) into the menu;
  navigation (wordmark, breadcrumb, switcher) and the theme quick-toggle stay.
- Three current duplications collapse to single homes once there is a canonical place to point at:
  the projects-folder editor (settings **and** wizard), the "Contains" child roster (switcher **and**
  Project pane), and the inheritance declaration (breadcrumb→pane **and** wizard).
- **Slicing** — one lane, vertical slices, each its own issue filed only when the last lands:
  1. App-menu shell + command set — re-home the existing top-bar buttons, no new features (proves
     the model at low risk).
  2. Settings redesign (AI / Appearance / Storage; AI keys unify to the wizard model) — with
     **2a. colour-palette rework** as a self-contained prerequisite.
  3. Project-pane de-cramming — move action sections per scope; **unbundle Validate** into integrity
     check + separately-surfaced document import.
  4. De-duplication (projects-folder, "Contains", inheritance).

## Open

- **Modal vs. pane for a given surface is deliberately unresolved and may vary from place to place**
  (settings might be a pane, a lighter action a modal). Decided per surface at its slice, not
  globally here.

## Amendments

### 2026-08-30 — layout presets rejoin the chrome as a quick-toggle (#1651)

§1 filed **layout presets** in the app menu as a project-scoped verb, and §Consequences shed the
top bar's "Layout" button into the menu — while §3/§Consequences kept **the theme quick-toggle in
the chrome**. In practice that split the two like-for-like presentation controls: theme (a quick
flip a writer makes often) stayed a chrome affordance, while layout (the same kind of quick flip
between workspace arrangements) became a verb buried under ten project commands.

The refinement: **layout presets are a presentation quick-toggle in the same class as the theme
toggle**, so they earn the same treatment — their own compact popover in the chrome, immediately
beside the theme toggle, and out of the ≡ menu entirely.

This does **not** loosen the load-bearing rule. A verb's scope still decides its home, nothing lives
in two places, and the ≡ menu remains the single home for verbs. What changed is the *classification*
of layout presets: they are presentation state, not a command — the same reasoning that already
exempted the theme quick-toggle to the chrome. The full arrangement of layout (save/reset/named
presets) rides along in the popover so the control stays whole rather than being split between chrome
and menu.
