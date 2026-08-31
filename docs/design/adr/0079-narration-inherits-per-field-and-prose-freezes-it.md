# ADR-0079: Narration inherits per field down the manuscript, and writing a scene freezes it

- Status: **Accepted** — 2026-08-31, Anton. Shaped with Anton over the design conversation
  that produced the prose-coupling rule (§4), the schema-level `cascade_fields` YAML home
  (§3), and the rejection of the atomic nested group (§2).
- Verified against `9aad04ef` (2026-08-31).
- Feature: #493 (narration cascade, split out of the create-project wizard #317/#318).
  Builds on the **manuscript-structure walker** (`StructureVisitor` /
  `TreeStructureService.walk`, PR #1710) — the tree twin of ADR-0039's single layer walk.
  **Mirrors `_ProjectNodeMetadataResolver`** (`services/project/lifecycle.py`), ADR-0039's
  per-key metadata fold, on a *second* inheritance axis. Field model per ADR-0029.
- Relates #1711 (entity_ref members are barred from metadata groups) — deliberately
  **sidestepped**, not resolved, here.
- Supersedes nothing.

## Problem

Narration is a **book-level default the author overrides down the manuscript-structure
tree** (book → act → chapter → scene), until it reaches a scene. Two attributes:

- **`pov_mode`** — the craft technique (`first` · `second` · `third_limited` ·
  `third_close` · `third_omniscient` · `third_objective` · `multiple_alternating`), a
  `select` that already exists as a built-in on `project:project` (the book default the
  wizard authors) and `manuscript:scene` (`default_schema.py`).
- **`pov_character`** — a reference to the lore character the narration follows. It does
  **not** exist yet, and it cannot be a wizard field: a new book has no characters, so it
  is set on the structure axis as the author writes.

The `multiple_alternating` case is the one that *requires* per-node override: mode and
character get set **per scene**, the book value only a default.

Two things are missing. `manuscript:act` and `manuscript:chapter` ship with empty
`fields: []`, so there is nowhere to author an override at the intermediate levels; and
**the cascade down manuscript structure does not exist** — the mature inheritance axis
(`_ProjectNodeMetadataResolver`, universe → series → book) walks a *different* tree (the
project-layer chain), not the manuscript one.

**The naive move is wrong.** Porting the layer resolver's resolve-on-read fold to the
manuscript axis would resolve a scene's narration by walking its ancestors *at read time* —
so changing a book- or act-level POV would silently change the resolved POV of every
already-written scene beneath it. But that prose was **authored from a viewpoint**. POV is
not world canon like `measurement_system` (safe to re-resolve anywhere); it is coupled to
the words on the page, and re-resolving a written scene's POV makes the metadata lie about
its prose.

## Decision

**Each of `pov_mode` and `pov_character` is an ordinary top-level metadata field that
inherits down the manuscript structure by its own absence — the value is the nearest
ancestor that sets it, the project being the parent of the root — and writing a scene
snapshots its resolved narration onto the scene, freezing it so a later ancestor change
never rewrites the POV finished prose was authored under.**

Resolution is a per-key fold, exactly `_ProjectNodeMetadataResolver`'s rule (`inherit ==
absence of the key`), moved from the project-layer axis to the manuscript-structure axis and
run over the PR #1710 walker. What the layer axis does **not** have — and what POV forces —
is the freeze: prose pins the value the layer chain would otherwise keep re-resolving.

### 1 — Two top-level fields, inheriting per field by absence

`pov_mode` and `pov_character` are plain top-level fields, attached to `project:project`,
`manuscript:act`, `manuscript:chapter`, and `manuscript:scene`. For each field
independently, the resolved value is the nearest node on the `self → parent → … → project`
chain that sets it; **absence means inherit**. The project is the floor: the book-level
`pov_mode` already on `project:project` is where the chain bottoms out.

- **Per field, not per group.** A chapter can override the *character* (a new viewpoint
  through the same lens) while the scene still inherits the *mode* from the book. The
  atomic-group alternative cannot express this (§2, Alternatives).
- **No "inherited" flag.** Absence *is* the flag. A node that does not set a field inherits
  it; there is no third stored field recording "is this inherited?" — which is what a group
  representation was reached for and does not need to exist.
- **Mode gates whether a character applies.** `third_omniscient` / `third_objective` have no
  viewpoint character; when the resolved mode is one of these, `pov_character` is simply not
  consulted. So `pov_character` never needs an "explicitly no character" value distinct from
  "inherit" — the mode already carries that, and the storage never has to distinguish an
  absent key from a present-null one.

### 2 — `pov_character` is a top-level `entity_ref`, not a nested group member

`pov_character` is a reference field (`entity_ref`) filtered to the character entry-type,
using the existing reference machinery and the read-side healers that already scrub dangling
refs.

It is kept **top-level on purpose.** The structurally tidier shape — an atomic
`narration: {mode, character}` group value, whose presence-or-absence would encode
explicit-vs-inherited in one atom — is unavailable without first lifting the restriction that
**bars `entity_ref` members from metadata groups** (#1711): the read-side healers only walk
top-level values, so a `character` ref buried in a group would never be scrubbed when its
target is deleted (a silent mis-link). Keeping the field top-level leaves the healers
untouched and keeps this feature independent of #1711, which revisits that restriction on its
own merits. The atomicity a group would buy is unnecessary anyway — per-field absence already
encodes explicit-vs-inherited, and more expressively (§1).

### 3 — Which fields cascade is a schema-level `cascade_fields` list, declared in YAML

A **schema-level `cascade_fields` list** in `metadata.schema.yaml` names the fields that fold
down the structure; narration ships as `cascade_fields: [pov_mode, pov_character]`. A field not
in the list is per-node as today.

Three things this is deliberately **not**, each a rejected home:

- **Not a per-field property.** A `cascade?` on the field definition would force every field
  author, on every type, to consider a value relevant to two fields on one node domain — a tax
  on the whole schema-authoring surface for a narrow need.
- **Not a Python constant in the resolver.** A hardcoded `{pov_mode, pov_character}` id-set is
  the exact pattern ADR-0059 rejected: *what cascades is a schema fact*, declared in the schema,
  not baked into application code. The list lives in YAML the resolver reads.
- **Not a composition group or a display section.** Both model composition/presentation, not
  inheritance behaviour: a *composition group* would need a third consumption mode (the #1711
  complexity), and a *section* (`group:`) is single-valued and display-purposed — a "Cascade"
  section would block a "Narration" one.

The list rides the **layered schema merge** like the rest of the schema (unioned up the chain),
so a series can declare `cascade_fields` once and every book inherits it, and a project can
extend it — narration cascade is an inheritable per-project decision, not an app constant. It
is **somewhat accessible, not fully user-facing**: a technical author edits the YAML, but no
schema-editor control renders for it yet (deferred until author-defined cascading fields are a
real need — see Scope). The narration default seeds into the `metadata.schema.yaml` a new
project is already scaffolded with (`lifecycle.py:210`); existing projects are back-filled by a
migration (Consequences).

The layer axis folds *every* key because `project.md` holds project-level canon; the structure
axis must not (most scene fields — `status`, word count — are intrinsically per-scene), which
is why the set is **explicit** rather than "all container metadata cascades."

### 4 — Writing a scene freezes its narration (snapshot on first write)

The prose-coupling rule: **it is only safe to let an ancestor change reach a scene while the
scene has no prose.** Once written, a scene's POV is whatever its words were authored under,
and nothing up the tree may silently rewrite it.

Mechanism: when a scene's body **first becomes non-empty**, the resolver's currently-resolved
`(pov_mode, pov_character)` is snapshotted onto the scene's own fields, making them explicit.
From then the scene owns its narration; a later ancestor change flows only to still-unwritten
descendants (which keep resolving up). This delivers the rule exactly — unwritten scenes
track their container, written scenes are pinned — with **no propagation pass**: inheritance
is lazy resolution, and the freeze is a single write-time snapshot.

Reset-to-inherit on a scene clears its stored narration so it resolves up again. On a
*written* scene this is allowed but **warned** (its prose was authored under the frozen value;
re-inheriting re-exposes it to ancestor changes) — the warning keys off "has body," needing
no extra provenance.

### 5 — Resolution runs once in Python; TS and Jinja consume a stamped value

The value has two shapes, the `stored`/`computed`-by-authorship split ADR-0029 already stamps
`category` through:

- **Stored** (author authority): the two top-level fields, absence = inherit. Lives in Python
  storage and in the frontend editor — the one place that must distinguish a node's own value
  from an inherited one, to draw the override / clear-to-inherit affordance.
- **Resolved** (computed): the resolver **stamps** the effective `(mode, character, source)`
  onto every node, always populated (book default at the floor). This is what read-side, the
  AI context envelope, and Jinja templates consume.

So there is **no dual-runtime resolution** (unlike view evaluation's IDL, ADR-0041): Python
resolves and stamps; TS and Jinja read the stamp. TS reimplements only the trivial "is my
stored value absent?" for the editor badge, never the ancestor walk. Templates never meet the
nullable form — `{{ narration.mode }}` / `{{ narration.character.name }}` always resolve,
because the fold ran before the template did. Exposing the resolved shape to templates is a
**registered prompt-vocab addition** (ADR-0060, the gate-enforced vocab surface).

### 6 — The cascade rides the manuscript-structure walker

Bulk resolution (the effective narration for every scene, for the AI context or a POV column)
is **one pre-order `StructureVisitor`** (PR #1710) carrying the last-seen value of each
cascade field down the ancestor chain — the manuscript-axis twin of
`_ProjectNodeMetadataResolver`. Per-node resolution is an ancestor lookup. This is the walker
#493's "do not hand-roll a second walk" asked for; slice 1 (PR #1710) built it, and this is
its first cascade consumer.

### 7 — Inherited-ness reuses the marker we already have

An inherited narration value shows the way inherited values already show on the project-layer
axis — `provenance.ts`'s `fieldProvenance` classifier, the `ti-versions` "Reset to \<source\>"
control, and the #517 clear-to-inherit gesture. A writer should not learn a second visual
language for "this came from above"; only the **source label** differs — "from Act 2" instead
of "from Series."

Reusing it surfaces two states the layer axis does not have, both real slice-2 work rather
than free:

- **Two inheritance axes can meet on one node.** A scene can inherit narration from its chapter
  (this axis) *and* `measurement_system` from its series (the layer axis) at once — same badge,
  different source. `fieldProvenance` today knows only the layer axis and must learn that a
  structure source exists.
- **The freeze is a third state.** A written scene's narration is *stored* (frozen, §4), so it
  renders as the node's own value — but it arrived by snapshot, not deliberate authoring.
  Whether the badge distinguishes "you set this" from "this froze when you wrote the scene" is a
  genuine UI call; the reset-to-inherit *warning* keys off has-body regardless.

## Scope

**In scope, sliced:**

1. **Backend cascade core.** The `pov_character` field definition (`entity_ref` → character);
   the schema-level `cascade_fields` list (§3) carried through the layered merge, seeded into
   the scaffolded `metadata.schema.yaml` and back-filled to existing projects by a
   `RootMigration`; `pov_mode` + `pov_character` attached to `manuscript:act` and
   `manuscript:chapter`; the `StructureVisitor` resolver stamping resolved narration; and the
   snapshot-on-write freeze. Acceptance at the service level against a
   `book → act → chapter → scene` fixture.
2. **Frontend surfacing.** Resolved narration + own-vs-inherited state + clear-to-inherit on
   the act / chapter / scene metadata rails — porting the layer axis's provenance/reset
   affordance (`provenance.ts`, #517) to the structure axis.
3. **AI / Jinja.** Register the resolved narration in the prompt vocab (ADR-0060) and feed it
   into the context envelope.

**Out of scope — deferred with the reason:**

- **The atomic nested-group representation** (§2) — gated on #1711; revisited there.
- **A schema-editor control for `cascade_fields`.** The list is YAML-editable now; a UI
  affordance waits until author-defined cascading fields (a field *outside* narration wanting to
  fold) are a real need, designed on demand then rather than taxing the schema editor for a
  maybe.
- **Cascade fields other than narration.** The mechanism is general, but no other built-in
  joins `cascade_fields` as part of this feature.
- **Non-manuscript axes** (story chronology, research trees). Narration cascades down the
  manuscript structure only.

## Alternatives considered

- **Resolve-on-read cascade, no freeze** (the direct port of `_ProjectNodeMetadataResolver`).
  Rejected: it retroactively rewrites the POV of already-written prose when an ancestor
  changes — the domain flaw that shaped §4. POV is coupled to the words; world canon is not.
- **An atomic `narration: {mode, character}` group value.** Structurally cleaner (presence =
  explicit, in one atom), and the instinct that a nullable-inherited state "wants a group."
  Rejected here: it needs the entity_ref-in-groups bar lifted (#1711) because the ref healers
  only walk top-level values; it couples this feature to a schema-core change inside the
  release gate; and it *loses* the "override just the character" case. Per-field absence
  encodes the same explicit/inherit distinction without nesting. #1711 revisits the bar on its
  own merits; if it lands, migrating narration onto a group is an additive follow-up.
- **Materialize on attach + a propagation pass** (copy the parent's POV onto every new node;
  on an ancestor change, walk the subtree overwriting where safe). Rejected: it needs an
  explicit inherited flag (the third field) to know what to overwrite, *and* a mutating,
  body-guarded propagation walk. Lazy per-field absence + snapshot-on-write reaches the same
  observable semantics — new nodes inherit, ancestor changes flow to unwritten descendants,
  written scenes freeze — with neither the flag nor the walk.
- **Gate the pair on one field's presence** (e.g. `pov_mode` set ⇒ explicit narration).
  Rejected: two independent top-level fields can drift into partial states, forcing the
  resolver to decree that a set-but-ungated field is ignored — a smell — and it discards the
  per-field override case. Per-field absence has no gate.
- **Guard/block the ancestor POV change when written descendants exist** (§4's counterpart).
  Rejected: a blocking gesture, and it cannot express the common intent — change the default
  and let *unwritten* scenes follow while written ones stay. Snapshot-on-write gets both.
- **A per-field `cascade` property** (or membership in a composition group / a display section),
  as the "which fields cascade" home. Rejected (§3): a per-field property taxes every field
  author for a two-field need; a composition group invents a third consumption mode (#1711
  complexity); a display section is single-valued and presentation-purposed (a "Cascade" section
  would block a "Narration" one). What cascades is a schema fact, so it lives as a schema-level
  `cascade_fields` list. A **Python constant in the resolver** was rejected for the same reason
  ADR-0059 gives — a hardcoded id-set is a schema fact escaping into code.

## Consequences

- New surface: the `pov_character` field, the schema-level `cascade_fields` key on
  `MetadataSchema` (+ its scaffold seed and back-fill migration), the resolver + stamped
  resolved-narration computed field, the snapshot-on-write hook, the frontend own/inherited
  surfacing + clear-to-inherit, and the prompt-vocab registration.
- `manuscript:act` / `manuscript:chapter` gain fields (empty today) — ordinary schema
  additions.
- **One small migration — for `cascade_fields`, not the rest.** The `pov_character` field and
  the act/chapter attachments are additive (absence = inherit, no migration — ADR-0071's "only
  migrate when a missing migration breaks something"). The exception is `cascade_fields`:
  existing projects' `metadata.schema.yaml` predates the key, and there is deliberately **no**
  resolver-side default to fall back on (that would be the Python constant §3 rejects), so a
  `RootMigration` writes the narration default into every existing project's schema file. That
  is the one storage-shape change this feature owes.
- **A second inheritance axis now exists** — manuscript structure, parallel to the
  project-layer axis. Both are walked by parallel visitors (`StructureVisitor` /
  `LayerVisitor`) and fold nearest-explicit-wins. The symmetry is deliberate, and the "read
  before hand-rolling a tree walk" discipline (PR #1710) now covers both.

## Acceptance

Service-level tests against a `book → act → chapter → scene` fixture, written red-first; a
test earns its place only if a plausible wrong implementation fails it (the mutation-testing
bar), and ★ marks the traps.

**Slice 1 — the cascade core:**

1. A scene setting no narration resolves `pov_mode`/`pov_character` from its chapter, the
   chapter from its act, the act from the book. **★** absence at every level walks to the
   project floor (catches a chain that stops at the manuscript root instead of the project).
2. **★ Per-field independence.** A chapter that sets only `pov_character` overrides the
   character while the scene still inherits `mode` from the book — the two fields resolve on
   separate chains.
3. **★ Snapshot-on-write freeze.** Writing a scene (body empty → non-empty) stamps its
   resolved narration onto it; then changing the book's `pov_mode` leaves the written scene's
   resolved mode unchanged while an unwritten sibling's follows. (A wrong freeze silently
   tracks the ancestor — mutation-checked.)
4. **Omniscient.** A node resolving `pov_mode = third_omniscient` yields no consulted
   `pov_character`, whether or not an ancestor sets one.
5. **Resolved is a pure stamp.** Reading a node twice with no change yields the same resolved
   `(mode, character, source)`; the stored fields are never mutated by a read.
6. **Reset-to-inherit.** Clearing a scene's stored narration makes it resolve up again; on a
   *written* scene the response carries the re-exposure warning.

**Slice 2 — surfacing:** the rail shows the resolved value with its source, marks own vs
inherited, and offers clear-to-inherit; the write path stamps the freeze on first prose.

**Slice 3 — AI/Jinja:** `{{ narration.mode }}` / `{{ narration.character.name }}` resolve on
a scene with no own narration (proving the stamp, not the stored value, reaches the template),
and the vocab-drift gate passes.

## To verify / build at implementation

- **The freeze trigger — "body first becomes non-empty."** Locate the single scene-save choke
  point where the empty→non-empty transition is observable, and snapshot there; guard against
  re-freezing on every subsequent save (freeze once, when prose first appears).
- **`pov_character` as a filtered `entity_ref`.** Confirm the reference-picker /
  `picker_config` machinery can restrict a ref to the character entry-type; if it cannot,
  that filter is its own small piece of work, not assumed.
- **The `cascade_fields` schema-level list.** A new top-level key on `MetadataSchema`: define
  its merge semantics (union up the layer chain), validate its ids resolve to real fields (like a
  group reference), seed it into `_empty_metadata_schema` / the scaffolder, author the
  `RootMigration` that back-fills existing projects, and add the key to the TS mirror in
  `types.ts` (the schema model is hand-mirrored, not a shared IDL — drift is caught only by
  discipline).
- **Resolved-narration stamping.** Ride the same lane that stamps `category` (the schema
  resolver's computed-field stamp), rather than a bespoke pass.
- **Jinja exposure.** Extend the `fields()` / `field_value` descriptor and register the
  resolved shape through the prompt-vocab gate (`docs/prompts/reference.md` +
  `promptVocab.json` regen), or the drift check fails.
- **Storage need not distinguish absent from present-null for `pov_character`** — §1's
  mode-gates-character rule is what removes that requirement; if a later change reintroduces an
  "explicit no character" state, revisit, because sparse front matter's absent-key vs
  null-value distinction is not something every read path preserves.
