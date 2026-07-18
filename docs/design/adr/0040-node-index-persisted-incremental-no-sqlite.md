# ADR-0040: The node index is a persisted, incrementally-maintained id-map; bodies are lazy; no SQLite

- Status: **Proposed** — 0.7.0 planning, 2026-07-16 (under review, not accepted)
- Feature: #7 (prerequisite) · Advances: #200 (storage + incremental half; change-gate still required) · Companion: ADR-0039 · Follows: ADR-0025
- Evidence: `tmp/bench/hierarchy_bench.py` (Weber + huge fixtures, measured 2026-07-16)

## Decision

The backend node index — `id → (path, kind, entry_type, title, owning-level)` plus the reference
**edge list** `(src, dst, field)` — is:

- built by a **single** front-matter parse pass per file (today it is parsed **twice**:
  `_build_node_index` then `_forward_refs_for_entry`/`reference_graph`);
- held in memory as **plain dicts** (not a database);
- **persisted as a rebuildable JSON snapshot under `.cache/`**;
- **maintained incrementally and change-gated** — on a file mutation, re-parse only the changed
  file(s) and patch the snapshot; and gate *how much* to do on *what* changed: an `entry_type`/`id`/
  `title` change touches the node index, an `entity_ref*` change touches the edge list, a body-only or
  other-field edit touches neither. A full rebuild happens only when the snapshot is missing or stale.

**Bodies are never held by the index.** They are loaded on demand by `id → path` (on open, render,
or AI-context assembly). **No SQLite / embedded DB** for the index. The **frontend relation table is
derived from a backend feed**, not independently persisted (no IndexedDB).

## Why / rejected alternative (measured, not assumed)

Benchmarked over synthetic Weber-scale (4 universes × 15 books = **11.7k node files**) and huge
(6 × 20 = **31.4k files**) fixtures, faithful to the real parse path (`yaml.safe_load` of
front-matter only, the current double parse):

- **Memory is never the constraint.** Resident footprint: index **18 MB** (Weber) / **52 MB** (huge);
  the *entire shelf including every body* is **91 MB** / **260 MB**. Nothing that trades memory for
  indexed query (SQLite's whole premise) can earn its cost here.
- **The cost is parsing.** Cold rebuild: **21 s** / **60 s**. Open one book's chain: **3.5 s** /
  **7.0 s** — pure-Python YAML, doubled by the two-pass build. Snapshot load: **74 ms** / **129 ms**
  (285–460× faster). Incremental re-parse of 10 changed files: **~18–20 ms** (1000×+ faster).
- **SQLite rejected.** It does not cut the parse (the actual cost). Per-query latency **66–86 µs** vs
  **~100 ns** for an in-memory dict (~600×). The 18–52 MB index fits in memory trivially. And it
  reintroduces the write-through-invalidation failure category ADR-0025 already rejected (external
  edits, restart-mid-save). A JSON snapshot gives identical persistence, stays *rebuildable by
  design*, and keeps dict-speed lookups.
- **IndexedDB (frontend) rejected.** The payload is single-digit-to-low-tens of MB; ADR-0025 measured
  store-side view evaluation at µs–ms. Browser persistence adds a cache-coherence surface for no win —
  the frontend table is derived from the backend feed.

## Consequences

- **This advances #200 but does not close it.** #200 (the reference index full-rebuilds the whole
  project on every autosave) needs *both* incremental patch *and* a change-gate. This ADR settles the
  **storage** decision (persisted JSON snapshot, no SQLite) and adopts **incremental patch**; the
  **change-gate** — deciding whether/how much to maintain per the changed-field class above, so a
  prose-only save does zero index work — remains required #200 work, complementary to this ADR.
- **Prerequisite for #7 (ADR-0039).** It keeps open-a-book responsive as ancestor chains deepen; the
  multi-second cold parse is otherwise inherited and multiplied by nesting.
- **`.cache/` stays authoritative-rebuildable** (files-are-truth): the snapshot is derived and
  disposable; a missing/corrupt snapshot triggers a full rebuild, never data loss.
- **Off-app file monitoring is a *separate* slice.** It is the invalidation trigger that lets the
  incremental path react to external edits, but the hierarchy feature is usable with rebuild-on-open
  before live file-watching lands — and watching is the exact surface ADR-0025 warns is error-prone,
  so it earns its own design pass.
- The single-pass build alone (dropping the double parse) roughly halves every cold number for free,
  independent of persistence.
- **Reference overrides/mutations layer on the cache, they do not invalidate it.** The snapshot
  indexes *base* (stored) edges, which stay stable and cacheable — the universe layer is the most
  stable block. A per-field override or scene mutation on an `entity_ref*` field yields *effective*
  edges = base + a sparse resolved delta for the active scope (parallel to `effective_state`),
  computed at query time by the consumers that need effective adjacency (backlinks / `References` /
  Nest), never baked into the global snapshot. *Which* scope a consumer resolves "effective" for is
  the open sub-problem, tracked in ADR-0039 (slice E). This keeps the expensive global index scope-
  independent and the per-scope delta cheap.
