# ADR-0040: The node index is a persisted, incrementally-maintained id-map; bodies are lazy; no SQLite

- Status: **Proposed** — 0.7.0 planning, 2026-07-16 · **red-penned and re-measured 2026-07-19**
  after adversarial review (awaiting approval)
- Feature: #7 (prerequisite) · Companion: ADR-0039 · Follows: ADR-0025
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
