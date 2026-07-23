# ADR-0039: Project hierarchies — inheritance is virtual membership; three edit affordances; per-field layer overrides

- Status: **Accepted** — 0.7.0, 2026-07-19 (PR #319) · rewritten 2026-07-19 after two rounds of
  adversarial review · **Amendment 1: inheritance is declared, not inferred** · **Amendment 2: one
  traversal; the root is stipulated, not inferred from a stray `metadata.schema.yaml`** ·
  **Amendment 3 (Proposed, undecided): is the declaration read transitively?**
- Feature: #7 (epic) full project hierarchies
- Companion: ADR-0040 (the index — which *materializes* the chain, not merely caches it)
- Amends: ADR-0013 (see its Amendment 1) · Gesture UX: **ADR-0042** (co-designed with mutation
  edit-in-place) · Provenance mark: **#304**
- Governed by: files-are-truth; the layered metadata schema already shipped

## Context

The layering machinery largely exists. `_project_layer_folders` (`layers.py:331`) walks the
ancestor chain, and `_build_node_index` (`references.py:260`) already collects lore, prompts,
assistants, mutation sets, views and research across every layer — descendant winning on id
collision in `resolve()` (`node_index.py:179`) — while scenes stay book-scoped in
`_families_for_layer` (`references.py:469-478`). What is missing is navigation, the edit story for an inherited node, and
settings resolution.

> **Citations re-verified 2026-07-22.** The claims above still hold; their locations had drifted —
> the schema/index split of #14 moved the chain walk into `layers.py`, and #329 gave it a single
> traversal. Where a later PR overtook a claim rather than moving it, the drift is marked inline
> below rather than rewritten away: an ADR's Context is a record of why it was written.

An earlier draft of this ADR framed per-field overrides as a new tier inside the `effective_state`
resolver, "one level up" from scene mutations, and claimed to redeem a deferred slot from ADR-0005.
That framing was wrong in a way worth recording, because it drove several downstream errors: see
*Why / rejected alternatives*.

## Decision

**A project is any folder containing `project.yaml`** (the manifest). Projects nest by filesystem
placement — no `children/` wrapper — though *which* ancestors a project inherits from is **declared**,
not inferred from that placement (Amendment 1). `project.md` is a *separate* thing: the singleton **project
node** (kind `project`, the level's own metadata + blurb). A flat project is a chain of length one.
*(This corrects the pre-1.0 design memo, which conflated the two as `project.md`.)*

> **⚠ Superseded by Amendment 1 below.** This ADR originally made `project.yaml` the *layering*
> marker, inferring the chain from folder placement. Amendment 1 replaces that with an explicit
> declaration. `project.yaml` still marks an **openable project**; it no longer decides what is
> inherited.

**Inheritance runs up the declared ancestry, N levels, with no hardcoded tier names.** "Universe /
series / book" are *conventions the user expresses by nesting depth*, never types the app knows. Lore, prompts,
assistants, mutation sets, views and research notes are collected across every ancestor layer,
descendant overriding ancestor on id collision. Scenes stay **book-scoped** (see below).

**Visibility is ancestor-only.** A descendant sees its ancestor chain; it never sees siblings. Opening
Book 12 pulls its universe + series canon, not the *other* universes on the shelf. This bounds a
session's working set to one root-to-leaf chain regardless of total shelf size.

**Scenes stay book-scoped** (not inherited) — the one kind that does not layer. The reason, so a later
pass does not "unify" it: a scene's identity is its position in *one* manuscript
(`manuscript.structure.yaml` is per-book, and `effective_state` resolves against that book's
`scene_order`), so an inherited scene would have no defined position in the inheriting book. A shared
prologue or series-level interlude is therefore not merely unimplemented — it needs a manuscript model
that admits a scene appearing at a position in more than one book.

**Opening is level-agnostic.** A **leaf** (book) opens to merged canon + its manuscript; a **non-leaf**
(universe/series) opens to merged canon + a **child-project roster**, with **no manuscript pane**
(manuscript is book-scoped). Same session shell in both cases — a universe is just a project whose
scenes folder is empty. A breadcrumb / level switcher walks the chain.

### Inheritance is virtual membership

An ancestor-owned node is **pulled into the open project as a member** — materialized through the
node index (ADR-0040), which resolves the chain into the member set this project sees. Inheritance is
not a lookup that happens later; it is what the index *produces*.

This is the load-bearing frame, and three things follow from it:

- **A layer override is not a resolution tier.** It is the consuming layer's sparse delta on a
  pulled-in node, applied **at materialization**. The result *is* the base that the open project sees.
- **Scene mutations are untouched.** They run on that base exactly as they always have, keyed by
  manuscript position. Resolution is `materialize(chain) → base`, then `base → mutations → effective`.
- **There is exactly one layer scope per open project** — the project you have open. "Which scope does
  this surface resolve for?" has one answer, so it is not an open question (see *Consequences*).

> **Terminology.** This ADR says **layer override** (or *layer delta*), never bare "field override".
> `field_overrides` is already taken: `models/schema.py:252` uses it for ADR-0029's per-entry-type
> `{label, hidden}` *presentation* overrides, an unrelated concept. Grepping the wrong one wires layer
> deltas into the schema machinery.

**Where the fold happens — concretely.** The index does *not* hold field values (`NodeIndexEntry` is
`(path, kind, entry_type, title, layer rank)`; ADR-0040 keeps it that way, and a metadata-carrying
index would break its change-gate and turn the snapshot into a field store). So the fold applies in
two places, from one shared helper:

- **Values** fold on read — `read_lore_entry` / `list_lore_entries` gather the target's overrides
  across the chain and apply them.
- **Edges** fold during index build — `_forward_refs_for_entry` already re-reads front matter to
  extract refs; it applies the same delta *before* extracting. So the index holds **effective** edges
  without holding metadata, and backlinks / `References` / Nest need no scope parameter and no
  query-time delta.

A consequence for the change-gate (ADR-0040): a write to an override file must be gated against its
**target**, not against itself.

### Three edit affordances

For a shared (ancestor-owned) node, matched to three genuinely different author intents:

1. **Direct edit** → writes the *owning layer's* file; visible everywhere downstream. The common case:
   correcting or enriching canon. One canon.
2. **Per-field override** → a sparse, layer-scoped delta on specific fields; the base entry is
   untouched, and **un-overridden fields keep resolving against the live ancestor**, so later canon
   corrections still flow down. Solves cross-book continuity (Honor is Commodore in the series base, a
   Captain by Book 12) without forking or walking prior books.
3. **Fork** → copy the whole node down to the current level and **stop inheriting** from here. For
   alternate-timeline / what-if books. Explicit, coarse, rare.

Override and fork are distinguished by *inheritance*, not by granularity: an override stays linked to
its ancestor; a fork severs the link. That is why whole-node override is rejected as an *override*
granularity while fork — which is a whole-node copy — remains a distinct, useful affordance.

**A fork keeps the node's id.** For an alternate-timeline book it is the same entity rendered
differently, so inbound references from ancestor entries must resolve to the fork *within the forking
project*. ADR-0040's `id → [candidates by layer]` provides exactly that, with the ancestor still
reachable as a shadowed candidate. Front matter carries `forked_from`, which is what declares the
severance and what suppresses the shadow warning `resolve()` already emits (`node_index.py:179`) — the
warning stays loud for *accidental* collisions.

`forked_from` records the **relative path from the base folder** to the owning layer, not a layer id.
The only layer identity in code is `_layer_id_for_folder` (`layers.py:64-85`) — sha256 of the
resolved path, first 16 hex chars — which
is machine- and location-dependent — persisting it into front matter breaks the moment the shelf is
moved, renamed, or opened on another machine, and "layer rank" is an ordinal within one chain, not a
durable identifier. A relative path survives all three.

**Glyph: unresolved, not settled.** `⧉` is in the lexicon as *"duplicate — fork the item into a new
editable copy"*, and the lexicon's governing rule is that a glyph earns its place *"only by meaning
the same thing everywhere"*. A fork here **keeps the id**, so it is not a duplicate — reusing `⧉`
would make it mean two things. Folded into **#304** with the other marks rather than asserted away.

### An override is a delta, built on the mutation structure

A layer override is a **body-less Node** under `overrides/`, carrying the **same op vocabulary as a
scene mutation** — set / add / remove — over the target's fields. One file per (layer, target).

**It reuses the mutation ops rather than inventing a second dialect**, and that is the point:
`_resolve_collection` (`lore_mutations.py:727-740`) already resolves multi-valued fields as
`(base ∪ adds) ∖ removes`. Without ops, an override could only *replace* a list — so adding one alias
would mean restating the whole list, after which later ancestor additions to that field silently stop
arriving. One collection rule in the codebase, and an author who already knows the vocabulary from
mid-scene mutations.

**Rejected: a sparse lore entry with the same id in the layer's own `lore/`.** Tempting — it needs no
new kind, no folder, and the shadow chain is already the fold input. But it makes a *delta*
impersonate a *node*: it cannot be read standalone, it fails `_validate_lore_entry_metadata` (which
validates a complete metadata dict), its sparseness is invisible without an out-of-band marker, and it
still cannot express add/remove on a multi-valued field. A delta should look like a delta.

**The join key is `target: <node-id>` in front matter — not the filename.** Filenames track the
*title*: `_filepath_for_new_node` sanitizes it, `_maybe_rename_node_file` renames on every title
change, and collisions get a `Name (2).md` suffix — so the same entity can have different filenames at
different layers even without a rename. `project_service.py:367` states the invariant: *"the on-disk
filename is cosmetic — the front-matter `id` is the canonical identity."* A filename join orphans
silently the first time an author retitles an entry.

**The override node's own id is `sha256(layer_id + target_id)`** — deterministic, distinct per layer
(so a series override and a book override of the same entry do not collide in the index), stable
across sessions, and needing no uniqueness registry. Overrides are filtered out of reference pickers
and view results; they are deltas, not pickable nodes.

**Composition across layers is descendant-wins per item** — deliberately *diverging* from the
mutation rule it otherwise copies. Mutations use remove-wins because two mutations at the same
manuscript position are genuinely unordered; layers are **totally ordered by rank**, so last-writer-
wins is available and is the intuitive reading — a book that re-adds an alias its series removed
should get it. Under remove-wins that case is inexpressible, and there is no migration between the two
rules once files exist. (ADR-0042 may still overturn this; it is the one override semantic that the
gesture work could reasonably revisit.)

### Provenance is first-class and must be visible

Every resolved node carries its **owning layer** (and, for a fork, its shadow stack). This supplies
the override resolution keys, the fork target, and the navigation surface — it rides the index's layer
rank (ADR-0040).

**An author must be able to see that a value is an override rather than authored canon**, and to tell
that apart from a *mutation*. Two surfaces carry it — a **level pill on the NodeRow** in lists, and a
**layer treatment on the metadata fields rail** when an entry is open, since the rail is where an edit
that reaches an ancestor most needs to be visible. The **form of the mark** — mutation glyph in another
colour, a different glyph, or a non-glyph treatment — is deliberately not settled here: the existing
mutation marker `⤳` is itself outside the closed glyph lexicon, so both marks enter it together under
**#304**. This ADR requires only that the tell exist and be distinct.

## Amendment 1 — inheritance is *declared*, over a filesystem-enumerated candidate list (2026-07-19)

The original decision inferred the chain from folder placement: walk to the base folder, and (per the
now-superseded blockquote above) treat every ancestor carrying a `project.yaml` as a layer. Review of
slice **A** showed that inference cannot answer two questions without guessing at author intent —
whether the marker also gates the *metadata-schema* walk, and whether a non-project ancestor
**breaks** the chain or is **skipped**. Both have defensible answers and opposite failure modes; under
"break", inserting an organizational folder mid-shelf silently removes a user's universe canon.

**The user declares it instead.** Two steps, in this order, and the order is the whole point:

1. **Enumerate candidates by walking the filesystem to the base folder.** Unchanged from today, and
   **finite by construction** — directory traversal terminates, so the candidate list is complete and
   cycle-free before anyone declares anything.
2. **The project records which of those enumerated ancestors it inherits from.** A declaration naming
   anything outside the enumeration is ignored with a warning; it cannot extend the walk.

Gaps are now legitimate rather than ambiguous — skipping `Shelf/Weber/` is a recorded choice, not an
inference the app has to make. This is the same principle the ADR already applies to node edits:
divergence must be explicit. Inferring an inheritance structure from where a folder happens to sit is
exactly the implicit magic that auto-shadow-on-edit is rejected for.

**Rejected: a `parent:` link resolved transitively.** Superficially cleaner — one field, chain by
transitivity, gaps free. But a link is *data in a user-editable file*, so `A → B → C → A` is reachable
by hand-editing `project.yaml`, and the app would need cycle detection on every chain resolution to
defend against a problem it introduced. Enumerate-then-declare cannot cycle, because the enumeration
is a directory walk. **Do not reintroduce transitive links to "simplify" the declaration** — the
finiteness is the feature.

**The change is contained.** `_project_layer_folders` still returns an ordered `list[Path]`; only its
body changes, from "every ancestor" to "the declared subset of every ancestor". Both consumers —
`_metadata_schema_layer_paths` and `_build_node_index` — enumerate that list and are untouched, as are
layer rank, candidate lists, and the ADR-0040 manifest. It also resolves the schema-walk question by
construction: one declared chain serves node inheritance *and* schema layering, so they cannot diverge.

**Where the declaration is made:** the create-project wizard, which presents the enumerated ancestors
and lets the author tick the ones to inherit from. Editable afterwards in project settings.

## Amendment 2 — one traversal, and the root is stipulated (2026-07-19)

Amendment 1 said the walk "enumerates candidates by walking the filesystem to the base folder" and
**never defined what determines the base folder**. The code does, dynamically and invisibly:
`_metadata_schema_base_folder` (`layers.py:361`) ignores the configured
`projects_base_folder` whenever it equals `root.parent` — *which the project chooser writes on every
create* — and substitutes the **outermost** ancestor anywhere up `root.parents` that happens to
contain a `metadata.schema.yaml`. A stray schema file in a grandparent directory therefore sets the
extent of schema layering, the node index **and** the assistant roster. This ADR made inheritance
explicit while leaving its outer bound implicit and file-triggered.

**The root is stipulated, never inferred from a file's presence.** The walk's extent comes from the
project's own declaration (Amendment 1) with `projects_base_folder` as the bound. The
`metadata.schema.yaml`-presence widening is removed. A project whose schema layering depended on it
declares those ancestors instead — which is the point of Amendment 1.

**There is exactly one traversal, and every consumer visits it.** Today there are six derivations of
the same chain, which is why a change to "how far do we walk" cannot be made in one place:

| | today | derives |
|---|---|---|
| 1 | `_project_layer_folders` (`layers.py:331`) | the chain, root → base |
| 2 | `_metadata_schema_base_folder` (`layers.py:361`) | where #1 *stops* — the widening above |
| 3 | `_metadata_schema_layer_paths` (`layers.py:419`) | maps #1 → schema files |
| 4 | `_build_node_index` (`references.py:260`) | iterates #1, building `IndexLayer` inline |
| 5 | `assistants.py`, line 75 as it then stood | layer folder from `entry.path.parent`, **rank from index insertion order** |
| 6 | `references.py` line 183 / `assistants.py` line 219, likewise | the machine layer, special-cased outside the chain |

> Rows 4–6 describe the code **as this ADR found it**, and #329 answered them: the traversal is now
> single and lives in `layers.py`, `IndexLayer` is declared once with an **explicit** `rank`
> (`node_index.py:30-36`) instead of one inferred from index insertion order, and the machine layer
> is an ordinary layer in the walk (`include_machine=True`) rather than a special case beside it.
> Rows 1–3 are still live code, re-verified 2026-07-22.

`IndexLayer(folder, id, label)` (#305) is already the right value object; it is merely private to the
index build, constructed inline by `_build_node_index` with rank implied by `enumerate`. Promote it:
a single walk yields `IndexLayer` objects stamped with folder, id, label, **explicit rank** and
`is_root`, and yields the machine assistants layer as an ordinary out-of-tree layer rather than a
special case at two call sites. Schema merge, node index, assistants, settings/AI-policy resolution
(slice F) and provenance all consume that one sequence.

**Why this is a prerequisite rather than a cleanup.** When the create-project wizard lands and makes
the declaration explicit, "how far do we traverse" must change in **one** place. With six derivations
it changes in six, and #305 already showed how that goes — the index build grew its own layer walk
while `assistants.py` kept inferring rank from insertion order, which an incremental patch (#307)
would silently reorder. Slice F (#312) was attempted against this substrate and had to be rolled
back.

**Sequencing consequence:** the unified walk lands **before #306**. The snapshot's manifest and layer
ranks are keyed on the chain, so persisting a format whose extent and rank semantics are still
unsettled builds on sand — and #309 waits on #306.

## Amendment 3 — should the declaration be read transitively? (**Proposed**, 2026-07-23)

> **Status: Proposed. Anton decides.** This amendment states the question, prices three answers and
> recommends one; it does not adopt anything. Nothing below is implemented.
>
> **Citations.** There is no tag newer than `v0.6.5`, which predates #309 entirely, so the house rule
> (an ADR quoting `file:line` names the tag it was written against) has nothing to name. Every
> citation below was verified against **`origin/master` at `f743203`, 2026-07-23**. Cite that commit,
> not this file's line numbers, when checking a claim.

### What forced the question

A real chain — The Honorverse › Honor Harrington › On Basilisk Station › Part Two — walked **down**
four levels and could not walk back **up**, because Part Two declares nothing. The two directions are
wired to one control and do not round-trip:

- **descent is a filesystem fact** — `_project_children` (`lifecycle.py:188-213`) lists subfolders
  carrying a `project.yaml`, and asks no manifest for permission;
- **ascent is a declaration fact** — `_project_layer_folders` (`layers.py:331-359`) keeps the
  ancestors this project's own `inherits:` names, and reads **no** ancestor's declaration.

### Four defects were bundled into one question — separate them first

Only the third is an argument about transitivity. The others are true under every option here, and
adopting transitivity would fix none of them.

1. **No project the app creates declares anything.** `_scaffold_project` /
   `_new_project_manifest` (`lifecycle.py:55-123`) never write `inherits`, and
   `CreateProjectRequest` (`models/project.py:11-17`) has no field to carry it. So the chain is
   empty for essentially every project that exists, and the breadcrumb is empty with it. This is an
   **authoring-default** defect owned by #318, not a semantic one.
2. **Descent and ascent are different relations rendered as one control.** Also true with a full
   chain declared: "contains" and "inherits from" are not each other's inverse and never were.
   Owned by the UX design (`docs/design/hierarchy-navigation-ux.md`), not by this amendment.
3. **Retroactive insertion costs N edits.** Put a universe above an existing series and the series
   picks it up with one edit; its books do not pick it up at all until each one is edited. **This is
   the only defect transitivity fixes**, and it recurs for the life of a shelf, which is what makes
   it worth an ADR rather than a default.
4. **The switcher's recents read as a breadcrumb**, which is how a stale entry got clicked (#423).
   A demarcation defect; see the UX doc.

### The cycle objection in Amendment 1 does not reach this proposal — with one condition

Amendment 1 rejected *"a `parent:` link resolved transitively"* because a free-form pointer in a
user-editable file admits `A → B → C → A`. That argument is sound and is **not** an argument against
transitive closure over *this* declaration, because a declaration here can only ever **select from a
filesystem walk** (`ancestor_candidates`, `layers.py:234-267`).

The termination argument, precisely: define `closure(P) = D(P) ∪ ⋃_{A ∈ D(P)} closure(A)`, where
`D(P)` is the set of folders `P` declares **that are genuine project ancestors of `P`**. Every edge
`P → A` strictly decreases filesystem depth, so the relation is a DAG whose longest path is bounded
by `depth(P)`; the closure terminates in at most that many hops and can never revisit a node.

**The condition is load-bearing: the per-hop filter is what supplies `D(P)`, and it is not what
`inherits:` gives you.** `_declared_ancestors` (`layers.py:269-298`) resolves the raw strings and
validates *nothing* — deliberately, because it is a read; the ancestor test lives one call later, in
`_project_layer_folders`'s comprehension over `ancestor_candidates`. A stored entry is a **relative
path** that can drift when a folder moves (`_validated_declaration`, `lifecycle.py:247-273`, validates
only on write), so a raw entry can resolve sideways or downward. **A closure built by unioning raw
`inherits:` lists across hops therefore has no termination guarantee at all.** It must re-apply the
ancestor filter *at each hop, relative to that hop's own root*. Any implementation of this amendment
states that as an invariant and pins it with a test using a hand-written cyclic pair of manifests.

### Ordering survives closure untouched — and this is why transitivity is cheap here

`closure(P)` is a set of filesystem ancestors of `P`, and filesystem ancestors of one folder are
**totally ordered by depth**. So the chain remains a sequence, `rank` remains well defined, and
descendant-wins remains unambiguous. There is no diamond, no linearization, no C3 — the ordering
problem that makes transitive inheritance expensive in a language type system does not arise, because
the partial order is supplied by the filesystem rather than by the declarations. The walk
(`_layer_sequence`, `layers.py:151-181`) changes only in which folders it is handed.

### What transitivity costs — the honest list

1. **Exclusion becomes inexpressible, and this is the real loss.** Today the declaration is *exact*:
   the set is precisely what you named. Under closure it is a **lower bound** — you can still skip
   *upward* past a level (declare the grandparent, not the parent: `test_a_gap_is_legal`,
   `backend/tests/test_declared_chain.py:72-80`, still passes), but you can no longer **stop short**:
   declare the parent and you inherit everything the parent inherits, whether or not you want the
   shelf-wide canon above it. Restoring it means an `excludes:` key — a second declaration whose only
   job is to contradict the first, which is the free-form complexity Amendment 1 spent. **Recommended:
   no exclusion.** The escape hatch is to declare the *grandparent* directly instead of the parent, or
   to move the folder; if a real case survives that, it earns its own amendment.
2. **"Each project's list is complete for itself" is spent.** A grandparent's edit silently changes
   what a book inherits. That is precisely the property being bought — but it makes provenance a
   requirement rather than a nicety, which pulls the *labelling* half of #313 forward (the crumb and
   the wizard row must say *declared* vs *implied*). The **mark** half of #313 stays where it is,
   still blocked on #304.
3. **The chain's identity is now a function of N manifests.** Anything keyed on "which layers, in
   which order" must fingerprint every `project.yaml` in the closure, not the open project's alone —
   the index snapshot and its manifest (#306/#307), the memo key (#392), and the definitions cache
   key (#394, whose "chain identity" bullet is written assuming one declaration decides it). The
   files are already stat-ed per layer; what changes is *which* file set determines the shape.
   Cheap, and wrong if left implicit.
4. **Validation acquires a second subject.** `declared_ancestor_warnings` (`layers.py:300-329`)
   reports one project's own bad entries. Under closure, a broken declaration three levels up
   degrades this project's chain, so a warning must name **whose** declaration failed — otherwise the
   author of Part Two sees canon go missing with a clean validation report on their own file.
5. **Per-open cost: one `project.yaml` read per declared ancestor.** Bounded by chain depth, and
   #420 already reads each ancestor manifest for its title. Effectively free.

### The one genuinely new decision: whose bound applies

Every `project.yaml` carries its **own** `settings.projects_base_folder`
(`_metadata_schema_base_folder`, `layers.py:361-391`), and an ancestor's declaration was validated
against *its* bound. So a series whose base folder is wider than a book's can pull in a folder that is
a filesystem ancestor of the book but sits **above the book's own base**. Termination is unaffected;
the invariant `test_a_folder_outside_the_base_cannot_be_declared_into_the_chain`
(`test_declared_chain.py:86-92`) protects is not.

- **(a) Clamp to the opener's bound** — intersect the closure with the open project's own
  `ancestor_candidates`. `projects_base_folder` stays a hard ceiling on everything the open project
  can ever see; a level that falls off is dropped with a warning naming it. **Recommended.**
- **(b) Honour the declaring layer's bound** — the shelf says what the shelf is, and a book's base
  folder governs only its own enumeration. Simpler to describe, and it silently removes the one
  guarantee `projects_base_folder` currently makes.

### …and the decision dissolves if the bound moves to the machine layer

Anton's question, and it is the better answer: **`projects_base_folder` is per-project only by
accident.** Move it up and the sub-decision above stops existing — there is one bound per *location*
rather than one per manifest, so a closure cannot exceed it by construction and there is nothing to
clamp.

Four facts that say the current placement is the anomaly, verified at `f743203`:

1. **It is already half at the machine layer.** `MachineSettings.default_projects_folder`
   (`models/ai.py:45`) is a machine-level projects folder — used as the picker's default, while the
   *bound* lives in each `project.yaml`. Two settings, one concept, trivially confusable.
2. **It is stored as an absolute path** (`_new_project_manifest`, `lifecycle.py:104-123`, writes
   `str(base_folder)`), duplicated into every manifest on the shelf. That is a machine fact wearing a
   file's clothes: it survives neither a move, nor another machine, nor a different drive letter.
   Removing it makes the project folder **more** portable, not less — which is the opposite of the
   usual files-are-truth objection to machine config.
3. **A shelf can already disagree with itself.** `_metadata_schema_base_folder(root)`
   (`layers.py:361-391`) reads *the open project's* manifest, so a series and one of its books may
   carry different bounds — and the same folder chain then enumerates differently depending on which
   end you open it from. That is a live inconsistency today, with or without transitivity.
4. **A per-project bound buys nothing a shelf-level one does not.** Nobody wants two books on one
   shelf to see different amounts of that shelf; when they do, that is what `inherits:` is for.

**Shape, if adopted: the machine layer holds a list of shelves, not a single folder.** A single value
breaks the author with two shelves on two drives. A project's bound is then *the nearest registered
shelf containing it* — a function of location, which is why every project on a shelf necessarily
agrees. A project inside no registered shelf is a **chain of length one**, with an offer to register
its folder; that is today's "root is not inside `projects_base_folder`" warning
(`schema.py:937-941`), except recoverable with one action instead of editing N manifests.

**Rejected: a marker file at the shelf root** (`shelf.yaml` or similar). It is the files-are-truth
answer and it is portable — but finding the shelf then means walking upward until a file appears,
which is exactly *"the root inferred from a file's presence"* that **Amendment 2 removed**. A machine
registry is the stipulated version of the same thing, and stipulation is the property Amendment 2
bought.

**On the name.** The layer is currently `"Machine"` (`machine_layer`, `layers.py:201-232`) and
"application layer" reads better — but the two names are not synonyms, and there are genuinely **two**
tiers here, only one of which is in the walk:

- **the application tier** — `DEFAULT_METADATA_SCHEMA`, merged as tier 0 by
  `_read_metadata_schema_through_path` (`schema.py`) and shipped in code. It is not an `IndexLayer`
  at all; it has no folder, so the walk cannot see it.
- **the machine tier** — `%APPDATA%\local-writing-app` (`config_dir`, `machine_settings.py:115-126`),
  holding assistants, palette, recents and **credentials**. Those last two are per-computer facts by
  definition, and would be a lie under the name "application".

So: rename to *Application* only if the built-in tier is simultaneously given a name and, ideally,
made a real layer in the walk — otherwise the rename takes the one accurate name in the pair and
leaves the genuinely-application tier nameless. A shelf registry belongs on the **machine** tier under
either naming.

**What it costs.** `_rebase_projects_base_folder` (`lifecycle.py:128-142`) and the
`projects_base_folder` field on the open/create requests lose their subject; the pending-`base`
parameter threaded through `ancestor_candidates` / `_validated_declaration` for the wizard's
widen-and-declare gesture stays, but now describes a *global* widening, which is a different consent
question and needs saying in the UI. Pre-1.0, the stored key is simply ignored — no migration
(`feedback_no_pre_1_0_migrations`).

**This is a separate issue from Amendment 3**, and it is worth filing whether or not transitivity is
adopted — it removes fact 3's live inconsistency on its own. If both are adopted, **it should land
first**: it deletes this amendment's only genuinely new decision instead of answering it.

### The three options

| | option | fixes #3 (insertion) | keeps exact declaration | cost |
|---|---|---|---|---|
| **A** | **Symmetrize descent**: children become *children that declare this project* | no | yes | near-zero code; **hides real projects** (see below) |
| **B** | **Transitive closure**, per-hop-filtered, clamped to the opener's bound, no exclusion | yes | no | §"costs" above; pulls #313's labelling forward |
| **C** | **Name the two relations**; fix the create-time default; leave semantics alone | no | yes | UX work only |

**A is not recommended.** It buys symmetry by making the roster *smaller* than the filesystem: a book
sitting inside a series that never declared it would stop being listed by its own parent, even though
the folder is right there. Hiding something that demonstrably exists on disk is a worse failure than
an asymmetric affordance, and it is against files-are-truth. Symmetry is the wrong goal here — the two
relations are genuinely different, and the fix is to **say so**, not to shrink one until it matches.

**C is required under every option**, including B: naming the relations and defaulting the declaration
at create time are what dissolve the reported failure (under a sane default, Part Two declares its
parent and the breadcrumb is never empty). **B is the semantic change**, and it stands or falls on
defect 3 alone.

**Recommendation: C now, B after** — adopt C's UX and the create-time default with #318, and take B as
a separate, testable change with the per-hop filter, the clamp, the multi-manifest chain identity and
the attributed warnings landing together. Splitting them keeps the semantic change from being merged
into a wizard PR, which is where its four obligations would go missing.

## Why / rejected alternatives

- **Overrides as a tier inside `effective_state`** (the earlier draft's central claim: an added layer
  `universe base → series → book-start → mutations`, "not a resolver rework"). **Rejected — the code
  contradicts it.** `effective_state(entity_id, scene_id, position, …)`
  (`lore_mutations.py:610-678`) keys on manuscript position exclusively and returns `{}` when the
  scene is not in `scene_order` (`:651-654`); its override corpus is built solely by scanning
  manuscript scene bodies (`:470-497`), ordered by `(manuscript position, prose offset)`. A layer
  override has no scene and no position, and a universe level has no manuscript at all — there is no
  coherent way for it to enter that ordering. Implementing it there would mean rewriting
  `_entity_base_values`, inventing a non-positional rank, and fixing up `_resolve_collection` /
  `_resolve_text_append` — precisely the resolver rework the claim denied. Folding at materialization
  keeps `effective_state` untouched.
- **Fixed three-tier types (universe/series/book).** Rejected: David Weber — the stated worst case —
  has *multiple* universes (Honorverse, Safehold, …) with an author grouping above them; depth is
  open-ended. Folder depth already expresses any shape, and the code layers by depth, not named tier.
- **Auto-shadow on edit** (silently write a per-book copy whenever you edit a shared entry). Rejected:
  it forks canon into N drifting versions on every casual edit — the exact consistency bug nesting
  exists to prevent. Divergence must be *explicit*.
- **Whole-node override granularity.** Rejected in favour of per-field: it keeps overrides *sparse* —
  a book overrides the handful of fields that actually diverge. At Weber scale, coarse copy-down would
  duplicate thousands of canonical entries; sparse overrides keep the ancestor layer single-sourced
  (and, per `memory/strategy_ai_integration.md`, the most cache-stable prompt block). Copy-down remains available
  deliberately, as **fork**.
- **A single `overrides.yaml` per layer.** Rejected: fewer files, but it needs bespoke merge, indexing
  and provenance code, against a Node-shaped alternative that needs none.

## Consequences

- **ADR-0005 is untouched — this ADR does not amend it.** 0005 decided *scoping*: the book is the
  resolution boundary, base is the lore file at book-start, cross-book walking is out of scope. All of
  that holds verbatim; the layer fold simply produces that book-start base. 0005's parenthetical guess
  at a future shape (`base → book_start_overrides → mutations`, storage on `project.md
  starting_state`) is **not adopted** — it predates hierarchies, puts overrides inside the resolver,
  and is the origin of the rejected framing above. `starting_state` exists nowhere in code and is not
  introduced.
- **ADR-0013 gains an amendment.** Its scrubber, discrete stops, stop-0-editability and total scope
  are unaffected — the layer axis has one value per open project and therefore does not scrub. What
  changes is that "base" at stop 0 is now a *resolved* state, so *which file* an edit at stop 0 writes
  to is no longer self-evident. That is the gesture question (ADR-0042). Recorded as Amendment 1 there.
- **The "which scope is effective?" question is dissolved, not deferred.** Because materialization
  yields one member set for the open project, effective **edges** for layer overrides are baked into
  that member set by the index — there is no scope parameter to thread through consumers, and no
  query-time delta for backlinks / `References` / Nest to apply. The split is clean: **layer overrides
  are position-independent and can be materialized; scene mutations are position-dependent and cannot**
  (they stay resolved at query time, as today).
- **Ordering is inherited too, not just content — and it *was* the exception when this was written.**
  **No longer: #332 took the layer term off the sort key** (`assistants.py`, `sort_key` — position in
  one merged sequence, then an alphabetical tail; verified at `f743203`). The paragraph below is kept
  as the record of the concern and where it was answered; do not read its present tense as live code.
  Assistants
  carry a manual priority sequence (`.order.yaml` per layer, `assistants.py:128-142`) where **topmost
  is the default** (ADR-0024). That makes position load-bearing rather than cosmetic, and it is the
  one place the chain is composed *without* the descendant-wins rule this ADR applies everywhere else:
  the effective order sorts on `layer_rank` first, and `layer_rank` is not stored — it is the order
  entries stream out of the index (`assistants.py`, line 76 as it then stood), with the machine layer
  collected first. So a project-level assistant can never outrank a machine one, whatever the
  user does. **Overtaken since:** #329 made rank explicit on `IndexLayer` rather than inferred from
  insertion order, and #332 took the layer term off the front of the sort key entirely
  (`assistants.py:168-174`) — one merged sequence across every layer, where position *is* precedence.
  The concern was real; this is where it was answered. Whether an ordering *inherits* — innermost layer that names an entry decides its position
  — is **#332**, and it must be settled before the wizard (#318) offers an ordering step. The general
  point for any future layered list: *the order is part of what layers, and it needs the same
  descendant-wins answer as the content.*

- **Settings / AI-policy resolution must extend to the chain.** Today AI settings read only the open
  project's own `project.yaml`; they must resolve `system → …chain… → prompt` over the same layer walk.
- **`revision` must span the fold.** `read_lore_entry` returns `revision=self._revision(path)` — a hash
  of *one* file (`read_lore_entry`, `services/project/lore.py:116`). Once an entry is folded, editing an override leaves
  the ancestor's hash unchanged, so optimistic concurrency in `save_lore_entry` (`services/project/lore.py:128`)
  accepts a stale buffer **and** the AI
  prompt cache, which partitions stable/volatile blocks on `entry.revision`
  (`services/ai/helpers.py:746-767`), keeps serving pre-override canon. The revision must be composite
  over the ancestor file plus every override in the chain. Slice E owns it.
- **Saving an inherited entry must not write the fold upstream.** `save_lore_entry` resolves its path
  through `by_id[id].path` — the *ancestor's* file (`lore.py:125`). Left alone, opening an inherited-
  and-overridden entry and pressing save promotes every override into ancestor canon, downstream to
  every other book: the auto-shadow failure this ADR rejects, reached by not deciding. What a stop-0
  edit writes to is exactly the gesture question — **ADR-0042 (#308)** — which is why slice E is
  blocked rather than merely unscheduled. Until it lands, saving an inherited entry must fail loudly
  rather than silently choose a target.
- **ADR-0040 is a prerequisite** — on materialization grounds, not only latency. It is the mechanism
  this ADR's inheritance *is*. Its backend implementation is #305 → #306 → #307 (the last being the
  backend half #200 never landed, having closed 2026-07-19 with only the frontend change-gate).
- **The `project` node stays a per-folder singleton** but now participates in navigation (the child
  roster) and must be indexed — its id is the constant `"project"`, so it collides at every level of
  any chain unless identity is layer-qualified (ADR-0040). Same `ProjectNode` model represents
  universe/series/book by field values — no new kind.
- **Slices for #7**, cut to issues:

  | | slice | issue | status |
  |---|---|---|---|
  | **A** | declared inheritance (Amendment 1) + discover ancestor chain and children on `ProjectInfo` | #309 | after #306 |
  | **B** | open a non-leaf level (canon + child roster, no manuscript) | #310 | after A |
  | **C** | frontend breadcrumb / level switcher | #311 | after B |
  | **F** | settings / AI-policy chain resolution | #312 | ready, independent |
  | **D** | provenance surfacing (level pill + rail treatment) + fork-to-here | #313 | blocked |
  | **E** | layer overrides (`overrides/` deltas on the mutation structure) | #314 | blocked |

  **A** needs #306 first — the project node's id is the constant `"project"`, so it collides at every
  layer until identity is layer-qualified. **D** and **E** additionally need ADR-0042 (the gesture,
  #308) and the mark decision (#304). Index prerequisites: #305 (single-pass) → #306 (snapshot) →
  #307 (incremental + change-gate).
- **Explicitly deferred:**
  - **Promote-upward** — move a node to an ancestor level (symmetric to fork-down).
  - **Layer-scrubbing** — "show me this entry as the *series* sees it". Genuinely useful for provenance
    debugging, and ADR-0013's scrubber is the precedent, but it is the resolution-position-dimension-
    on-views item and belongs with Views 2.0.
  - **Series/cross-book mutation collation** — auto-rolling a book's accumulated mutations into the
    next book's opening override set. 0.7.0 authors overrides explicitly. *(0005 scoped cross-book
    walking out of v1 for lack of payoff; this is the deferred convenience on top, not a permanent
    rejection.)*
- **Overriding a `body` field.** ADR-0013's scope is deliberately total — title, body and every field
  travel. Overrides are per-field and body is a field, so a layer-level body override is expressible
  and lands on 0013's buffer-safe read-only body overlay. Permitted; slice E states the interaction.
