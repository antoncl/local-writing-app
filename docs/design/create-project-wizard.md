# Create-project wizard — guided defaults, the inheritance declaration, and clear-to-inherit

- Status: **Draft** (design doc; supports the ADR to follow)
- Issues: **#318** (the wizard), **#317** (project fields never reach the AI), **#471** (clear
  AI policy back to inherit) — plus a **slice-0** this design names: a general per-field
  *clear-to-inherit* gesture
- Follows: **ADR-0039** (project hierarchies — its **Amendment 1** places the inheritance
  declaration *in this wizard*), **ADR-0042** (the inherited-node edit gesture — this design
  completes its missing **inverse**), **ADR-0030** (design language — the wizard is a *dialog*)
- Deferred sibling: **#493** (narration cascade down manuscript structure) — explicitly out of scope
- Milestone: 0.7.0 — the last gate before epic **#7** closes

> Citations are `file:line` against `origin/master` at drafting time (2026-07-24) and will drift;
> they are evidence for the design, not a contract. The ADR that follows pins its own.

## 1. Why now, and why one design

Project creation today is `createProject(rootPath, title)` — a path and a name
(`frontend/src/lib/api.ts:229`). Everything else is either an empty free-text field the author
must discover after the fact, or a default they never see. Three open issues all turn out to be
faces of **one** thing — *establishing a project node's authored fields, layer-aware, at the moment
of creation* — and are cheapest to design together:

- **#317 is the vocabulary.** It gives the project node's fields their *types* (measurement,
  tense, spelling as selects; language/POV converted from free text) and — the half that is
  actually a bug — a *channel to the model*, so `{{ project.metadata.measurement_system }}`
  resolves at all.
- **#318 is the flow.** The guided wizard, and the place ADR-0039 Amendment 1 already assigns the
  inheritance declaration.
- **#471 is the primitive the flow needs.** "Clear the AI policy back to inherit" is really the
  AI-policy instance of a *general* gesture every layered field needs: **unset ⇒ inherit**.

The backend spine these sit on is **already built** — the slices that shipped ahead of this
(#306/#309/#312/#313/#314) gave us declaration, layer resolution, provenance, and `overrides/`
deltas. What remains is almost entirely **creation-time UX plus two small write paths**. That is a
comfortable place to be designing from.

## 2. Two settings tiers — the distinction the wizard is built on

The wizard's first-run step and its per-book steps touch two *different* kinds of setting, and
conflating them (as an earlier framing did) is what made the machine-config step feel unbounded.
The clean line:

- **Machine settings = the physical substrate, *outside* the layer chain.** Bound to this install;
  meaningless if copied to another box. The projects **root folder** (`default_projects_folder`,
  `machine_settings.py:111`, stored in the per-user `config.yaml`, read by
  `projects_root()`, `machine_settings.py:169-216`) and **provider credentials / Ollama host**
  (`ProviderCredentials`, `machine_settings.py:80-84`). A fresh install has *none* of these, and
  the root folder is **blocking** — the ancestor walk literally has nowhere to stop
  (`_metadata_schema_base_folder` delegates straight to `projects_root()`, `layers.py:415-446`).
- **Application-global settings = the *outermost fallback of the layer chain*.** Portable, app-wide
  defaults and preferences — theme, currency display, default AI policy/provider, default
  new-project values. Never blocking (they have defaults); conceptually just the layer *above* the
  universe. When a project defers a field all the way out, it lands here.

> **The line, in one sentence:** machine settings are the ground the chain stands on; application
> settings are the top of the chain. On a new laptop, application settings should travel and
> machine settings must not.

The operational consequence for the wizard: **only machine-*substrate* setup can block, and only
the root folder is unconditional** (§5, step 1). Credentials are machine-level too, but they are
gathered *conditionally* — see the AI gate (§5, step 3).

## 3. Where the wizard sits — one axis, not two

The book node lives where two inheritance axes meet, and this design touches only one:

- **Project-layer axis** (universe → series → book): *world canon* — measurement, spelling,
  language. This is the axis ADR-0039/#314 built and the axis the wizard sets.
- **Manuscript-structure axis** (book → act → chapter → scene): *narration* — POV mode, POV
  character, per-scene overrides. This cascade **does not exist yet** and is out of scope. It is
  filed as **#493**. The wizard sets only the book-level *default* for `pov_mode`; the cascade and
  the POV-*character* reference (which cannot be a creation field — a new book has no characters to
  point at) are that separate slice.

Naming the two axes is what keeps the wizard from silently swallowing a whole new inheritance
mechanism.

## 4. The wizard is a *dialog* — the stepper is the only new chrome

By the surface taxonomy (`design-language.md:296, 309`), a flow that **"demands completion"** is a
**dialog** — the same class as settings and the tag/group managers. Creating a project is exactly
such a flow (you cannot half-create a project into the workspace). So the wizard needs **no new
surface class**; it composes the existing `Modal.svelte` shell
(`frontend/src/components/dialogs/Modal.svelte`, sized via `--modal-width` / `--modal-max-height`).

The one genuinely new thing is the **multi-step stepper** *inside* a dialog — every existing dialog
is single-panel (`NewProjectModal`, `MachineSettingsDialog`, `DirectoryPickerModal`, … all compose
`Modal` as one panel with a flat `actions` footer). This is a composition detail of an existing
class, not a new class, so it needs no design-language amendment — but the stepper carries three
rules the ADR fixes once, so they are not re-invented per dialog later:

- **Progress is a breadcrumb** — the step names as a clickable path (a completed step navigates back),
  not bare numbered dots.
- **Next is gated on consistency** — a step cannot advance until its own inputs are valid; Next stays
  disabled until then, so an inconsistent step is never carried forward.
- **The dialog is fixed-size** — the frame does not resize between steps, so Back/Next never makes the
  surface jump; each step body fits one stable content area.

**Everything else a step shows composes from existing components** (§5). The scout finding that
crystallizes the whole shape: *the stepper shell is the only net-new UI.*

### The steps are a DAG, and the order is forced by data

Each step feeds the next, so a linear stepper is the honest shape rather than imposed chrome — with
two **conditional** branches so nobody is asked what they will never use (#318's "don't ask what
you can default; skipping should never be the attractive option"):

```
1. Root folder            (first-run / no root configured — unconditional when shown)
2. Location + inheritance  → declares the chain; everything downstream resolves against it
3. AI policy = the GATE    → resolved from the chain, or asked when nothing to inherit
     ├─ if AI on & no provider yet → provider credentials / Ollama  (conditional substrate)
     └─ if AI on                   → assistant reorder + inline hire
4. Book settings / overrides   → the project NodeEditor; inherited values shown, overridable
5. Description                  → short blurb (cover image cut — see §10)
```

Forced orderings, each independently true:
- Step 2's ancestor picker walks *from the root folder* (step 1) down to the chosen location.
- Step 4 can only show a field as *inherited* after step 2 declares the chain.
- Hiring an assistant (step 3) needs a configured provider — machine-level — so the credential
  sub-step sits **behind the AI gate**, never in the unconditional first-run block.

**Minimal paths fall out naturally.** A new book under an already-configured `cloud-allowed`
universe is `2 → 4 → 5` (measurement/spelling/tense all inherited, provider already present,
assistants inherited). A standalone `off` project is `2 → 4 → 5` with no AI questions at all.
First-run of a first universe is the only path that sees every step.

## 5. The steps in detail — reuse vs. new

**What creation produces, and the non-question of "book vs container."** The wizard creates a project
exactly as `_scaffold_new_project` does today — seeded with **one scene** and a matching manuscript
leaf (`lifecycle.py:115-135`) — and opens that first scene on completion (`createProjectAt`,
`projectSession.svelte.ts:196-199`), so a first-time author lands ready to write. It does **not** ask
"book or universe?", because there is no such stored fact: leaf/container is deliberately designed out
(`Project.svelte:159-163`, *"that emptiness IS the only leaf/non-leaf distinction … nothing derived
from the chain's shape"*). Two orthogonal file-existence signals drive two independent panes —
**child-project folders present ⟹ a "Contains" roster** (`ProjectInfo.children`,
`lifecycle.py:377-408`); **scenes present ⟹ a manuscript pane** — and both may hold at once. A
"universe" is just a project you nest others under and don't write prose in; its seeded scene is
harmless because nothing classifies on scene count at runtime. The one caution the wizard must honour:
**seed at creation only — never add an "open a project with no scenes → make one" fallback**, the one
change that *would* hand a container a stray scene. (Scene-counting to infer book-ness survives only
in test *containment* assertions, `test_open_non_leaf.py`, which already document this.)

**Step 1 — Root folder (machine substrate).** Establish `default_projects_folder`. Reuses the
existing machine-settings write (`PUT /api/settings/machine`, `machine_settings.py:40-51`;
validated by `validated_projects_root()`, `machine_settings.py:134-166`) and the folder-picker
(`DirectoryPickerModal.svelte`). `NewProjectModal.svelte:49-53` already renders the "no default
projects folder set" state — the wizard formalizes it into a first step that only appears when
`projects_root()` is `None`. *New:* nothing but the step framing.

**Step 2 — Location + inheritance declaration.** Pick the folder the book lives in (under the root),
then tick which enumerated ancestors it inherits from. This **implements ADR-0039 Amendment 1
verbatim** ("the create-project wizard … presents the enumerated ancestors and lets the author tick
the ones to inherit from"). The declaration is stored as the `inherits:` list in `project.yaml`
(`layers.py:65`), and — crucially — the **backend create path already accepts it**:
`CreateProjectRequest.inherits: list[str] | None` (`models/project.py:11-21`) →
`created_at(root, title, inherits)` (`project_service.py:128-141`). The candidate-row logic and
toggle helpers already exist for the *post-hoc* editor in `Project.svelte:99-140`
(`projectChain.ts:81-178` — `declarationRows`, `toggledDeclaration`, `canDeclareInheritance`).
*New, and small:* (a) `api.createProject` must be extended to *send* `inherits`
(`api.ts:229` sends only `{root_path, title}` today); (b) candidate enumeration currently rides on
`ProjectInfo.ancestors` — an *open* project — so the wizard needs to enumerate candidates for a
**prospective** path *before* the project exists. That is a ~25-LOC endpoint reusing
`declared_ancestor_candidates(root)` (`layers.py:296-310`), not new machinery. Per #318, each
candidate row should show *what it contributes* ("Honorverse — 1,240 lore, 3 views"), not a bare
path — a NodeList-shaped surface, not a bespoke one.

**Step 3 — AI.** One step, gated from the top. The **AI-policy slider leads the step** — a three-stop
slider *Off · Local · Cloud* (glyphs above each stop), carrying §8's inherited-muted / hover-reset
treatment, *not* the cluttered Project-pane radio group — and everything below it is the **provider
selector**, revealed only when the resolved policy is on (Local/Cloud) and **hidden when Off**. So the policy is the in-step gate rather than a
separate step: pick Off (or inherit Off) and the step is just the one control; pick/inherit on and
the provider + assistant surface unfolds beneath it. The provider chooser shows only the providers you
have **already configured** (your subscriptions — always a small set) as a segmented control, plus an
**"+ Add provider"** action; it does *not* enumerate every provider the app supports. That is what
keeps the compact display from breaking as the supported set grows (and it will): you only ever see
the few you use, while *adding* one opens a menu of all supported providers → its **credential entry**
(API key, or the Ollama URL) → written to the **machine layer** (`ProviderCredentials`, over `PUT
/api/settings/machine`; the fields `MachineSettingsDialog.svelte:93-108` already own). The long list
only appears behind "Add", where a menu is the right shape. Then reorder/hire assistants. **The entire assistant system already exists** and composes directly:
- *Hire* = `ProviderTierPicker.svelte` (labels provider "Subscription" — the subscribe→hire
  metaphor) → `POST /api/assistants` (`assistants.py:403-433`, which prepends the new id to the
  local `.order.yaml` so a fresh assistant leads).
- *Reorder / un-list* = embed `Assistants.svelte` (drag-reorder + list/unlist) → `POST
  /api/assistants/order` (`assistants.py:226-261`) / `POST /api/assistants/unlist`. Reorder names
  the id in the *local* book's `.order.yaml`, so it is layer-safe by construction.
- First-run seeds a non-empty roster automatically (`_migrate_default_models_to_files_if_empty`,
  `machine_settings.py:420-478`).
- The ordering-inherits question ADR-0039 flagged as a prerequisite (#332) reads as **settled** in
  that ADR's own verified notes.
*New:* nothing but wiring these into a step.

**Step 4 — Book settings / overrides.** The project node's own authored fields, rendered
MetadataPanel-shaped: **one `FieldValueEditor` per field** (`widgets/FieldValueEditor.svelte` — the
canonical per-type value editor, already reused across the rail, view params, mutation rows and
inputs), driven by the chain-resolved project schema, with the #313 provenance display and the
clear-to-inherit affordance (§8) wrapped around it. Because the field's *type* picks the widget, a
`select` field is a dropdown everywhere (no bespoke controls, no measurement text-vs-select drift),
friendly labels come from `field.options[].label` for free, and `readOnly` mode gives inherited
values a proper static display (chips/pills/swatch, not a raw string). For a child book, fields
inherited from ancestors show as *inherited* (star-axis provenance banner, `MetadataPanel.svelte:224-231`,
`provenance.ts:31-39`); setting one writes the key into this book's own `project.md`, and clearing it
(pop the key) defers back to the ancestor — the chain-walk model of §7/§8, no `overrides/` deltas.
This is the **review pane** of §6 — few asks, everything else shown filled-in. *New:* the field
vocabulary itself (§7) and the per-field clear affordance (§8); the row widgets are reused.

**Step 5 — Description.** A short blurb into the project node body (`project.md`, already a
`has_body` node — `default_schema.py:309-324`), edited with the app's **`long_text` editor**
(`FieldValueEditor` → `MetadataLongTextEditor`), never a bare textarea — so it matches every other
long-text surface. Offered late, skippable. *New:* nothing structural.

**A better folder picker — its own slice, used everywhere.** Steps 1 and 2 both choose a folder, and
the current `DirectoryPickerModal` is not good enough to build on: it is a one-level-at-a-time click
walker with **no typed path, no clickable breadcrumb, no create-folder, and no drive switching** (a
real problem on Windows — you cannot hop `C:\`→`D:\`), and it reloads the whole list on every click.
The backend `GET /api/directories` (`lifecycle.py:554-584`) can only *list subdirs* — no mkdir, no
path validation, no drive/home roots, and no "is this already a project / is it empty" signal. And
the single most important path — Machine Settings' projects root — **bypasses the picker entirely**,
forcing a hand-typed absolute path (`MachineSettingsDialog.svelte:64-89`). So the redesign is **one
picker used everywhere** (both wizard folder steps *and* machine settings, over the shared
`.path-picker-row` idiom, `styles.css:493-497`): a clickable breadcrumb, typed-path-with-validation,
create-folder, and drive/home roots, plus an is-a-project/empty flag on each entry so the picker can
mark existing projects. It needs small backend additions (mkdir, a path-validate probe, a roots
enumerator, the project/empty flag). Because it also repairs the *existing* create and settings flows,
it is **separable** — it can land before the wizard shell and stand on its own.

## 6. The field model — minimize *asks*, not the set

Overwhelm comes from being **asked** N questions, not from being **shown** N filled-in answers you
can accept wholesale. So the goal is a small *prompted* set with everything else defaulted-and-shown
on step 4's review pane. One rule sorts every candidate field:

> A field is **prompted** only if it is identity or changes generated prose, **and** has no
> defensible default at this layer, **and** is costly to discover you got wrong later. Otherwise it
> is **defaulted-and-shown** (visible, one tap to change) or **deferred** (fill it in later in the
> ordinary editor).

| field | verdict | why |
|---|---|---|
| title | **prompted** | no default; cannot proceed without |
| `pov_mode` | **prompted** | no safe default (1st vs 3rd is a real fork); genuinely *per-book* |
| `measurement_system` | **prompted — only when not inherited** | defaulting *is* the bug (#317: don't assume US); but world-canon, so a child book inherits it |
| author | defaulted-and-shown | asked **once** at first-run, flows into every book |
| language / spelling / tense | defaulted-and-shown | defensible defaults (locale, English→GB/US, past); world/series-ish, set high and inherited |
| `target_word_count` | defaulted-and-shown | from a work-type preset (novel / novella / short), per #318 |
| genre | **removed** | a keyword can't carry it — becomes a Lore-entry treatment later (shape TBD); the schema field goes (pre-1.0, no migration) |
| `series_number` | deferred / conditional | only meaningful under a series ancestor; usually auto-derivable |
| description | deferred | step 5, skippable |
| cover image | **cut** | §10 |

**The prompted set is a function of the layer**, and shrinks to almost nothing in the common case:

- **New universe / first-run standalone:** you set the world canon once — title, POV, tense,
  measurement, spelling. A handful of prompts, the one time these decisions are made.
- **New book under an existing universe:** measurement/spelling/tense/language all inherit and
  appear on the review pane. The only reliably-per-book craft field is **POV**. So the ask is
  effectively *title + POV*, then a review pane showing the full resolved picture, each line one tap
  to override.

`pov_mode` is not a binary. Options: `first` · `second` · `third_limited` · `third_close` ·
`third_omniscient` · `third_objective` · `multiple/alternating`. (`multiple/alternating` is precisely
the case that motivates the deferred #493 cascade.)

**Every built-in option carries a human label, and the lists are user-extensible.** Selects show
friendly text, never raw keys — `third_limited` reads *"Third person — limited"*, `en_GB` reads
*"British English"*. And because `project` is a kind (§7), a user can add to any of these option
lists through their own schema layer, so the built-in set only has to be a sensible *start* — it can
be opinionated rather than exhaustive:

- **`measurement_system`** — always a select, never a free-text field, and when prompted (top level /
  nothing to inherit) it **pre-selects `metric`** — never blank, never US. Options: `metric` ·
  `us_customary` · `imperial` · `in_world`.
- **`spelling`** — the hard one: *British / American* is too coarse; *every language's orthography* is
  impossible. It is a **sub-choice of language**: the spelling options are **filtered by the chosen
  `language`** (English → `en_GB` · `en_US` · `en_AU` · `en_CA` …; another language → its own
  conventions), with the schema-layer escape for the long tail (an author writing in Esperanto adds it
  once). Language-linked, not a flat list — a dependent dropdown.
- **`pov_mode` / `tense` / `language`** — friendly-labelled selects with sensible built-in rosters,
  same extensibility.

## 7. #317 — the vocabulary, and why the mechanism is the *settings walk*, not the index

The `project` node is **already a fully-indexed kind**. `_collect_project_node_entry`
(`references.py:750-811`) indexes each layer's `project.md` — a separate collector (#334), because
the family glob (`<layer>/<folder>/*.md`) never reached a file sitting at the layer *root*. Its id is
**unique** (`_new_id("project")` → `project_<uuid>`, `project_node.py:67`), deliberately: #343
refuses the filename-stem fallback because "the *name* is the same word at every layer, which is
exactly why the id must not be." Tests enforce it — `node.id != "project"`, nested projects get
different ids, `assertNotIn("project", index.by_id)` (`test_project_node.py:38, 218, 230`).

Indexing is therefore **not** the blocker, and adding `project` to `NODE_FAMILIES` would buy nothing
— and could not deliver field inheritance anyway. Lore inherits because a book-level override reuses the
ancestor's *same id* and shadows it; project nodes carry deliberately **distinct** ids, so there is
no shadow to resolve. The id-keyed override index has nothing to merge for them. (Reversing #343 to
a shared id would only reignite the collision it removed.)

**The right mechanism is the chain walk #312 already built for settings**, applied to the project
node's authored fields — exactly what #317 anticipated (*"the same walk applied to authored fields
rather than settings"*). And it is the *simpler* shape: each layer has its own `project.md`, so
"this book is metric" is just a key **present** in the book's own `project.md`, and **"inherit" is
that key being absent** — the walk defers to the universe. No `overrides/` delta files for project
fields at all. Today `read_project_node` reads only the open project's own `project.md` and does
**not** walk the chain (`project_node.py`); #317's substance is to make it resolve authored fields
nearest-explicit-wins over the declared chain, the way `_resolved_ai_policy` already does for policy.

> **One rule everywhere: a field left undefined resolves to the nearest ancestor that defines it.**
> This is the single inheritance law for every layered value — settings, AI policy, and the project
> node's authored fields alike — and clearing a field (§8) is precisely what returns it to that
> undefined state so the rule takes over.

#317 is therefore three parts:

1. **Chain-resolve the project node's authored fields** — extend #312's nearest-explicit-wins walk
   from settings to `project.md` fields, so an ancestor's value reaches a descendant that leaves the
   key absent. (Addressability and reference edges already work via the #334 collector — untouched.)
2. **Fields:** add `measurement_system`, `tense`, `spelling` (selects; none exist today —
   `default_schema.py` has no definition); convert `language` and `narrative_pov` from `text`
   (`default_schema.py:552-557`) to selects. (`narrative_pov` becomes the rich `pov_mode` roster.)
   *(#317's note that imperial and US-customary agree on length but differ on volume/weight — so
   `us_customary`, `imperial`, `metric`, and `in_world` are distinct options — carries over.)*
3. **Wire the fields into the built-in prompt templates / context envelope** — exposing them is
   half the job; the default authoring templates must reference at least the units/tense/spelling
   triple, or the author fills them in and nothing changes.

## 8. Slice-0 — clear-to-inherit, split by *resolution model*

The capability Anton named as missing — "delete a specific field's value" — is what makes sparse
population usable, and the everyday MetadataPanel needs it as much as the wizard. Two resolution
models exist in the codebase; the clear gesture is a different (small) write path in each, under one
intent — **unset ⇒ inherit**:

- **Chain-walk fields → pop the key.** This is where the *project node's* authored fields live (§7)
  and where settings/AI policy already lives. "Inherit" is simply the key being **absent** from this
  layer's file, so the walk defers to an ancestor. `_stated_ai_policy` already reads a missing
  `policy` key as "no opinion" (`lifecycle.py:507-552`); the only gap is a *write* path that
  **removes** the key — `update_project_settings` only ever *sets* it (`lifecycle.py:420-421`), and
  `AIPolicy` has no inherit sentinel (`models/base.py:39`). So: a clear signal that pops the field
  (for #471, `ai.policy`, also dropping an emptied `settings.ai` block; for authored project fields,
  the key in `project.md`). **This is the model the wizard uses** — its review pane sets and clears
  project-node fields, with no `overrides/` deltas anywhere in sight.
- **Id-keyed overrides → drop the row.** This is the *lore* case (inherited entries edited in the
  everyday MetadataPanel). #314 **PR 2 (now merged)** — `LayerAuthoringBar.svelte`, the L-picker
  carrying all five ADR-0042 §8 affordances — built the *write* side, not the inverse. No per-field
  clear exists: the only revert is undiscoverable (retype the exact inherited value → the diff yields
  zero rows → `_save_lore_override` deletes the *whole* override file, `lore.py:317-327`). The gesture
  is a **targeted single-field unset** — drop just that field's
  row(s) from the layer's override file (reusing that empty-delta file-deletion), instead of the
  current all-or-nothing. `_diff_metadata_to_override_rows` / `materialize_override_metadata` are the
  functions to ride.

**Where the affordance lives, and what it's called.** At rest, provenance is carried by **tint, not
chrome**: an inherited value reads **gently muted** — a small text dim only, not a filled/boxed
treatment, so it stays subtle and does **not** overpower dark mode — while an overridden one is
**live** (full strength, leading with the **actual `ti-versions` mark PR 2 already ships** —
`MetadataPanel.svelte:277`, the same glyph made interactive, never a new one). The glyph, present only
on an overridden row, is the *primary* signal; the tint is a quiet second. Reading whether a value is inherited costs no space,
and — because inheriting is the *common* case — an inherited row carries **no persistent source label**
(one on every row would clutter); the source lives in the **tooltip**. The *action* appears only on an
overridden row, on hover: a small link **above the `ti-versions` mark**, anchored to it, zero resting
width, **naming the source instead of the word "inherit"** — *"↩ Reset to Honorverse"*. ("Inherit" is
jargon for the state, a poor verb for the gesture; the muted tint already says *inherited*.)

**This is a general field-display treatment, not wizard chrome.** Muted-vs-live tint, the interactive
`ti-versions` mark, and the *Reset to <source>* control land in `FieldValueEditor` / `MetadataPanel`,
so they touch **every field display in the app** — which is exactly why slice-0 owns them, is
foundational, and is separable. The wizard merely consumes the result.

**AI policy is the same pattern, as a slider.** Instead of the cluttered radio group
(`Project.svelte:201-206`), the policy is a **three-stop slider** — Off (no glyph) · Local (Ollama
glyph) · Cloud (the AI glyph) — carrying the identical inherited-muted / overridden-live tint and the
hover *Reset to <source>* control. At the machine-settings root there is nothing to inherit, so it
shows no reset affordance — just the three stops. Slice-0 builds directly on the merged PR 2.

## 9. Open questions, and the ADR plan

Design is settled. Two items the ADR *records* rather than decides:

- **Prospective-path candidates (impl detail).** The Location step lists a *not-yet-created* project's
  ancestors, but the ancestor-walk today only runs for an *open* project. A ~25-LOC endpoint takes the
  intended folder and returns the candidates, reusing `declared_ancestor_candidates`
  (`layers.py:296-310`). Mechanical, not a fork.
- **`genre` removal.** Pre-1.0, so the field is simply dropped (no migration); a keyword can't carry
  genre — its replacement is a Lore-entry treatment (shape TBD), out of scope here.

**Reset wording — recommended: *"Reset to <source>"***. "Reset" is the most universally understood
"put it back", techie or not; naming the source fixes *what* it resets to. (Pending final OK.)

Settled and shown in the mockups: the stepper (breadcrumb, consistency-gated Next, fixed-size frame,
§4), the delete-field affordance (gently-muted-inherited / live-overridden + hover *Reset to source*
above the `ti-versions` mark, §8), the AI three-stop slider, and the provider chooser (configured
providers + "Add", §5).

**ADR plan:** no new ADR. **Amend ADR-0039** (owns the declaration) and **ADR-0042** (owns the
override gesture) to reference this design doc, extending them with the wizard-as-flow, the
nearest-wins rule for authored project fields (§7), and the clear-to-inherit inverse (§8).

## 10. Explicitly out of scope

- **Cover image** — cut entirely, not deferred. Images have a real home in research, post-1.0;
  anything sooner is a distraction (Anton's call).
- **Narration cascade** (`pov_mode`/`pov_character` down manuscript structure with per-node
  override) — the second inheritance axis (§3), filed as **#493**.
- **Editing the declaration after creation** already exists (`Project.svelte`); the wizard reuses
  its row logic but adds only the *create-time* declaration.

## 11. Proposed slices, in dependency order

Filed one at a time as the prior lands (vertical slices; snapshots over inheritance):

| # | slice | rests on |
|---|---|---|
| 0 | **clear-to-inherit** — pop-key (project fields + #471) + drop-row (lore) + interactive `ti-versions` mark + "Inherit" radio | #314 PR 2 (merged), #312 (chain walk) |
| P | **folder picker v2** — one picker for wizard + machine settings: breadcrumb, typed+validate, create-folder, drive/home roots, is-a-project flag; backend mkdir/validate/roots | separable — also repairs existing create/settings flows |
| 1 | **#317 fields + AI channel** — chain-resolve `project.md` fields (extend #312 walk); add/convert fields; wire templates | slice 0; #312 |
| 2 | **wizard shell + steps 1–2** — stepper dialog; root-folder step; location + create-time declaration (send `inherits`, prospective-path enumeration) | slice P; #309 (declaration), ADR-0039 A1 |
| 3 | **wizard AI step** — policy widget (slice-0 control) leads the step and gates the reveal; provider credentials + assistant reorder/hire unfold below, hidden when off | slices 0, 2; existing assistant system |
| 4 | **wizard steps: review + describe** — book settings/overrides review pane; description | slices 1–3 |

Slice 0 is the smallest and unblocks the sparse-population story everywhere, not just in the wizard,
so it leads.
