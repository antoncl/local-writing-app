# Design note: de-cramming the Project pane (#626)

This is ADR-0047 **slice 3**. It applies the invocation model from
`docs/design/invocation-model.md` to the surface that motivated it most: the
Project pane, root cause #2 of #543 — the app had no invocation model, so the
Project pane became the junk drawer every project-scoped verb was dropped into.

## 1. Why this exists — the diagnosis

The Project pane (`frontend/src/components/panes/Project.svelte`) is two
different things wearing one coat:

- **A project dashboard** — state you cannot read anywhere else: identity
  (title/path), the inheritance chain ("Inherits From"), the child roster
  ("Contains"), running cost, the AI policy, and the *results* of the
  health and validation checks.
- **A pile of action buttons** — verbs that landed here for lack of a home:
  `Validate`, `Chats…`, `Prompts…`, `Mutations…`, `Health Check`,
  `Save AI Settings`, plus two hidden *inside* a result panel
  (`Repair TODO Links`, `Add to Manuscript`). The panes that carry verbs —
  Lore, Prompts, Mutations, Assistants, Chats, TODO — do so through a
  **header-actions cluster**; the Project region has none, and pushed its verbs
  into the body instead.

**"Validate" is itself two-headed.** One button does two unrelated jobs:

1. a **data-integrity check** — sanity-checks the on-disk project, which is
   legitimate and permanent because the files are the source of truth and the
   user may hand-edit them (`services/project/lifecycle.py::validate_project`);
2. a **document-import vehicle** — the check's result surfaces loose scene files
   (including `.md` files dropped into `scenes/`) and offers to adopt them into
   the manuscript (`services/project/manuscript.py::import_loose_scenes`).

In code the two heads are already *mostly* apart — separate endpoints, separate
service mixins, separate return types; import even re-derives its own loose set.
They are joined in only three places: the `ProjectValidation.loose_scenes`
field, the single shared `.validation-panel` section in the pane, and the
frontend habit of re-running validate to refresh the import offer.

## 2. Intent and anti-goals

**Intent.** Every project verb has one obvious home decided by *scope*, and the
Project pane becomes a dashboard you *read* rather than a control panel. Validate
stops being a two-headed button.

**Anti-goals.**

- Not shuffling buttons around inside the pane — the point is the invocation
  model, not a tidier junk drawer.
- Not folding the integrity check into save-on-change or a migration; it is an
  explicit, user-invoked check *because* the files are hand-editable.
- Not designing the richer Markdown-import feature here. This slice only
  *unbundles* the loose-scene import that already exists and gives it a home;
  its evolution (drag-drop, external files, previews) is a separate feature.
- Not touching the "Contains" / "Inherits From" duplication against the TopBar
  switcher — that de-dup is slice 4.

## 3. The design

One rule places every verb:

> **The app menu is where you navigate to things; a pane's own header is where
> you act on what that pane shows; machine- and provider-level concerns live in
> the AI Settings tab, never per-project.**

### 3a. Where today's Project-pane controls land

| Control today | Home | Rationale |
|---|---|---|
| `Chats…` · `Prompts…` · `Mutations…` | ≡ app menu → **This project** | They open *other* panes — pure navigation, same shape as Assistants / Detail Types, already there. |
| `Validate` · `Repair` | **Project-pane header actions** (new) | They act on, and report about, *this* project; the result renders in the dashboard body, so trigger and result stay together. |
| `Health Check` | **AI Settings tab**, beside the provider chips | It pings the default assistant's provider to prove the connection works — a machine/provider check with nothing project-specific in it. |
| AI policy + its apply | **grouped with "Inherits From"** in the dashboard | See 3b. |
| Loose-scene import | **app menu → "Import documents…"** | See 3c. |
| Identity · Contains · cost · check results | stays — dashboard content | This is what the pane is *for*. |

### 3b. AI policy joins the Inheritance block

AI policy's headline option is **"inherit"** — defer to the ancestor chain
(#471) — so it is an inheritance-flavoured, **per-project** setting, the same
shape as the "Inherits From" declarations. It belongs beside them, as one
**Inheritance** block in the dashboard.

It deliberately does **not** move to the AI Settings tab: that surface is
**per-machine** (provider keys shared by every project), and a per-project policy
shown there would read as machine-wide. (The AI Settings tab is exactly where
the machine-scoped `Health Check` goes, for the mirror-image reason.)

The policy keeps an **explicit apply** — it is a permission/privacy control (may
this project reach the cloud?), and a permission control must never fold into
save-on-change (`memory/decisions_ai_permission_fails_closed.md`). It is not the
same data as, and is not persisted by, the machine Settings dialog.

### 3c. Unbundling Validate into integrity and import

- **Integrity** stays a Project-pane action (`Validate` / "Check project" in the
  new header), result in the dashboard body; `Repair` stays paired with it.
- **Import** becomes its own minimal surface — an **"Import documents…"** action
  in the app menu (project-scoped, deliberately out of the day-to-day pane
  because it is used rarely, roughly once at project start) that lists the loose
  scenes with per-item select and Add.
- `loose_scenes` comes **off** `ProjectValidation`; a dedicated **read** endpoint
  enumerates loose scenes so import no longer piggybacks on the integrity scan.
  The model change is a clean pre-1.0 break — no migration.
- Import stays deliberately minimal; the richer feature is future work.

## 4. User journeys (the model, walked)

- *"Is my project well-formed?"* → **Check project** (Project-pane header) →
  issues and warnings in the dashboard; **Repair** if offered.
- *"I dropped three `.md` chapters into the folder."* → app menu →
  **Import documents…** → tick them → Add. Import is a thing you go *do*, not a
  side effect of validation, and it doesn't clutter the daily surface.
- *"Open the chats."* → app menu → **Chats** — the same place as every other
  pane you open.
- *"Does the AI even connect?"* → AI Settings → **Test connection**, beside the
  providers it tests.

## 5. Scope boundary

- **Slice 4** owns de-duplicating "Contains" and the "Inherits From" editor
  against the TopBar switcher. This slice leaves that structure alone — it only
  *adds* AI policy into the Inheritance block.
- The **richer Markdown-import feature** (external files, drag-drop, previews) is
  its own tracked feature, not designed here.

## 6. Slicing

Two work streams, sequenced one lane at a time:

1. **De-cram** (frontend only) — relocate `Chats…`/`Prompts…`/`Mutations…` to the
   app menu; give the Project region a header-actions cluster and move
   `Validate`/`Repair` into it; move `Health Check` to the AI Settings tab;
   group AI policy with "Inherits From" (keeping its explicit apply).
2. **Unbundle Validate/import** (backend + frontend) — drop `loose_scenes` from
   `ProjectValidation`, add the loose-scenes read endpoint, and add the
   "Import documents…" app-menu surface wired to the existing import endpoint.

## 7. Settled, and what's still open

Settled: the placement of every control above; AI policy grouped with Inherits
From; Health Check to the connectors; import in the app menu.

Deliberately deferred: the "Test connection" affordance is a single check in
slice 3 (the richer per-provider test is future polish); the Contains /
inheritance de-dup is slice 4; the richer import feature is its own issue.
Placement is reversible — a control that reads wrong in use can move.
