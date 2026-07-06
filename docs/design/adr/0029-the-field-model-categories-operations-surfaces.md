# ADR-0029: The field model — a permissive convenience, categorized by authorship

- Status: Proposed — 0.5.5, 2026-07-05
- Amendments: **2026-07-06 (#113)** — §C matrix + §J corrected: intrinsics support **relabel only**; `hide`/`reorder` are N/A (their display is a routed identity control, not a rail row).
- Feature: #118 (unify the field model, then conform) · follows #116 (intrinsic fields + per-type overrides, merged PR #119)
- Governed by: `memory/decisions_intrinsic_fields_and_overrides.md`,
  `docs/metadata-strategy.md`, `memory/decisions_metadata_revision.md`,
  `memory/decisions_ui_widget_taxonomy.md`
- Interacts with: ADR-0020 (views are kind-anchored → picker resolution, §F),
  #89/#113 (display-order + color-row hoist, §G), #117 (models.py split — orthogonal)

## Context

`title`/`entry_type`/`id` became first-class schema fields in #116 (virtual intrinsic
fields; per-type `field_overrides` for relabel/hide). Shipping it surfaced the real
problem it was a symptom of: **there are distinct *categories* of field, each handled
ad-hoc, so the same field renders inconsistently across the four surfaces that show
fields.** The categories were never named, so every surface re-derives "what is this
field and what may I do with it" from a scatter of independent signals — `intrinsic:
bool`, `type === "computed"`, `key === "color"`, `hidden: bool`, `field_overrides` — and
each derives it slightly differently. That is the drift #118 catalogues (intrinsic
rename/hide partly inert; visibility decided per surface; computed fields "live their own
life"; the color-row hoist; own-vs-inherited override controls diverging; override
aspect-freeze; a duplicated `INTRINSIC_FIELD_KEYS`).

But there is a second, deeper problem underneath the drift, and it sets the frame for the
first: **the schema currently reads as a contract the user must satisfy, when it should be
scaffolding the user may lean on or ignore.** Two symptoms:

- To add one field to a built-in type (`lore:character`) a user must **derive a subtype** —
  `upsert_entry_type` rejects any edit to a built-in type ("System node types cannot be
  edited", `schema.py:205`). The same guard also blocks `set_entry_type_field_order` and
  `set_entry_type_group_applications` on built-in types — yet those are per-*layer* overlays
  that never touch the built-in. The `field_overrides` path (`schema.py:450`) *deliberately*
  skips the guard with a comment: an overlay "never mutates the built-in type." The codebase
  already contradicts itself: one overlay path is permissive, the others are walls.
- The provenance-based split I first reached for — "computed (from this node) vs derived
  (from other nodes)" — is contrived. `word_count` reads the body, `number` reads sibling
  order, `cost` accumulates the invocation ledger (and becomes fully derived once AI cost
  accounting lands). They differ in *what the derivation reads*, which is a config detail,
  not a user-facing category. The user-facing fact is simply: the app produces the value; you
  don't type it.

The four surfaces are: **the metadata rail** (`MetadataPanel`, per-node instance editor),
**the schema type editor** (`SchemaTypeEditor`, the class editor), **the Views field
picker** (`ViewBodyView`, kind-anchored filter/sort authoring), and **the field-order /
NodeEditor** lists.

## Decision

### A. The field system is a permissive convenience, not a contract

Fields exist to **aid** a writer in structuring a project; they must never coerce. This
principle governs every decision below and is the tie-breaker for future ones:

- **No required fields; redundant tracking is legitimate.** A writer who records a scene's
  status inside a `summary` long-text instead of the `status` field is using the tool
  correctly. The app validates the *integrity* of what was entered (references resolve to
  real nodes; YAML parses) but never forces the schema's structure onto the user's prose or
  demands a field be filled.
- **Layering is additive and permissive.** The layered schema (built-in → ancestor folders →
  project) already merges definitions downward. Extend that reading to its logical end:
  **any layer may _extend_ any type — built-in types included — with its own fields and
  subtypes, and may _overlay_ presentation (label / hidden / display-order / groups) on any
  type.** Adding a field to `lore:character` is an *extension at your layer*, not an edit of
  the built-in; it must not require a subtype.
- **Built-in definitions are immutable _as declarations_, not untouchable.** A layer cannot
  rewrite a built-in type's own `parent`/`kind`/`name`/declared fields (that would fork the
  shipped schema and break inheritance invariants). But extending and overlaying it changes
  nothing about the built-in. So the "System node types cannot be edited" guard is
  **narrowed to block only definition-rewrites** — it must stop blocking own-field extension,
  `display_order`, and `group_applications` on built-in types. The `field_overrides`
  no-guard reasoning is the model; generalize it, don't special-case it.

### B. Three categories, cut by authorship

Every resolved field carries one `category`, and the cut is **who produces the value**:

| category | value produced by | lives in | example fields |
|---|---|---|---|
| **stored** | the user (typed into a widget) | `metadata.<key>` | `status`, `summary`, `characters`, `color` |
| **intrinsic** | the user, via identity controls | a top-level node property (`node.<key>`) | `title`, `entry_type`, `id` |
| **computed** | the app (read-only) | nothing — derived on read | `word_count`, `number`, `cost`, backlinks |

There is **no separate "derived" category.** A computed field's derivation may read this
node's body, its position among siblings, an invocation ledger, or other nodes' inbound
links — all of that is the field's `computed: {function, scope, source}` config, invisible
to the user, who sees only "the app fills this in." `color` is a **stored** field (value in
`metadata.color`) with a swatch widget and a type-level default — not its own category
(see §G).

### C. Operations, and the capability matrix

The operations a field can be subject to, and which categories permit each:

| operation | stored | intrinsic | computed |
|---|:--:|:--:|:--:|
| **read** (display the value) | ✓ | ✓ | ✓ |
| **edit value** (author the instance value) | ✓ widget | ✓ identity control | — app-produced |
| **relabel** (per-type label) | ✓ | ✓ | ✓ |
| **hide** (per-type visibility) | ✓ | —¹ | ✓ |
| **reorder** (via `display_order`) | ✓ | —¹ | ✓ |
| **add / remove on a type** (any type, per §A) | ✓ | — always present | ✓ from catalog |
| **author the field's definition** | ✓ user-defined defs | — built-in identity | — app owns derivations |

¹ **Amendment (2026-07-06, #113):** intrinsics are the exception to the otherwise-uniform
matrix. Their value is **never rendered as a metadata-rail row** — display is routed to a
fixed identity control (header / type selector; `id` shows nowhere), so `hide` has no rail
target and `reorder` no rail position. Only **relabel** is meaningful for an intrinsic (it
retargets the identity-control label and the Views-picker entry). `id` stays out of the Views
picker via its def-level `hidden` default, not a per-type toggle. See the amended §J.

For **stored** and **computed** fields the middle three rows are identical — **relabel, hide,
and reorder apply the same way.** **Intrinsics are the exception** (¹, §J): only relabel
applies. Otherwise only *value editing* and *definition authoring* vary by category.
Membership (add/remove on a type) is permissive for all three per §A: it is never blocked by a
type being built-in. This matrix *is* the ADR — each surface consults `category` → the row →
renders accordingly, instead of re-deriving from scattered booleans.

### D. One resolved descriptor; `category` is the single source of truth

The resolver stamps `category` onto each field in the resolved schema. `category` is
derived, not stored: `intrinsic` iff the key is in the resolver's intrinsic set;
`computed` iff `type == "computed"`; else `stored`. **The intrinsic key set lives in
exactly one place** (`default_schema.INTRINSIC_FIELD_KEYS`), is applied by the resolver, and
reaches the frontend as the stamped `category` — the frontend never hardcodes the key set.
This retires the duplicated `INTRINSIC_FIELD_KEYS` `Set` in `evaluateView.ts` (#118 point
7): `fieldValue` switches on `category` (`intrinsic → node[key]`, else `node.metadata[key]`)
read off the payload. Capabilities (`editable`, membership, def-authorability) are a pure
function of `category` — one shared table, consulted identically on both sides.

### E. Computed fields are app-produced, read-only, and first-class in presentation

Being app-produced governs authoring, not presentation:

- **Read-only everywhere a value shows** (rail lock icon — already done), and **first-class
  in the picker** (filter/sort by `word_count > 1200`) and in ordering. They relabel / hide /
  reorder like any field.
- **Added to a type from a fixed catalog** of app-provided derivations
  (`word_count`, `number`/counter, `cost` and its scoped variants; backlinks when surfaced).
  Adding one is a membership operation (§A) — pick from the catalog — never authoring a new
  derivation. The schema field-type dropdown does **not** offer `computed` as a
  user-creatable type: a user cannot supply a derivation function, so a "computed" option is
  a dead control. This is the *one* honest limit in the model — the app owns derivations —
  and it is framed as such, not as a restriction on structuring.
- **Removable from a type** (membership) but their **definition is not user-editable**
  (built-in). This resolves #118 point 3's "cost / References editable-or-removable in the
  schema editor": you may remove them from a type, not rewrite their definition.
- `cost` is accumulated today and becomes fully derived once AI cost accounting lands; it
  stays `computed` throughout — the category is about *who authors the value* (never the
  user), not *how* the app arrives at it.

### F. Presentation resolution is one function, parameterized by the anchor type

`effectiveFieldLabel` / `effectiveFieldHidden` already merge a per-type override over the
base def (child wins per aspect). Make **both the rail and the Views picker** consult them;
the only difference is *which type* they resolve against:

- **rail / schema editor / NodeEditor** resolve against **the node's own `entry_type`** — the
  full per-type override applies.
- **the Views picker** is kind-anchored (ADR-0020: a view's universe is a whole kind), so it
  resolves against **the kind's root entry_type** (e.g. `lore:lore_entry`). That is where
  cross-type conventions live — the built-in `title → "Name"` override sits on
  `lore:lore_entry` and so *does* reach the picker. A per-leaf-type override (`title → "Full
  Name"` on `lore:character` only) deliberately does **not** reach the kind picker; the picker
  filters a whole kind, and a leaf-only relabel is a per-type presentation choice. Same
  resolution code, different anchor argument. This resolves #118 point 2.

### G. Canonical ordering: `display_order` over the full membership; no hoists

There is one ordering axis: the per-type `display_order` overlay, resolved over the full
membership (intrinsics lead by injection, then inherited, then own, then group-expanded;
`display_order` floats listed keys to the front in listed order — #89, landed 0.5.4).
Intrinsics and computed fields order like any field. **`color` renders at its `display_order`
slot like every other field**: remove the `MetadataPanel` `color-row` hoist and the
`NodeEditor` `metadataFieldIds.filter(id => id !== "color")`; the generic field-row renderer
gains a `type === "color"` branch drawing the swatch widget inline (it already picks the
widget by `type`). The type-level color *default* (`EntryTypeDefinition.color`/`own_color`)
is a separate schema concern, unchanged. Resolves #118 point 4; unblocks #113 §2.

### H. Own-field overrides; the def editor and the override are two scopes

Every field row — **own and inherited alike** — exposes the per-type override controls
(relabel / hide), because presentation is per-type regardless of where the def is owned. Own
rows *additionally* expose the **global def editor** (name / type / options / icon), a
different scope: it edits the field's definition everywhere, not this type's presentation of
it. Both can sit on one own row. Resolves #118 point 5 (relabel/hide no longer
inherited-rows-only).

### I. Overrides compose per-aspect; the UI writes the type's *own* overlay, not the resolved

The resolver already merges overrides per-aspect (child wins on `label` and `hidden`
independently). The aspect-freeze bug (#118 point 6) is entirely UI-side: the override
editor reads the **resolved** (parent-merged) value of the aspect it isn't editing and PUTs
it, freezing the inherited value into the child layer. Fix: ship the type's **own
(pre-merge) `field_overrides`** in the schema payload — `own_field_overrides`, the exact
parallel to the existing `own_fields`/`fields` and `own_color`/`color` split — and have the
override editor read/write against *that*. Editing one aspect leaves the other absent in the
child overlay, so it keeps inheriting. The endpoint contract (a complete desired overlay;
`null` clears an aspect; empty overlay drops the entry — #116) is unchanged; only the value
the UI feeds it changes.

### J. Intrinsic fields: identity presentation, not a rail row (amended 2026-07-06, #113)

> **Amendment.** The original §J posited that an intrinsic has *two* presentations — an
> identity control **and** a "field presentation (a row in the rail) governed by `hidden`."
> Verifying #113 showed the second half is fiction: the metadata rail (`MetadataPanel`)
> unconditionally skips intrinsics, so there is no rail row to hide or reorder. Build `hide`
> and `reorder` on a row that doesn't exist and they have no target. The corrected model:

An intrinsic field's value is **never rendered as a metadata-rail row** — its display is routed
to a fixed identity control:

- `title` → the editor header (the doc's name)
- `entry_type` → the type selector
- `id` → an opaque key with no control of its own (shown nowhere)

Because there is no rail row, **`hide` has no target and `reorder` has no position** — both are
meaningless for intrinsics (§C¹). Only **relabel** is meaningful: it retargets the
identity-control label *wherever the field surfaces* — the header / type selector **and** the
Views-picker entry (`title → "Name"` renames the lore header and the picker entry together).
The Views picker keeps `id` out of its filter/sort list via `id`'s def-level `hidden` default
(not a per-type toggle). The type editor therefore shows intrinsic rows as **rename-only** and
**pinned** (non-draggable, and not a drop target, so nothing slots above them). You still
cannot "hide" a document's name — but that's now because `hide` doesn't apply to intrinsics at
all, not because a hide-of-a-rail-row is intercepted. Resolves #118 point 1.

## Why / rejected alternatives

- **Why authorship, not provenance, is the category axis.** "Computed vs derived" splits on
  what the derivation *reads* — a config detail the user never sees. The user sees exactly one
  distinction: *did I type this, or did the app fill it in.* Cutting categories on authorship
  (stored / intrinsic / computed) is the cut that matches what the user experiences, keeps
  `cost` in one category across its accumulate-then-derive evolution, and avoids a boundary
  that shifts every time a derivation's inputs change.
- **Why the permissive principle leads.** Every inconsistency in #118 is a place where the
  tooling drifted toward treating the schema as a constraint (must-subtype-to-add-a-field;
  built-in types walled off from their own layer's overlays). Naming "convenience, not
  contract" as the first principle makes those resolutions forced rather than case-by-case,
  and pre-commits the answer to the next such question.
- **Rejected: keep the built-in guard as a blanket wall.** It conflates *rewriting a built-in
  declaration* (rightly forbidden) with *extending/overlaying it downstream* (the whole point
  of layering). The `field_overrides` path already proves the narrow guard is correct;
  generalizing it is coherence, not new risk.
- **Rejected: let users author computed derivations from the dropdown.** They cannot supply a
  derivation function; a user-selectable "computed" type is a dead control. A fixed catalog +
  membership picking is the honest shape — and the only limit the permissive model keeps.
- **Rejected: keep the picker on `def.hidden` + base labels only.** A real inconsistency, not
  a scope — the built-in `lore → "Name"` relabel is invisible in the picker today. Resolving
  against the kind root (§F) fixes it with the same code and a principled anchor.
- **Rejected: `color` as its own category / keep the hoist.** Color differs from other stored
  fields only in *widget* and a type-level default, both already expressible. A category plus
  a hoist plus a filter to move one field to the top is the per-field special-case the model
  exists to kill.
- **Rejected: hide-title removes the header.** A node must display its name; there is no
  coherent nameless document. Splitting identity presentation from field presentation (§J) is
  what lets `hide` mean something without breaking identity.
- **Rejected: fix aspect-freeze by reading resolved values more carefully in the UI.** The
  robust fix is to never feed resolved values back as authored overrides — expose the own
  overlay (§I), matching the `own_fields`/`fields` split the codebase already trusts.

## Consequences

- **Backend**: the built-in guard narrows — `upsert_entry_type` (own-field extension),
  `set_entry_type_field_order`, and `set_entry_type_group_applications` stop rejecting
  built-in types; the guard is kept only where an operation would rewrite a built-in's own
  declaration. The resolver stamps `category` on each resolved field and ships
  `own_field_overrides` per type; `INTRINSIC_FIELD_KEYS` stays canonical there and stops being
  mirrored. The `computed`/`color` type values and `field_overrides` model are unchanged.
  `models.py` is at the file-size cap — the split is #117 and orthogonal.
- **Frontend**: `evaluateView.ts` drops its `INTRINSIC_FIELD_KEYS` mirror and reads `category`
  off the payload. `effectiveFieldLabel`/`effectiveFieldHidden` gain an anchor-type argument
  (picker → kind root, rail → node type). The `MetadataPanel` color-row hoist and `NodeEditor`
  color filter are removed; the field-row renderer gains a `color`-widget branch. The schema
  type editor exposes override controls on own rows too, reads/writes `own_field_overrides`,
  and lets a user add fields to a built-in type in place (no forced subtype).
- **This is a design ADR; the conform pass is separate work — but the "refactor" _is_ the
  conform.** Complying with this ADR *is* the cleanup: the scattered `intrinsic` /
  `type === "computed"` / `key === "color"` derivations collapse into one `category` stamp, the
  color hoist + filter go, and the duplicated `INTRINSIC_FIELD_KEYS` goes. It is not a separate
  optional tidy-up. The surface-by-surface changes land under #118's follow-up and pick up #113
  (draggable inherited rows + color-row removal). Each change to the live rail / type editor
  needs eyeballing in the interactive 0.5.5 session (headless can't exercise drag, the color
  widget, or in-place built-in extension).
- **Ride #85 on this pass.** #85 (`<kind>:base` abstract roots; `lore:place → lore:location`)
  re-keys the same `default_schema.py` built-in defs the conform work edits — including the
  `lore:lore_entry` (→ `lore:base`) root that carries the built-in `title → "Name"` override and
  is the picker's resolution anchor (§F). Doing it separately means editing those defs twice and
  risking a `default_schema.py` rebase conflict; it is mechanical and pre-1.0-free (abstract
  roots are never instantiated, so no on-disk migration). Land it as a **standalone leading
  rename commit** on the conform branch, then the semantic changes on top. **#86** (`scene` kind
  → `manuscript`) stays out — it leaks into folders/routes/discriminator, a different order of
  magnitude.
- **Out of scope**: user-authored computed derivations (catalog only); a per-leaf-type
  override reaching the kind picker (deliberately not — §F); full AI cost accounting (tracked
  separately; `cost` stays `computed` regardless); the `models.py` split (#117).
