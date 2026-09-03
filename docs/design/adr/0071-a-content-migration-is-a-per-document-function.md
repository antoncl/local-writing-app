# ADR-0071: A content migration is a per-document function; the registry names each step's scope

- Status: **Accepted** — 2026-08-22, Anton (reviewed in-thread across three revisions: the 0.9.5
  boundary, the four-encoding content surface incl. override deltas, and the inheritance/ownership rules;
  a cold-implementer pass caught the free-function/instance-seam mismatch and two contradictions before
  approval). Restore-wiring (§7) kept in #366; slicing per the author.
- Verified against `03c9e69c` (2026-08-22).
- Feature: #366 · Realises: ADR-0043's "migrate at restore, over that one body" · Follows: ADR-0040
  (the node index + `overrides_by_target`), ADR-0039/0042 (override deltas), ADR-0001/0011 (mutations),
  ADR-0056 (a boundary is a choke point) · Constrains: `services/migrations.py`
- Supersedes nothing. Provides the mechanism ADR-0043 declared a hard pre-gateway requirement.

## Problem

`MigrationFn = Callable[[Path], None]` (`migrations.py:49`; registry `MIGRATIONS` at `migrations.py:89`)
takes a project **root** and mutates the tree in place. Every shipped step is project-shaped —
`_create_snippets_folder` (`migrations.py:52`), `_create_research_structure` (`migrations.py:57`).
That shape cannot express *transform one document's content*.

Nothing needs it today. **From the 0.9.5 gateway on**, something will: 0.9.5 is the data-durability
boundary — after it real drafts are migrated in place, not recreated
(`strategy_migration` / `feedback_no_pre_1_0_migrations`), so the first content migration (a
front-matter key rename, a marker-grammar change, a metadata value re-encoding) arrives, and it has
nowhere to run over a body held outside the live project tree. Two facts make the gateway the deadline,
not a someday:

- **ADR-0043 already committed to it.** Snapshots are immutable and migrate **at restore, over that
  one body, on the way out** — the stored record is never rewritten (`models/snapshots.py:172-175`).
  Each snapshot sidecar already freezes its capture-time `schema_version` (`scene_snapshots.py:337`,
  model `snapshots.py:175`) precisely so a restore can run the ladder from there. But no such ladder
  exists: `restore_snapshot` (`scene_snapshots.py:400`) is a raw byte copy (`_atomic_write_bytes`,
  `scene_snapshots.py:426`) that ignores the version. The intent is in the code; the mechanism is not.
- **Retrofitting after real data exists is the expensive order** — hence the hardening milestone, not
  "discovered by whoever writes the first content migration" (#366).

This ADR defines the *mechanism*. Per `feedback_no_pre_1_0_migrations` (boundary now 0.9.5), it writes
**no** content migration now; it makes the shape available, wired, and tested before the gateway.

## Decision

**A migration step declares its scope, and content steps are authored as per-document functions applied
to every content-bearing file the project owns.**

### 1 — Two shapes, named in the registry

- **Root-scoped** (`MigrationFn = Callable[[Path], None]`, unchanged): project-shaped changes — folder
  creation, cross-file moves, `*.structure.yaml` edits (see §6). Anything genuinely project-shaped.
- **Document-scoped** (new): `DocumentMigrationFn = Callable[[MigratableDocument], MigratableDocument]`.
  `MigratableDocument` is a frozen value `(front_matter: dict, body: str)` — `front_matter` is the
  **entire** parsed front-matter mapping (what `_read_markdown_with_front_matter`, `project_service.py:436`,
  yields), `body` the markdown after it. It transforms **one document in isolation**: no root, no
  filesystem, no sibling documents. Pure.

The registry carries the distinction as a **type**: frozen dataclasses `RootMigration(version,
description, fn)` and `DocumentMigration(version, description, fn)` in one ordered
`MIGRATIONS: list[RootMigration | DocumentMigration]`. The shape is visible at the registration site and
the fn signature enforces it — an author picks deliberately, not by default (#366 acceptance).

### 2 — The invariant that separates them

**Root steps never transform document content; document steps never depend on project structure, the
filesystem, or sibling documents.** This lets the two axes run independently, makes the equivalence
guarantee hold *by construction*, and — because each document step, like the shipped root steps
(`mkdir(exist_ok=True)`), must be **idempotent** (re-applying to an already-migrated document is a
no-op) — makes the retry-on-open path (§4) safe. A step that needs both axes is two steps at two
versions.

The invariant also forbids reading the live schema: a document step is **authored against the known
format at its version transition** — a built-in field's type at v(N-1)→vN is fixed history, encoded in
the step itself — so it never introspects the merged (possibly *inherited*) `metadata.schema.yaml` at
runtime. That is what keeps it pure and portable to a body migrated in isolation (a snapshot on
restore), where no live project schema is even in scope. A migration that would need to resolve values
against the runtime merged schema — a type-dependent re-encode over *user-defined* fields — is therefore
not expressible as a pure per-document function; none is anticipated, and its shape is deliberately not
sketched here (the P2 trap).

### 3 — The content surface a document migration must reach

This is the load-bearing correction, because **a single field key or value lives in up to four
encodings, and only three of them are nodes in the index:**

| Encoding | Where | In the node index (`by_id`)? |
|---|---|---|
| entry **metadata** (lore, scene, …) | node front-matter `metadata:` | yes |
| `mutation_set` **rows** | `mutation-sets/*.md` front-matter `rows:` | yes (kind `mutation_set`) |
| in-scene **mutation markers** | the scene **body** (`<!-- mutate:…field=…value=… -->`, `lore_mutations.py:71`) | yes (scene node; content in body) |
| **override delta rows** | `<layer>/overrides/*.md` front-matter `rows:` (`overrides.py:14-18`) | **NO — deliberately excluded** (`overrides.py:19-23`; collected in the parallel `overrides_by_target` pass, `references.py:451`) |

So "walk the index nodes and migrate each one" is **insufficient**: it silently misses every override
delta, leaving pre-migration keys/values in `overrides/*.md`. The document pass therefore enumerates
**every content-bearing file the open project owns — the index nodes *and* the open layer's
`overrides/*.md`** — reading each as `(front_matter, body)`. The `(front_matter, body)` unit still
suffices for all of them (override and mutation_set content is in front-matter `rows:`; scene mutations
are in the body). A `DocumentMigrationFn` is therefore **kind-aware**: it reads `front_matter`
(`entry_type`) and transforms the representation that kind uses — a `metadata:` block, a `rows:` list,
or body markers — returning kinds it doesn't concern unchanged. Authoring the fn to cover each
representation a change touches is the migration author's job; the framework's contract is that the pass
*delivers the fn to every content-bearing file*, so none is a blind spot.

### 4 — The unit's home, the seam, and the two runners

The **pure** pieces live in `migrations.py` (no service dependency): the registry + types,
`DocumentMigrationFn`, `MigratableDocument`, version I/O (`read/write_project_version`), `backup_project`,
and `migrate_document(doc: MigratableDocument, from_version: int) -> MigratableDocument` — the document
subladder from `from_version` to `CURRENT_VERSION`, over one body. This is the isolated entry point:
no root, no service, unit-testable (acceptance) and callable from restore.

The **orchestration and the document pass** live on `ProjectService` (a mixin), because they need the
node-index walk, the override enumeration, and the serialization seam — all instance methods; the free
`migrate_project(root)` is called at `project_service.py:181` *before* the instance is constructed
(`:184`) and cannot reach them. Migration runs **through the service instance on open, before it serves
any request**:

1. `current = read_project_version(root)`, captured **once**, before anything is stamped.
2. If any step is pending, `backup_project(root, current)` (the existing zip; every content-bearing
   file — index nodes and `overrides/*.md` — lives under `root`, so all are covered).
3. Run pending **root** steps against `root`.
4. **Document pass:** for each content-bearing file the open project owns (§3), read `(front_matter,
   body)`, apply `migrate_document(doc, current)`, and **write it back only if a step changed it** (an
   untouched document is left byte-for-byte alone — no mtime churn, no interaction with the snapshot
   session-boundary heuristic).
5. `write_project_version(root, CURRENT_VERSION)` — **once, at the end**, only after the full pending
   ladder succeeds. On failure the stamp is unmoved and the backup is the recovery; idempotency (§2)
   makes re-opening re-run cleanly over any partially-rewritten tree.

Read via `_read_markdown_with_front_matter` and write via the **generic**
`_write_markdown_with_front_matter(path, front_matter, body)` (`project_service.py:497`) — *not* the
kind writers `_write_scene_file`/`_write_lore_entry_file` (`project_service.py:589/604`): they take
domain models (`Scene` needs a `revision` a parsed document has no value for) and emit a fixed key set
(they would silently drop unknown front-matter keys). The generic writer takes exactly `(front_matter,
body)` and preserves every key; a migrated file's serialized form may differ cosmetically from an
app-written one (a blank line, key order) and re-canonicalises on the document's next ordinary save.

### 5 — Ownership and version source

- **Owned = the open project's own layer.** The node walk (`references.py:310`) and the override
  collection are both layer-aware (they include ancestor / Library / machine layers); the pass rewrites
  only files whose `source_layer_id ==` the open project's own layer (the `lore.py:60` pattern), and only
  the open layer's `overrides/*.md`. Reasons this is the boundary, not a limitation: the backup zips only
  the open root (`migrations.py:124`), and under ADR-0039 each project is opened independently with its
  own `schema_version`, so an ancestor migrates when **its** project is opened — exactly how root-scoped
  migrations behave today.
- **Version:** in-tree content rides the project stamp (`read_project_version`, captured once); the whole
  owned tree migrates together, so **no per-document version field is added to live files**. Out-of-tree
  bodies carry their own — snapshots already freeze `schema_version` in the sidecar.

### 6 — Project-shaped non-node files (structure, schema) are root-scoped

`manuscript.structure.yaml` / `research.structure.yaml` are not nodes (not in `by_id`) — project-shaped
ordering files, one per project. A change to their format is a **`RootMigration`**. They carry a
denormalized per-node **`title`** and the leaf reference (`scene_id`/`note_id`), so a migration that
renames a node title or changes the id / leaf-ref scheme is a `RootMigration` that must touch them;
`status`/`color`/`metadata` are *not* persisted there (stripped on write, re-projected on read —
`tree_structure.py:103`), so those are safe.

The **entry-type schema** (`metadata.schema.yaml`, one per layer, merged down the ancestor chain) is the
same category — a project-shaped non-node file, **not** an index node — so a change to the *schema
format* (how entry types / field definitions are written) is a `RootMigration`, and each layer's schema
migrates when **that layer's project** is opened, the same ownership boundary as everything else. (This
is distinct from a content migration that transforms a *value* whose type the schema defines — that
stays a `DocumentMigration` authored against the known type, per §2, and never reads the schema.)

A change that touches both content and a project-shaped file — a node-id scheme in every node's
front-matter `id` **and** in the structure files, say — is one `DocumentMigration` plus one
`RootMigration` at the same version, per §2.

### 7 — Restore routes through the runner, byte-exactly when it can (ADR-0056, ADR-0043)

`restore_snapshot` (`scene_snapshots.py:400`):

- **Sidecar `schema_version == CURRENT_VERSION` (the common case):** unchanged — the raw byte copy it is
  today, so ADR-0043's *prose restored byte-exact* holds verbatim.
- **Sidecar version behind:** parse the stored `.md` to `(front_matter, body)`, run
  `migrate_document(MigratableDocument(front_matter, body), sidecar.schema_version)`, write via the
  generic writer. This is a *transformation* — byte-exactness to the old snapshot is impossible by
  definition; the byte-exact guarantee applies to the same-version branch only. Today the document
  subladder is empty, so **every** snapshot takes the byte-exact branch; the mechanism is wired to the
  choke point (ADR-0056) and dormant, so the first post-gateway content migration applies at restore
  with no new call-site to remember.

## Why / rejected alternatives

- **Document pass = index nodes only.** The tempting scope, and wrong: override deltas carry field
  keys/values yet are deliberately not nodes (`overrides.py:19-23`), so a node-only walk silently leaves
  stale content in `overrides/*.md`. The pass must reach every content-bearing file, index node or not.
  Rejected.
- **A raw-text `str -> str` document fn.** Every step would re-parse YAML + split the body itself,
  risking drift and duplicating the runner's parse. The parsed `(front_matter, body)` unit + one seam is
  DRY and format-stable. Rejected.
- **A per-document `schema_version` in every live document's front matter.** The name is even reserved
  as a non-author key (`snapshot_diff.py:658`), yet still wrong: redundant with the project stamp (the
  owned tree migrates together), a field on every file to keep in sync (a fresh drift source), and the
  only bodies that genuinely need their own version already carry one (the snapshot sidecar). Rejected.
- **Write back through the kind writers to keep byte-identical format.** They take domain models and emit
  a fixed key set — no value for `Scene.revision`, and unknown keys dropped (the two failure modes §4
  avoids). The generic writer is the correct seam; cosmetic format re-canonicalises on next save. Rejected.
- **Fold overrides into `metadata` before migrating, then re-diff.** Materialising an override into base,
  migrating, and re-diffing to a delta would reuse the content fn — but it changes what the override
  *is* (its `target`/row identity, its descendant-wins semantics) and risks rewriting deltas the
  migration never needed to touch. Migrating the override file in place, as its own content-bearing
  document, is narrower and truer to the store. Rejected.
- **One unified shape — everything document-scoped.** Folder creation, cross-file moves, and structure
  files are genuinely project-shaped; a per-document signature cannot express them. Rejected.
- **Delta / three-way-merge cleverness in the runner.** A pure content transform per document is enough
  for every named case; deltas add machinery with no consumer. Rejected.

## Consequences

- ADR-0043's *migrate at restore* becomes constructible, wired to the restore choke point.
- Any later feature holding document content outside the live tree (document import, a future trash
  metaphor) inherits the same `migrate_document(doc, from_version)` entry point.
- **The override blind spot is closed by design** — the review's key finding. A content migration reaches
  entry metadata, `mutation_set` rows, scene-body markers, *and* override rows, because the pass
  enumerates content-bearing files, not just index nodes.
- **A body-marker migration has a frontend twin.** The mutation-marker grammar is mirrored in
  `frontend/src/lib/utils/markdown.ts` with no shared cross-language source (`markers.py:19`); a
  grammar-changing migration must keep both in lockstep — named here, not solved.
- **The registry type change ripples**, by design: `pending_migrations` (`migrations.py:120`) and the
  runner loop stop indexing `m[0]` / unpacking a 3-tuple, and the two tests that append a bare tuple to
  `MIGRATIONS` (`test_migrations.py`) construct a `RootMigration`/`DocumentMigration` instead —
  `isinstance` dispatch mis-handles a stray tuple rather than failing loudly, so they must be updated.
- **Pre-gateway policy is unchanged.** No content migration is written now. The deliverable is the shape,
  available and used: a **fixture** `DocumentMigration` (monkeypatched in with `CURRENT_VERSION` raised,
  the existing test idiom) proves `migrate_document` applies to a single body with no root, and that
  migrating a project equals migrating each document individually for content steps — the fixture step
  exercising **≥2 encodings** (e.g. a metadata field *and* its override row) so the kind-awareness of §3
  is proven, not assumed. The distinction is visible in the registry types; the module docstring records
  which shape to reach for and why.
- **Inherited items migrate with their owner.** An **inherited lore entry** (and the **entry types** it
  is typed by, §6) is owned by the ancestor, so it migrates when the *ancestor* project is opened — the
  descendant never rewrites it (it is outside the descendant's backup; ADR-0039 opens each project
  independently). The descendant's **own override** of an inherited entry lives in the descendant's
  `overrides/` and migrates *with the descendant* (§3). So both halves are covered, each by its owning
  project — parent base with the parent, child override with the child.
- **Named and scoped out — cross-layer content skew.** The corollary of the above: opening a descendant
  before its ancestor has been migrated means the descendant reads old-format ancestor content (and its
  own already-migrated override folds over it) until the ancestor is opened. This is a **pre-existing
  property of open-project-scoped migration** — a root-scoped migration on the descendant does not touch
  ancestor files today either — not introduced here. Addressing it (migrate-ancestors-on-descendant-open,
  or a machine-root sweep) is a separate decision for whoever writes the first cross-layer content
  migration.

  > **⚠ Superseded by Amendment 1 below.** ADR-0082 §6 decided this: opening a project now migrates
  > its whole declared chain, not just its own layer — closing the cross-layer skew named here rather
  > than leaving it to a future migration author.

## Acceptance (from #366)

- A content migration applies to a single document body with no project root — `migrate_document`, with
  a test that does exactly that.
- Migrating a project and migrating each of its documents individually produce the same result for
  content-shaped steps — a test over a fixture `DocumentMigration` spanning ≥2 encodings.
- The root-vs-document distinction is visible in the registry — the `RootMigration`/`DocumentMigration`
  types.
- `docs/` or the module docstring records which shape to reach for and why.

## Slices

1. **The pure framework** (`migrations.py`): `MigratableDocument`, `DocumentMigrationFn`, the typed
   registry (`RootMigration`/`DocumentMigration`), `migrate_document`, the runner-internals + docstring;
   the two bare-tuple tests updated. Delivers acceptance #1, #3, #4. Touches neither the open path nor
   restore — the foundation.
2. **The project document pass** (`ProjectService` mixin + open-path wiring): enumerate owned index
   nodes **+** owned `overrides/*.md`, migrate each, write-if-changed, construct-then-migrate + end-stamp.
   Delivers acceptance #2 (equivalence over a fixture step spanning ≥2 encodings).
3. **Restore wiring** (`restore_snapshot`, §7): byte-exact at CURRENT, `migrate_document` when behind.

Sequential (2 and 3 each depend only on 1). Binding = the Decision + the invariant (§2); the slice
boundaries may shift if implementation argues for it, amending this ADR before code.

## Amendment 1 — opening a project migrates its whole declared chain, outermost first (2026-09-03, ADR-0082 §6, PR #1807)

§5's ownership rule ("an ancestor migrates when **its** project is opened") and the Consequences
section's "named and scoped out" cross-layer skew are reversed: **opening a project now runs the full
ladder — root steps, chain steps, the document pass — on every layer of its declared chain, outermost
first, each layer backed up and stamped through its own `ProjectService(WorkScope(root=layer))`, before
the open layer runs its own.** A new `ChainMigration` step type (alongside `RootMigration`/
`DocumentMigration`) carries a context accumulated across that walk, so a descendant layer's step can
see what an ancestor layer's step already did. A machine-level once-step, keyed on
`MachineSettings.version` rather than any project's `schema_version`, runs in the app lifespan for
out-of-tree machine content — and again from the runner's top-level call, so a project opened without
the app ever starting (a script, a test) still finds the machine vocabulary; both triggers are
idempotent.

The reason is ADR-0082 §6's tags migration: removing `tags` from the schema `type` Literal makes an
**unmigrated ancestor's `metadata.schema.yaml` fail validation the moment a migrated descendant merges
it** — the skew this ADR shrugged off as pre-existing is no longer harmless once a migration changes
what a *valid* ancestor file looks like, not just what a *current* one looks like. A version-dispatching
reader (branch behavior on an ancestor's stamped `schema_version` instead of migrating it) was rejected
for the same reason every other content-shaped reader in this ADR stays version-blind: it is the
`RootMigration`/`ChainMigration`/`DocumentMigration` framework's whole point that a live reader never has
to know a format's history.
