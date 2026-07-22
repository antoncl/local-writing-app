# ADR-0040: The node index is a persisted, incrementally-maintained id-map; bodies are lazy; no SQLite

- Status: **Accepted** — 0.7.0, 2026-07-19 (PR #319) · re-measured 2026-07-19 after two rounds of
  adversarial review · **Amendment 1: the index is three caches with different lifetimes, not one**
  (Accepted — Anton, 2026-07-22, #390)
- Feature: #7 (prerequisite) · Companion: ADR-0039 · Follows: ADR-0025 · Context: **ADR-0045**
- Amended by: #390 — see [Amendment 1](#amendment-1--the-index-is-three-caches-not-one-2026-07-22)
- Implemented by: #305 (single-pass) → #306 (snapshot + staleness manifest) → #307 (incremental patch
  + change-gate). #307 is the **backend** half of the reference-index work that #200 never landed —
  it closed 2026-07-19 having shipped the *frontend* change-gate only (PR #301).
- Evidence: `scripts/benchmark/cache/hierarchy_bench.py` — drives the **real `ProjectService`**
  (Weber + huge fixtures, re-measured 2026-07-19)

## Context

The backend maintains a node index over the open project *and its ancestor layers*: `id → node` plus
the reference edges between nodes. Under ADR-0039 this index stops being merely a lookup table and
becomes the **materialization mechanism** — it is what pulls ancestor-owned nodes (lore, research
notes, prompts, assistants, mutation sets, views) into the open book as members. That makes its cost and its
correctness a prerequisite for hierarchies rather than an optimization of them.

Today the index is rebuilt from scratch on demand, and the chain is parsed **three times** to answer
one reference-graph request: `_build_node_index` parses every file (`references.py:182`);
`reference_graph` then calls `_build_node_index` *again* (`references.py:410`) and re-reads each
node's front matter per entry in `_forward_refs_for_entry` (`:377`). `list_backlinks` (`:343`) and
every `list_*` slice add further passes. Nothing is memoized. Deepening the ancestor chain
multiplies all of it.

## Decision

**Identity is layer-qualified.** The index maps `id → [candidates, innermost layer first]`, not
`id → entry`. The innermost candidate is the winner; the shadowed ancestors are **retained**. This
is required by three separate things: ADR-0039's per-field overrides (which need the ancestor base
*and* the descendant overlay simultaneously), un-shadowing on delete (below), and the project node,
whose id is the constant `"project"` (`project_node.py:34`) and therefore collides at every level of
any chain. `project` becomes an indexed kind; it is not indexed today (`references.py:52-68`).

**Each entry carries an ordered layer rank**, not just a label. `NodeIndexEntry.source_layer_id` is
today a sha256 of the path (`schema.py:912-913`) — an opaque identity with no ancestry in it. ADR-0039
resolves overrides in layer order and renders provenance, so the rank is part of the index contract.

> **Amended by [Amendment 1](#amendment-1--the-index-is-three-caches-not-one-2026-07-22):** the
> identity map and the edges are still both correct and still built in one pass, but they are two
> caches with different lifetimes rather than one artifact — and the edges need a second layer, the
> values they were extracted from.

**The index holds** `id → (path, kind, entry_type, title, layer rank)` plus reference edges
`(src, dst, field)`. Note both are partly new work, not the status quo: today's store is
`refs: dict[str, list[str]]` with the field id computed and then **discarded** when targets are
flattened across fields (`references.py:381-398`), and there is **no cache at all** — `reference_graph()`
rebuilds on every call (`references.py:401`). The `field` qualifier is required by ADR-0039's
reference-typed overrides, which must know *which* field an override re-points.

**Backlinks are served by a reverse adjacency map**, built alongside the forward edges — not by
scanning an edge list. Measured per backlink query (Weber / huge): reverse map **179 ns / 194 ns**,
flat edge-list scan **229 µs / 518 µs**, SQLite **29.6 µs / 35.1 µs**. The map costs 0.7 ms / 6.5 ms
to build. Backlinks, `References` and Nest are the queries that motivate the index, so the structure
it exposes must be the one they use — and note the flat edge list, which earlier drafts of this ADR
proposed, is the one option that loses to SQLite.

**Storage:** plain in-memory dicts, persisted as a rebuildable JSON snapshot under `.cache/`, written
through the existing `_atomic_write` (`project_service.py:250` — same-directory temp file then
`replace`). The snapshot carries a **format version key**; a mismatch triggers a rebuild. Pre-1.0
that is the whole migration story: bump the key, rebuild once, never write migration code
(consistent with the no-pre-1.0-migrations rule).

**The snapshot is per-open-project, not global.** The index is root-parameterized — scenes are taken
only from the open project (`references.py:70-72`), layer labels and shadow resolution are ordered by
the chain to that root — so a snapshot is valid for one open-project root.

*Per-project means the ancestor layers are re-parsed once per book, and that is deliberate.* At Weber
scale ~93% of a chain's nodes are ancestor-owned, so a per-layer snapshot would share more. But a book
is opened many times and switched between rarely — you write in one book for months, and a finished
book is seldom reopened. The duplication is a one-time cost when a book is started; every subsequent
open is the warm path. Do not "fix" this into per-layer snapshots without new evidence about how books
are actually opened.

**The machine assistant layer is indexed but is not in any chain.**
`_collect_machine_layer_assistants` (`references.py:45`, `:149-166`) reads
`machine_settings.assistants_dir().parent` — outside every project tree and shared across all
projects. So a chain walk will never stat it, and a per-project snapshot can serve a stale roster
after it changes. Its files must be in the manifest despite not being in the chain, and the
assistant index built with no project open (`assistants.py:228-238`) is **not** persisted.

**Bodies are never held by the index.** They are loaded on demand by `id → path` (on open, render, or
AI-context assembly).

### Staleness detection

"Rebuild when the snapshot is missing or stale" is only safe if *stale* has a mechanism. It does:

The snapshot carries a **manifest** — `path → (mtime_ns, size)` for every file it indexed, including
each layer's `metadata.schema.yaml` and `project.yaml`. On open, walk the layer chain and set-diff
the manifest against disk (measured full sweep: **19.7 ms** Weber / **41.4 ms** huge).

Compare **tuple equality, not recency**. "Anything newer than the snapshot" misses files restored
from backup, extracted from an archive, or copied with preserved timestamps — all of which can land
an *older* mtime on disk. Equality also catches deletions, as manifest keys with no file.

**Additions are not free, and the manifest alone cannot see them.** A new file has no manifest key,
so nothing looks for it — drop a `.md` into an ancestor's `lore/` from Explorer, or `git pull` a
layer, and it stays invisible. Detecting additions requires re-globbing the indexed folders, using
the index's own glob semantics (`_collect_layer_entries` globs `*.md` **non-recursively**,
`references.py:180`; a recursive walk would report permanent phantom additions). The measured sweep
below is therefore the stat-known-files half; the directory walk is additional.

The diff is not a yes/no verdict, it is the **work list**, and it routes:

| Diff | Action |
|---|---|
| empty | use the snapshot as-is |
| changed / added paths | re-parse only those, patch the snapshot (~20 ms for 10 files, both scales) |
| deleted paths | drop the entry, re-resolve shadows for the affected ids |
| snapshot missing, corrupt, or version-mismatched | full rebuild |

So *stale* almost always means "patch six files", never "rebuild everything". Two cases need naming
because they are not one-file-in-one-file-out:

- **Deletes must un-shadow.** Removing a book-level entry that shadowed a series-level one must make
  the ancestor visible again — and there is no changed file to re-parse. This is why the index keeps
  all candidates per id rather than the winner alone. A rename is a delete plus an add and needs no
  separate rule, since identity is the front-matter `id`, not the filename.
- **Schema files fan out.** Edge extraction is schema-driven — `_forward_refs_for_entry`
  (`references.py:373-399`) resolves `entry_type → field → type == "entity_ref"`. A
  `metadata.schema.yaml` edit therefore invalidates edges for *every node of the affected entry types
  across the chain*, not one file. `project.yaml` likewise fans out to the settings/AI-policy chain.
  > **Amended by [Amendment 1](#amendment-1--the-index-is-three-caches-not-one-2026-07-22):** the
  > fan-out is over *edges*, not over the index. It never reached identity, and it is a lookup by
  > `field_id` rather than a re-read once the extraction inputs are cached.

**Concurrent writers are a non-goal.** This is a single-user, offline-capable tool. Two backends over
one project folder would race on the snapshot — and that is fine: the snapshot is advisory and
derived, so last-writer-wins costs at most one wasted rebuild and never data. Anyone running this as
a hosted multi-user service owns that problem; we do not build locking for it.

**No SQLite** for the index. **No IndexedDB** on the frontend — the relation table is derived from a
backend feed, not independently persisted.

## Why / rejected alternatives (measured, not assumed)

Two synthetic shelves — **Weber** (4 universes × 15 books, 11.7k files) and **huge** (6 × 20, 31.4k
files) — each opened at `universe_00/series_00/book_00`, a 4-layer chain. The benchmark drives the
real `ProjectService`, so these are the app's own call paths, not a replica's.

**Every figure is scoped to the ancestor chain, because that is what the code builds.**
`_build_node_index` (`references.py:40`) walks `_project_layer_folders(root)` — base→root only — and
never touches sibling books or universes. Opening one book indexes **~1610 nodes** (Weber) / **~3130** (huge) — the chain's 1600 / 3120 plus
this machine's assistant roster, so the tail digits vary per developer — not the 11.7k /
31.4k files on the shelf. Mixing the two scopes is how earlier drafts produced both a 285–460×
speedup and an implausible 3.5 s cold open; chain-vs-chain is the only comparison that means
anything.

| | Weber | huge |
|---|---|---|
| `_build_node_index` | 2.0 s | 4.1 s |
| `reference_graph` (rebuilds the index, then re-parses per entry) | 3.6 s | 7.2 s |
| **cold open, total** | **5.6 s** | **11.3 s** |
| snapshot → usable index (load + rehydrate) | 14.7 ms | 22.5 ms |
| staleness sweep | 19.7 ms | 41.4 ms |
| **warm open, total** | **34 ms** | **64 ms** |
| | **≈165×** | **≈177×** |

- **The cost is parsing, and the snapshot removes it.** Cold open is *worse* than earlier drafts
  claimed — 5.6 s / 11.3 s — because the real extractor is schema-driven and the chain is parsed three
  times. Warm open is far *better*: 34 ms / 64 ms, staleness sweep included.
- **Memory is never the constraint.** The chain index is **2.2 MB** (Weber) / **4.4 MB** (huge);
  holding *every body in the chain* as well reaches only **7.1 MB** / **14.8 MB**. (Object-graph
  estimate, not resident set — an optimistic floor, but the headroom is three orders of magnitude.)
  Ancestor-only visibility means the whole shelf is never resident. Nothing that trades memory for
  indexed query — SQLite's whole premise — can earn its cost here.
- **SQLite rejected** — it does not cut the parse, which is the actual cost, and a 2–4 MB index fits
  in memory trivially. It is *not* rejected on invalidation grounds: both a SQLite file and a JSON
  snapshot under `.cache/` are derived, disposable, rebuildable-by-design artifacts with identical
  invalidation obligations, so that argument would disqualify this ADR's own design just as readily.
  To be precise about the predecessor: ADR-0025 *did* give invalidation as its reason (2) — "a derived
  write-through cache needing correct invalidation on every mutation path … a **new failure category**,
  whereas `.cache/` is rebuildable *by design*". But that reasoning discriminates rebuildable-by-design
  from authoritative, not JSON from SQLite: a SQLite file under `.cache/` is equally disposable. 0025
  also explicitly contemplated a backend index — "port that one function to Python over the existing
  node index, still no database". With both stores equally rebuildable, we keep the cheaper one.
- **A flat edge list rejected** in favour of a reverse adjacency map. This is the one place the
  measurement contradicted the original proposal outright: an edge-list scan (229 µs / 518 µs) is
  **slower than SQLite** (29.6 µs / 35.1 µs), while the reverse map (179 ns / 194 ns) beats it by
  ~165×. The anti-SQLite case depends on exposing the right structure.
- **IndexedDB (frontend) rejected.** The payload is low single-digit MB; ADR-0025 measured store-side
  view evaluation at µs–ms. Browser persistence adds a cache-coherence surface for no win.
- **Schema merge is not a hidden cost.** `read_metadata_schema()` is uncached, but it scales with
  *layer depth*, not shelf size: **6.0 ms / 7.4 ms** for a 4-layer chain. Deepening hierarchies makes
  this grow linearly and slowly; it is not the thing to optimize.

## Consequences

- **Prerequisite for #7 (ADR-0039)** — and on materialization grounds, not only latency: the index is
  what makes ancestor nodes members of the open book.
- **Snapshot write-back is cheap, but still debounced.** Serializing the chain snapshot costs
  **16 ms** (Weber) / **31 ms** (huge) — not the blocker an earlier shelf-scoped measurement
  suggested. The in-memory index is still patched eagerly and the snapshot flushed on a
  debounce/dirty-flag (and on clean shutdown), because a prose-only autosave should do *zero* index
  work, not 16 ms of it. A crash between patch and flush is safe: the manifest diff catches it on the
  next open.
- **`.cache/` stays rebuildable** (files-are-truth): the snapshot is derived and disposable; missing
  or corrupt triggers a rebuild, never data loss. The directory already exists and is already governed
  — `lifecycle.py:52` creates it with every project, and `migrations.py:36` excludes it from backups
  (`SKIP_FROM_BACKUP`), which is already correct for the snapshot. Only its *contents* are new.
- **Off-app file monitoring stays a separate slice, and is now optional.** With sweep-on-open,
  external edits are caught at the next open by construction. A watcher would only let us skip the
  sweep and react live — an optimization, not a correctness requirement. This is what makes deferring
  it safe. **The accepted exposure:** a session that stays open for hours never re-sweeps, so an
  external edit made mid-session stays invisible until the next open. That is a deliberate trade, not
  an oversight — a mid-session refresh hook is the cheap mitigation if it ever bites.
- **Single-pass build is free money, and worth ~2.8×, not "half".** Answering one reference-graph
  request costs 5.6 s, of which 2.0 s is the first index build and 3.6 s is `reference_graph`
  rebuilding the index a second time and then re-reading every node's front matter. Extracting edges
  during the one build that already parses each file collapses that to roughly a single pass. This is
  independent of persistence and can land first.
- **Layer overrides are materialized into the index; scene mutations are not.** A layer override is
  position-independent and the open project has exactly one layer scope, so an override on an
  `entity_ref*` field is folded into the member set and its edges *before* adjacency is built — no
  scope parameter threaded through consumers, no query-time delta. Scene mutations stay
  position-dependent and therefore stay resolved at query time, as today. The reasoning is ADR-0039's
  (virtual membership); stated once, there.

## Note on the evidence

The first revision of this ADR was argued from a benchmark that **reimplemented** the parse path
rather than calling it. Its fixtures carried no `metadata.schema.yaml` and used undeclared `ref_*`
field names, so it measured edge extraction the real schema-driven code would never perform — under
the real extractor those fixtures yield *zero* edges. It also compared a chain-scoped build against a
shelf-scoped snapshot, inflating the headline ratio, and never measured schema merge, snapshot
write-back, rehydration, or staleness at all.

One caveat survives, stated rather than buried: the benchmark serializes **one winner per id with a
layer label and unqualified edges**, while this ADR specifies **candidate lists, layer ranks and
field-qualified edges**. The snapshot size, write and load figures are therefore floors for a
strictly smaller structure. The fixtures also generate globally unique ids, so they contain **zero
shadows** — un-shadowing cost is not merely unmeasured, it is unmeasurable on them, and the candidate
list is pinned at length 1 where the real one is O(chain depth). Closing that gap belongs to #306.

The benchmark now drives `ProjectService` directly, so faithfulness is a property rather than a
claim, and it is tracked at `scripts/benchmark/cache/` (fixtures generate into gitignored `tmp/`).
Every number above is reproducible from a clean clone: `hierarchy_bench.py` generates its fixtures on
first run (`--regen` to rebuild them), and a bare invocation runs all three scales.

## Amendment 1 — the index is three caches, not one (2026-07-22)

Status: **Accepted** — Anton, 2026-07-22 (#390).

**Code read against `master` at `052895c` (2026-07-22)**, after #305/#306/#307's merged half. Every
name cited below lives in `backend/app/services/project/` — `node_index.py` (`NodeIndex`,
`NodeIndexEntry`, `ReferenceEdge`), `references.py` (`_reference_edges_for_entry`,
`_edges_from_field`), `node_index_patch.py`, `node_index_snapshot.py` (`build_identity`). They are
cited as evidence that the fusion is real and that `field_id` already exists, not as a contract:
**if a name has moved, the model below is what binds, and the citation is the thing to update.**
v1's own citations have already drifted this way — its `_forward_refs_for_entry` (`references.py:373-399`)
is today's `_reference_edges_for_entry`, and its line numbers predate three PRs.

Established with Anton during the ADR-0045 design pass, and a correction to this ADR's own model
rather than a new subject: splitting the node index across two documents would leave a reader to
reconcile them.

### What v1 got wrong

The original design was **two caches**, and both are here and correct:

1. **`id → path`.** The app references nodes by id; nodes are files; with folder inheritance,
   resolving an id means knowing *which layer's* file it is, and rescanning the chain per lookup is
   a non-starter. This is `candidates`.
2. **the reference graph** — which nodes a node points at, traversable both directions. This is
   `edges_by_layer_src` / `edges_by_src` / `edges_by_dst`.

**The error is that they were fused into one artifact with one lifetime.** #305 folded edge
extraction into the identity walk so each file is parsed once instead of once per pass — a real win, still
right, and nothing here undoes it. But a shared *read* was allowed to dictate a shared
*invalidation*, and the two have opposite relationships to the schema:

- **identity is schema-independent.** It changes when a file is added, removed, renamed, or changes
  its front-matter `id` — and at no other time. No schema edit can move it.
- **references are schema-dependent.** Knowing which fields are references requires resolved field
  definitions, which are layered and which resolve differently per authoring layer (ADR-0042 §3).

Fused, the schema dependency contaminates identity: a `metadata.schema.yaml` edit forces a **full**
rebuild *including the id→path map, which could not have changed*. #307 declines to patch on schema
edits for exactly this reason, and wrote the fan-out up as though it were inherent
(`node_index_patch.py`, "Two things fan out and are therefore not patchable"). It is not inherent —
it is an artifact of the fusion.

### The third cache, never designed as one

**Resolved field definitions, per layer.** Today the schema is re-merged from YAML on every index
build (measured above at 6.0 ms / 7.4 ms for a 4-layer chain — small, but paid unconditionally), and
ADR-0042's picker surfaces want a second, as-of-L variant of the same thing. It is a derived,
layered, expensive artifact consumed by everything: a cache whether or not it is treated as one. Not
modelling it is what allowed an index to be built against one project's files and another project's
schema (found in #381).

**It is an *input* to the index, not part of it.** This amendment names it as required and stops
there; its design belongs to a separate issue, or ADR-0040 acquires a second subject that ADR-0042's
surfaces would then have to share.

### References must be two-layered

**An edge is a function of a value AND a definition** — literally so:
`_reference_edges_for_entry` walks the entry type's declared fields, looks each field's `type` up in
the schema, and pairs it with the node's stored value. We cache only the *output*. So when the
definition changes, the other input has to be reconstructed from source.

Adding an `entity_ref` field mints edges from values that were already on disk — **no file changed**.
That means the references cache cannot be rebuilt from "which files changed", and cannot be rebuilt
at all without the values, which the identity cache does not hold. This is not an edge case: it is
the faction example that carries ADR-0045.

So the references cache stores the extraction **input** alongside its result: per node, per layer,
the metadata values that could ever become a reference. **Bounded** — only strings and lists of
strings can (`_edges_from_field` discards everything else), so a field retyped from `number` loses
nothing by never having been kept. Note the values worth keeping are *not* only those of currently
declared reference fields: the case that needs them is precisely a field that had no such definition
a moment ago.

### `field_id` is the join key, and it is already there

`ReferenceEdge` carries `(src, dst, field_id)` — Anton's design, which this ADR justified by
ADR-0039's reference-typed overrides. That undersells it. **The field id is what makes a definitions
change a lookup instead of a rebuild:**

- a field retyped away from `entity_ref*`, or deleted → drop the edges carrying that field id;
- a picker constraint narrowed → re-check only those edges;
- a field **added** as `entity_ref*` → no existing edge carries that id, and this is the one case
  that needs the cached values.

Key the values by the same `(node, layer, field_id)` and the third case collapses into the shape of
the other two. The join key exists on one side of the join today; the amendment is that it must
exist on both.

### Consequences

- **A schema edit stops being the most expensive invalidation we have.** It leaves identity
  untouched and reduces to a field-id lookup over the edges, plus a values scan only for
  newly-reference-typed fields.
- **#307's patch gains a second unit of work.** Its work list is "changed paths"; it now also needs
  "changed *definitions*", which touch nodes whose files never moved. The manifest cannot express
  that unit, and this is the amendment's main obligation on the implementation.
- **The three lifetimes differ, so invalidation must be stated per cache**, not per snapshot: files
  moving invalidates identity (and, through it, values); definitions changing invalidates edges
  alone; a code change to what a build *produces* still invalidates everything, as `build_identity()`
  already arranges.
- **Nothing here changes the storage decision.** JSON under `.cache/`, rebuildable by design, no
  SQLite. Deliberately **no cache formats are specified**: the moment this section describes storage
  it stops being an amendment to a model and becomes a design for one.
- **#314 (slice E) must be planned against this model**, not the fused one — which is why this was
  written before it.
