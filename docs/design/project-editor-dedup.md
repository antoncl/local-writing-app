# Design note: de-duplicating the project editors (slice 4)

This is ADR-0047 **slice 4**, the last slice of the invocation model. Slices 1–3
gave every project verb one home. Three *editors* still appear in two places
each; this slice collapses each to a single home. Design language from
`docs/design/invocation-model.md`; the three duplications are named in the ADR
(`docs/design/adr/0047-feature-invocation-is-an-app-menu-plus-contextual-actions.md`,
§Consequences).

## 1. Why this exists — the diagnosis

Three editors are rendered twice. They are **not the same kind of duplication**,
so they do not get the same fix.

| Editor | Home 1 | Home 2 | Nature |
|---|---|---|---|
| **"Contains" child roster** | TopBar switcher (`TopBar.svelte`) | Project pane (`Project.svelte`) | same read-only navigation, **two live surfaces at once** |
| **"Inherits from" declaration** | Project pane Inheritance section (PATCH-saved) | New-project wizard, location step (committed at create) | **one editor, two lifecycle moments** |
| **projects-folder picker** | Settings → Storage tab | New-project wizard, root step (first-run only) | **one editor, two lifecycle moments** |

The inheritance and projects-folder pairs are **hand-copied widgets that appear
at both create-time and configure-time**. Neither copy is deletable: before a
project exists, first-run must still set the machine root and declare the new
project's ancestry. The wizard's inheritance code even self-documents the hazard
— *"Mirrors the post-hoc declaration editor"* — which is precisely the drift a
copy invites. The fix is not to delete a copy but to **extract one shared
component and mount it in both moments** — the ADR's own phrasing for the
projects-folder case: the wizard's picker should *point at* the canonical editor
"rather than forking a parallel copy."

The "Contains" pair is different: **both copies are read-only, click-to-open
navigation** over the same `project.children` data, shown simultaneously. Neither
edits containment. Here "single home" can mean genuinely picking one surface.

## 2. Intent and anti-goals

**Intent.** Each of the three editors has exactly one home. The two create-time /
configure-time editors are one component the wizard and the dashboard both mount;
the child roster lives in one place, chosen by what navigation each surface owns.

**Anti-goals.**

- **No new containment editing.** "Contains" stays read-only navigation; this
  slice does not add "add/remove child project" anywhere. That is a separate
  feature if ever wanted.
- **No change to how anything saves.** The inheritance editor keeps its two save
  paths (wizard commits at create; the pane PATCHes post-hoc). The
  projects-folder picker keeps its one field and one endpoint. Extraction is
  UI-only.
- **Don't disturb the slice-3 Inheritance grouping.** The pane's "Inheritance"
  section keeps AI policy grouped beside the declarations, and AI policy keeps
  its explicit fails-closed apply (`memory/decisions_ai_permission_fails_closed.md`).
  The shared component is the declaration checkbox list only — not the whole
  section, not the policy.
- **No wizard-step removal.** First-run still sets root and declares ancestry in
  the wizard; those steps simply render the shared components.

## 3. The design

### 3a. "Contains" → the Project pane; drop it from the switcher

Cross-project navigation already decomposes cleanly by *relationship*, and each
relationship wants exactly one home:

- **up (ancestors)** → the breadcrumb
- **down (children)** → the Project pane's "Contains" roster
- **sideways (recent / unrelated)** → the switcher's "Recent" list

The child roster is removed from the switcher; the Project pane becomes its sole
home. This honours the ADR's most explicit line — *"the Project pane … keeps
identity, cost, and the child roster"* — and leaves the switcher exactly what its
neighbours make it: the jump-to-a-recent-project dropdown. To descend into a
child you focus the Project pane (a persistent workspace pane, always a glance
away) rather than the transient dropdown.

*Considered and rejected:* keep "Contains" in the switcher and drop the pane's
roster. Defensible — it keeps all cross-project *jumping* in one dropdown — but it
fights the ADR's assignment of the roster to the pane, and a project dashboard is
the natural place to read "what is inside this project."

### 3b. "Inherits from" → one shared declaration editor

Extract the declaration checkbox list (over `declarationRows`, currently mirrored
in `Project.svelte` and `CreateProjectWizard.svelte`) into one controlled
component. The host supplies the candidate rows and a toggle callback; the
component renders the list and its checked state. The Project pane mounts it
inside the slice-3 **Inheritance** section, above the AI-policy fieldset, and
wires the toggle to the post-hoc PATCH. The wizard mounts the same component in
its location step and wires the toggle to its create-time local state. AI policy
is **not** part of the shared component — only the pane has it, and it keeps its
own explicit apply.

The breadcrumb "set up…" launcher is untouched: it reveals the Project pane's
Inheritance section, which is still the post-hoc home.

### 3c. projects-folder picker → one shared component, Storage is canonical

Extract the picker (the folder text input + **Browse…** + **Clear** +
`DirectoryPickerModal` wiring) into one controlled component. The Settings →
Storage tab is the canonical, always-available editor; the wizard's first-run
root step mounts the **same component** instead of its parallel copy. Both write
the identical `default_projects_folder` field through the identical machine-
settings endpoint (they already do — only the widget is duplicated), so this is a
pure UI extraction with the existing save paths behind it.

## 4. User journeys (the model, walked)

- *"What's inside this universe?"* → Project pane → **Contains** → click a book to
  open it. (The switcher no longer answers this — it answers "jump to something
  recent.")
- *"This new book is part of my series."* → wizard → location step → tick the
  series under **Inherit from** — the same control, glyph-for-glyph, that the
  Project pane shows after the project exists.
- *"Change where my projects live."* → Settings → **Storage** → the one
  projects-folder editor; the wizard shows that same editor the first time only.

## 5. Scope boundary

- This is the final ADR-0047 slice; it adds no new features, only removes
  duplication left by slices 1–3.
- The shared-component extractions here are siblings of the chip/inline-form
  extraction tracked in #619 and the tab-style convergence in #610 — the same
  "converge on one primitive" theme, scoped to the hierarchy editors.

## 6. Slicing

Three streams, disjoint files, sequenced one lane at a time:

1. **Contains** (frontend only) — delete the switcher's "Contains" section; the
   Project pane is the sole home. The only stream that carries the placement
   call above.
2. **Inherits-from editor** (frontend only) — extract the shared declaration
   list; mount it in the pane's Inheritance section and the wizard location step.
3. **projects-folder picker** (frontend only) — extract the shared picker; mount
   it in the Storage tab and the wizard root step.

## 7. Settled, and what's still open

Settled: "Contains" lives in the Project pane; inheritance and projects-folder
each become one shared component mounted at create-time and configure-time;
Storage is the canonical projects-folder home; the slice-3 Inheritance grouping
and the fails-closed AI-policy apply are preserved.

Deliberately unchanged: no containment editing, no save-path changes, no wizard
steps removed. Placement is reversible — a surface that reads wrong in use can
move.
