# Design: The resolved-definitions cache

> Status: **DRAFT for review** · Issue: [#394](https://github.com/antoncl/local-writing-app/issues/394) ·
> Milestone: 0.7.0
> Decision of record: **ADR-0040 Amendment 1** names this cache as *required* and deliberately declines
> to design its storage — "the moment it specifies storage it stops being an amendment". This document
> is where that design happens. It does not supersede the amendment; it fills the hole the amendment
> left, and ADR-0040 points here rather than growing a second subject.
> Context: **ADR-0045** (scope is the unit of work), **ADR-0042 §3** (as-of-L definitions), and
> [#393](https://github.com/antoncl/local-writing-app/issues/393) — the as-of-L schema *read*, which is
> this same artefact seen from the consuming side.

## 0. What this is, in one paragraph

Resolved field definitions — the merged answer to "what fields does this node have, of what types,
with what pickers, at this point in the layer chain" — are a **derived, layered, expensive-to-produce
artefact that nearly everything consumes**: the index build (to know which fields are references), the
as-of-L authoring surfaces, and every endpoint that validates saved metadata. Today they are recomputed
from disk on every request with no cache. This document makes them a *thing with its own lifetime*: a
cache keyed by the identity of the schema files it is built from, so that changing one layer's schema
invalidates that layer's definitions and nothing else — and, in particular, never disturbs the node
index's identity map.

## 1. Why definitions must be modelled as a cache — it is correctness, not speed

The merge is cheap — a few milliseconds for a realistic chain — so latency is not the argument.
Amendment 1's argument is:

**An edge is a function of a value *and* a definition, and the index caches only the output.** Whether
a stored metadata value is a reference edge depends on whether its field is typed as a reference — a
fact that lives in the schema, not in the file that holds the value. So adding a reference-typed field
mints edges from values *already on disk, with no file changed at all*. A cache that decides
invalidation from "which files changed" cannot see that change. Making the definitions an explicit,
addressable input is what turns "a definition changed" from an unrepresentable event into a lookup.

The second reason is a correctness failure that already happened: because definitions were not modelled
as an input, an index was once built against one project's files and another project's schema
([#381](https://github.com/antoncl/local-writing-app/issues/381)). A modelled input makes that mismatch
unrepresentable rather than a bug to be found.

The whole point, stated as the test the design must pass: **a schema edit must leave the identity map
untouched.** Identity changes when a file is added, removed, renamed, or changes its front-matter `id`,
and at no other time. No schema edit can move it. If a schema edit still invalidates identity, the three
lifetimes are still fused and this design has failed.

## 2. Cache the parse, not the answer — but at two levels

The merge pipeline does three things: parse each layer's `metadata.schema.yaml` from bytes into data;
overlay the layers nearer-wins; validate and resolve the result into the definition objects consumers
use. **Only the first step touches disk and pays the tokenizer.** The rest is in-memory dict work over
already-parsed data.

The naïve conclusion — "cache only the parse" — is wrong, and it was the first cut of this design. If
the cache stops at the parse, every call still re-folds the layers and constructs a fresh validated
object graph, uses it, and drops it. On a hot path called many times per request that is exactly the
instantiate-use-destroy churn the cache was meant to remove. The proof it bites is already in the tree:
the node-index memo (`ResolvedIndex.schema`, from [#392](https://github.com/antoncl/local-writing-app/issues/392))
holds a merged schema *specifically so a save does not re-merge on every write*.

So the cache has **two levels**, and they interlock:

1. **The parse atom** — one layer's parsed schema. Shared across every chain that includes that layer.
   This is the *invalidation primitive*.
2. **The merged result** — the folded, validated definitions for a given chain (or chain-prefix, for
   as-of-L). This is what removes the churn: an unchanged chain returns *the same object*, with no
   re-fold and no re-validation.

They interlock through their keys (§4): the merged result's key is composed from the identities of the
parse atoms it was folded from, so a changed layer makes the merged entry miss automatically. Level 1
keeps the shared work shared; level 2 keeps the repeated work from repeating.

## 3. The primitive is per-layer; the chain is a fold

The cached unit at level 1 is **a single layer's parsed schema, never a merged chain.** Only a per-layer
primitive has the two properties the feature needs:

- **It shares across descendants.** An ancestor's `metadata.schema.yaml` is the same file for every book
  that inherits it, so it parses once and is reused by all of them. A per-chain primitive would re-parse
  the shared ancestors once per descendant.
- **It makes as-of-L free.** Reading definitions "as authored at layer L" (#393, ADR-0042 §3) is the
  same fold over the same atoms, *truncated* — base→L instead of base→root. It is not a second merge
  path with its own bugs; it is the identical operation with fewer terms. This is only possible because
  the merge is strictly ordered nearer-wins, so a prefix of the fold is exactly the answer at L.

The merged view any consumer wants is therefore a fold over per-layer primitives, produced on demand and
memoised at level 2.

### Why not cache the merged chain as the primitive

Because that is what today's code effectively does (`ResolvedIndex.schema` holds one whole-chain schema),
and it is the wrong granularity for exactly the two reasons above: it cannot share an ancestor across
books, and it cannot answer as-of-L without a separate truncated merge. A per-chain artefact is a
*derived* view, not the primitive.

## 4. Keys — identity, and code-identity only where objects are held

Both levels are **keyed by identity and store their fingerprint beside the payload.** The fingerprint is
the schema file's `(mtime_ns, size)` — the same content-identity the index snapshot manifest already
trusts, compared by equality rather than recency so that a file restored from backup with an older
timestamp is still seen as changed.

- **The parse atom's key is the layer's schema-file path**, and its stored fingerprint is that one file's
  identity. **It carries no code identity.** This is affordable precisely because the atom is *raw parsed
  data*: parsing is stable across our code changes, so the parse output is code-independent. The parts
  that *do* depend on our code — validation, inheritance resolution, the shape of the definition objects
  — are exactly the parts level 1 does not hold.
- **The merged result's key is the chain identity** (which layers, in order), and its stored fingerprint
  is the tuple of the participating layers' file fingerprints **plus the build's code identity**
  (`build_identity()`, already computed for the snapshot). Code identity belongs here and only here,
  because this level holds validated objects whose shape depends on our models. Caching one step earlier
  than this — validated per-layer — would drag code identity down into the shared primitive and lose its
  cross-project reuse. Caching exactly at the raw-parse boundary is what confines code-identity to the
  one level that genuinely needs it.

## 5. Reloading — absence is data, and there is nothing to flush

Reloading is never a decision the cache remembers state about; it is re-derived from a `stat` on every
read. For each layer in the chain, stat its *known* schema path to get the current fingerprint, and
compare to the stored one:

| Read outcome | Action |
|---|---|
| absent from cache | parse (cold miss) |
| present, fingerprint differs | reparse and **overwrite in place** |
| present, fingerprint matches | use the cached payload |

Overwrite-in-place is what makes accumulation impossible: there is one entry per identity, forever, and a
change replaces it rather than adding a second version.

**"File does not exist" is a first-class stored value, not a miss.** Most layers have no
`metadata.schema.yaml` — one is created only when a definition is first saved at that layer — so "no
schema file here" is the common case and is cached as a fingerprint sentinel. This is sound *because the
path is known a priori*: we stat one exact path per layer, so a definition appearing at a
previously-empty layer is detected by that stat flipping absent→present. This is the addition-detection
problem ADR-0040's staleness section calls hard for the index (a new file has no manifest key, so nothing
looks for it) — made easy here because there is nothing to discover, only a known path to check.

### "Doesn't exist" versus "was cleared"

These are two different absences and the design keeps them clean. *File absent on disk* is a stored value
(a sentinel fingerprint). *Entry absent from the cache* is a miss — and a miss is indistinguishable from
never-existed, which is exactly why it is safe: both trigger a stat-and-maybe-parse, and re-deriving from
disk is always correct because the file is the source of truth. That indistinguishability is the property
that would make eviction *safe* if we ever wanted it. Reloading is never wrong, only sometimes wasteful,
and the fingerprint check bounds the waste to the layers that actually changed.

So there is no flush operation, and no notion of a "flushed" state to reason about.

## 6. No eviction, and specifically no LRU

An LRU bounds a population that exceeds memory by discarding the least-recently-used. This population does
not exceed anything. It is bounded *by the domain*:

- Parse atoms number one per layer that has a schema file — realistically a handful per chain and a few
  tens across a whole session of switching projects.
- Merged results number one per distinct chain (and its as-of-L prefixes) — single digits per open
  project.

Every entry is kilobytes, in a single-user process that restarts each session. There is no memory problem
to solve, so an eviction policy is machinery guarding a condition that cannot arise. Reaching for an LRU
here is cargo-cult.

If a bound were ever genuinely wanted, the correct trigger is *liveness*, not recency — drop a project's
entries when it is switched away, as #392 drops its index memo on scope change. But the caches here are
**switch-stable by construction**: parse atoms are keyed by absolute path, so a layer's schema is the
same entry no matter which descendant is open, and switching *back* reuses it. So even liveness eviction
buys nothing. The cache lives and dies with the process and rebuilds on first read.

## 7. The interface — one door, cache-oblivious consumers

This is the principle that keeps the cache from becoming "a second private merge with its own bugs," which
is the risk the issue names by name and which `ResolvedIndex.schema` is the embryo of.

**Resolved definitions are obtained from a single function parameterised only by `(root, up-to-layer L)`**,
with L defaulting to the resolution scope — today's `read_metadata_schema(root, *, up_to_layer_id=…)`.
That door owns the cache. No consumer holds a cache handle, and no consumer merges layers itself. The
index build and the as-of-L authoring surfaces are *the same call with different L*, which is the whole
reason the parse atom had to be per-layer.

The one nuance comes straight from ADR-0045: a consumer **may hold** a resolved value for the lifetime of
its unit of work — an index build wants a schema that cannot shift mid-build — but it must **obtain** that
value from the door, never produce its own. So `ResolvedIndex.schema` does not vanish; it becomes a
legitimate within-unit hold of *the door's output*, not a parallel producer. The rule is: **hold for your
unit, produce nowhere but the door.**

## 8. What this delivers, and where it stops

This design delivers the definitions cache and makes the identity map *separable* from a schema edit: the
definitions have their own lifetime and their own key, and a schema edit's invalidation is expressed as a
definitions change, not a file change.

It does **not** rewire the index change-gate to actually stop dropping identity when a schema file is
written. Today a schema write drops the whole index memo; making it re-derive edges alone — a lookup over
the reference edges by the changed field, plus a values scan only for newly-reference-typed fields — is
the edge-invalidation work that belongs to **slice E ([#314](https://github.com/antoncl/local-writing-app/issues/314))**,
which Amendment 1 says must be planned against this model. The honest seam: this design makes the
separation *true and possible*; making it *observable* — proving a schema edit leaves `candidates`
untouched — lands with #314. The acceptance criterion that asserts identity is untouched is therefore a
#314 test, not a #394 one.

## The tests it must pass

The shape is clear enough before implementation to fix the behavioural contract, and each obligation is
stated with the **mutation it exists to catch** — a test whose regression cannot be named is not
defending a principle. Grouped by the principle each defends.

**A. The parse is cached (§2 level 1).**

1. A second read of an unchanged chain performs **zero** YAML parses. *Catches:* a cache that stores but
   never hits.
2. An ancestor shared by two different chains is parsed **once**; both reads reuse the same atom.
   *Catches:* collapsing level 1 to a per-chain cache, which re-parses shared ancestors.

**B. Invalidation is per-layer (§3, §5).**

3. Editing one layer's schema re-parses that layer only; a sibling layer's atom is the same instance
   afterwards. *Catches:* whole-chain invalidation — the fusion this design exists to break.

**C. The merged result (§2 level 2, §4).**

4. Two reads of an unchanged chain return the **same object** — no re-fold, no re-validation. *Catches:*
   caching only the parse and leaving the merge to churn; this test goes red if level 2 is dropped.
5. A change to `build_identity()` with unchanged files rebuilds the merged result. *Catches:* code
   identity missing from the merged key — a model change silently serving stale objects.
6. A change to `build_identity()` re-parses **no** atom. *Catches:* code identity leaking into the atom
   key, which would kill cross-project reuse. The adversarial dual of test 5.

**D. As-of-L is a truncated fold, not a second merge (§3).**

7. `up_to_layer_id=L` equals merging base→L, and at the root layer equals the full read. *Catches:* an
   as-of-L path that merges differently from the full path — two producers drifting.
8. A definition that exists only at a layer *below* L does not appear in the as-of-L result. *Catches:*
   truncation implemented as a filter that leaks lower layers.
9. Reading the full chain and then as-of-L parses no additional files. *Catches:* as-of-L building its
   own atoms instead of sharing the primitive.

**E. Reload is stat-on-read; absence is data (§5).**

10. A schema file appearing at a previously-empty layer is reflected on the next read. *Catches:* caching
    "absent" as permanent — addition blindness.
11. A schema file deleted un-defines its fields on the next read. *Catches:* a parsed atom outliving its
    file.
12. Content changed under an **older** mtime is still re-parsed. *Catches:* a recency-based staleness
    check instead of equality — the backup-restore case ADR-0040 names. (The accepted non-goal: content
    that changes with byte-identical `(mtime_ns, size)` is not a test but a documented limitation,
    inherited from the index manifest.)

**F. Switch-stable (§6).**

13. Switching projects and back reuses the atoms rather than re-parsing. *Catches:* dropping the schema
    cache on scope change — copying #392's memo lifetime, which is wrong for a path-keyed cache.

**G. One door (§7).**

14. Structural: the layer-merge machinery is reached only through the one door, and the index memo's held
    schema is the door's output rather than an independent merge. *Catches:* a future second private
    producer — the "second merge with its own bugs" the issue names. Mirror the import-guard style of the
    existing scope-invariant test.

**H. Deferred to #314, named here so it is not forgotten.** A schema edit leaves the identity map
(`candidates`) untouched. This is the acceptance criterion that proves the three lifetimes are actually
separate, but it is only *observable* once the change-gate stops dropping the whole memo on a schema
write — slice E's work (§8). It is listed as this design's obligation on #314, not a #394 test.

## Decisions and rationale

The four questions ADR-0040 Amendment 1 deferred, answered. This section is the decision record ADR-0040
points to.

1. **What the cache key is.** The parse atom is keyed by the schema file's path with its `(mtime_ns,
   size)` fingerprint stored alongside; **no code identity.** The merged result is keyed by chain identity
   with the participating fingerprints **and** `build_identity()` stored alongside. Code identity is
   confined to the level that holds validated objects, and kept out of the level that must be shared
   across projects. *Rejected:* putting code identity in the atom key — it would defeat cross-project
   reuse for no benefit, since raw parsing is code-stable.

2. **Per-layer or per-chain.** Per-layer is the primitive; per-chain is a derived, memoised fold on top.
   *Rejected:* per-chain as the primitive (what the code does today) — it cannot share an ancestor across
   books and cannot answer as-of-L without a separate merge.

3. **Whether it persists.** In-memory only. Persisting saves single-digit milliseconds against a
   multi-second cold index build already covered by the index snapshot, in exchange for a second on-disk
   staleness surface. The atoms rebuild on first read. *Rejected:* a persisted schema cache — cost without
   a corresponding win, and a new invalidation surface.

4. **Where it lives.** In the schema slice, behind the one door, consumed by the index rather than owned
   by it. *Rejected:* keeping it on the index memo (`node_index_*`) — that is the fusion Amendment 1 exists
   to break, and it hides the artefact from the as-of-L surfaces that also need it.

## Relationship to the ADRs

- **ADR-0040 Amendment 1** is the decision of record that this cache is required and that the index is
  three caches, not one. This document supplies the storage design that amendment declined to specify; the
  amendment gains a pointer here and no new subject.
- **ADR-0045** governs the interface (§7): scope belongs to the unit of work, and a consumer holds a
  resolved value for its unit but obtains it from the one door.
- **ADR-0042 §3** requires the as-of-L read (§3 here) and is the surface that makes a per-layer primitive
  necessary rather than merely tidy.
