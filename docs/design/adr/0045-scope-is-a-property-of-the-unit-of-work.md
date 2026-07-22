# ADR-0045: Scope is a property of the unit of work, not of the process

- Status: **Accepted** — 2026-07-22 (Anton, PR #389). Drafted from his framing of the book as a build target with
  the ancestor projects as its dependencies. Its two open questions — the cached title and the
  last-migration result — were answered by him the same day; see the closing section. Reviewed on a
  second thread, whose four corrections are §1 (scope is captured when the work is *initiated*), the
  wire asymmetry in §1, §5 (the choke point) and the restart note in Consequences.
- Feature: #7 · Issues: #381 (the data-loss symptom), #307 (the in-memory index it unblocks)
- Follows: ADR-0005 (book as the resolution boundary), ADR-0039 (the hierarchy model),
  ADR-0040 (the node index), ADR-0042 (the bounded authoring layer L — **this ADR generalises its
  §3 rule from the picker surfaces to the whole unit of work**)
- Amends the wording of: ADR-0039, ADR-0040, ADR-0013 — each says *"the open project"* where it now
  means *"the project this unit of work is scoped to"*. A substitution, not a supersession.

> **Code references.** This ADR describes **roles and behaviours**, not call sites. Where it must
> point at code it names a role ("the layer walk", "the node save path") rather than a symbol or a
> line, because those rot and have already caused real misreadings in this repo. The few concrete
> claims about *current* behaviour — §4's known gap, §6's route census — were verified against
> **`6284bda` (2026-07-22)** and are true of that tree only. A reader arriving later should re-verify
> before acting on them, and an implementer should treat a disagreement with the code as evidence the
> ADR aged, not that the code is wrong.

## Context

### The model we actually have

A book is a **build target**. The projects above it in the folder hierarchy are its **dependencies**.
The layer walk is the **resolver**: it decides which dependencies are pulled in and in what order.
The node index is the **resolved graph**, and its snapshot (#306) is the **build cache** — which is
why keying it to a root was right, why a copied folder must invalidate it, and why the cache carries
a digest of the resolver's own source. Build caches invalidate on toolchain change.

Most of the time a dependency is consumed as-is. Sometimes it is extended; sometimes a descendant
shadows it. The traditional way to change a dependency is to open that project and edit it — valid,
and still supported — but heavyweight for a small tweak. **ADR-0042 is the in-place patch gesture**
that exists so a minor override does not cost a context switch.

### What scope means, concretely

A book introduces a faction conflict. It is resolved entirely within that book and must never reach
the series. Modelling it needs a **`faction` field on a lore entry the book does not own** — the
entry is the series', the amendment is the book's.

Three things follow, and together they are what "scope" means:

1. **The field is defined at the book layer.** It exists in the book's schema and nowhere above it.
2. **The value is written as the book's delta on the ancestor's entry** — the series' file is not
   touched. The book amends its dependency without modifying it.
3. **The write is verified against the book's field definitions**, because the book is where both the
   field and the value live.

Now move the layer picker to *series*. The `faction` field **is not shown** — the series has no such
field, and a series-level write could not store it. Move it back to *book* and the field reappears,
with the delta intact.

That disappearance is not the UI hiding something. It is the schema resolving through a shorter
dependency chain, and it is the visible face of the rule ADR-0042 §3 already states: the roster can
only shrink as the authoring layer rises, so a name is always asserted at or above the layer holding
the value that uses it. Upward-dangling vocabulary is unconstructable rather than something to catch
in validation.

**So the picker does not merely choose a destination file. It chooses which rules apply and which
vocabulary exists.** That is why it is a change in scope and not a write-target label.

### Deleting is scoped too, and this is where it bites hardest

**A book-level delete of an inherited lore entry cannot delete that entry in the dependency.** It can
only remove what the book asserts about it.

So "delete" at a layer means *remove this layer's opinion*, never *remove the thing*:

- the book holds a **shadowing copy** → the copy goes and the ancestor's entry becomes visible again,
  with its own references and its own values;
- the book holds only a **delta** (the faction amendment above) → the delta goes and the pristine
  ancestor remains;
- the book holds **nothing** — a purely inherited entry — → there is nothing at this scope to delete,
  and the gesture must not be offered as if there were.

Removing the series' entry requires scoping to the series, exactly as deleting a dependency means
opening that project rather than deleting your local patch of it.

This is not a refinement; it is the rule the reference purge broke. Deleting a shadowing copy is not
a deletion of the id — the id still resolves, one layer out — and treating it as one destroyed
references across the project that had just become correct (#379). The same rule is what makes
un-shadowing on delete a *requirement* of the index rather than a nicety (#307): the ancestor must
come back whole, edges included, because it never went anywhere.

### The defect

The build target is implemented as **mutable ambient process state**: a module-level service whose
project path is reassigned when a project is opened. The delete routes and the open-project route are
all synchronous handlers on the web framework's threadpool, so one unit of work can have its target
swapped mid-flight by another.

Every defect found in the #306/#307/#379/#381 sequence is one shape: **an operation resolving its
project twice and getting two different answers.**

- The reference purge rebuilt its index from the ambient state after the caller had already unlinked
  a file — a delete in one project rewrote another project's files (#379, #381; reproduced as data
  loss).
- The index build took its root explicitly but read its schema from the ambient state, indexing one
  project's files against another's schema and persisting that into the *correct* project's cache.
- The manuscript tree re-resolves between reading and writing the structure, so a concurrent open
  overwrites another project's structure document wholesale — no id collision required, and present
  on every manuscript mutation, not just deletes (#381).

These are not concurrency bugs to be locked away. Locking would serialise the straddles while leaving
the model that generates them in place. No compiler holds a mutable global "current project" that a
second invocation can flip halfway through resolution.

### Why the newer code already disagrees with the older

Everything 0.7.0 added takes the project explicitly — the layer walk, the index build, the schema
merge, the snapshot path. Those sit alongside ~60 call sites that ask the ambient state instead. Two
models coexist, and the bugs live on the seam. The ambient state itself is small: a project path, a
cached title, and the last migration result.

## Decision

### 1. A unit of work carries its scope, captured when the work is *initiated*

A unit of work is not "one API request" — it begins when the work does. For a pane that is **when
the document was loaded**, and the scope travels with the buffer exactly as `base_revision` already
does. The scope is part of the edit's provenance, not a reading of the app's current state at the
moment a request happens to be flushed.

This is what makes a late write safe. A pane opened against one book and autosaved after the user has
moved to another must write to **the book it was editing, or fail** — never to whichever project is
open now. Capturing scope at send time would send it to the wrong project with no error anywhere,
which is the client-side twin of the server-side straddle in §2.

Its scope has two components:

- **Resolution scope** — the project being built. Fixes the dependency chain the resolver walks, and
  therefore what the node index, the merged schema and every read resolve through.
- **Authoring layer `L`** — the write target, bounded by ADR-0042 §2
  (`node's owning layer ≤ L ≤ resolution scope`). Defaults to the resolution scope, which is the
  degenerate case covering almost every request.

**On the wire, they are not symmetric.** The resolution scope is sent by every unit that needs a
project. `L` is **optional and omitted by default**, sent only by the ADR-0042 edit unit that
selected it; absent, it *is* the resolution scope. §4's validation depends on `L` having arrived, so
this must not be left for an implementer to infer.

### 2. A unit of work resolves its scope once and never re-resolves it

This is a rule about **our own code**, and it is the whole invariant: every defect above is one
operation asking "which project?" twice and getting two different answers.

It is deliberately *not* a claim that the project cannot change underneath us. Nothing stops a user
dropping a file into an ancestor's folder, hand-editing a scene, or opening the parent project in a
second browser session, and no amount of scoping will stop them. We do not defend against the world;
we defend against **ourselves**.

So the standard is a shape, not a guarantee of freshness:

- **Self-consistency is required.** A unit of work must never mix two scopes — that is what turned a
  delete in one project into a rewrite of another's files.
- **Staleness is acceptable and detected.** A unit may act on a chain that moved a moment ago. The
  manifest and staleness machinery (#306) catches that at the *next* unit boundary, which is the
  right place: a fingerprint comparison, not a lock.
- **Incoherence is not acceptable.** An out-of-band change may make a unit stale, or make it fail —
  both fine. It must never let a unit produce a structure our own code cannot reason about, and it
  must never let a unit write outside its own scope.

That last line is the one worth enforcing in review, and it is the existing "invariants, not
defenses" rule applied to scope: garbage in may error, but must not corrupt a *different* project.

### 3. Changing scope is a unit-of-work boundary, not an exception to §2

Scope changes are ordinary, deliberate user actions. There are two selectors, and neither mutates a
unit already running:

- the **project switcher** selects the resolution scope for subsequent units;
- the **ADR-0042 rail picker** selects `L` for the edit unit it initiates, and resets afterwards.

### 4. Constraining vocabularies resolve as of `L`, everywhere — not only in the picker

ADR-0042 §3 decided this for the surfaces a picker feeds: the schema roster, reference candidates and
the tag vocabulary resolve `base → L`. The faction example above is that rule seen from the user's
side.

**This ADR extends it from what a picker offers to what a write accepts.** A write validated against
a chain deeper than its own target is validated against rules its file does not live under — it would
accept fields the target layer cannot store, and fail only later, when a sibling book reads it.

⚠ **Known gap as of `6284bda`.** The node save paths resolve the schema through the resolution scope,
not as of `L`; the as-of-`L` resolution exists but is used only by schema authoring. This is latent
only because no picker ships yet. **#313/#314 must not ship without closing it.**

### 5. One choke point, where the scope is read

The requirement that no unit reaches a project's files without that project having been prepared is
enforced **once, at the single place the incoming scope is resolved** — an unprepared scope resolves
to an error, for every route, without any route knowing about it.

Not per-route checks. Those would be defenses in the sense §2 disavows: N places that must each
remember, and a new route is a new hole. One resolution point makes it structural, and it is the same
place §1's scope arrives.

### 6. Scope therefore cannot be ambient

Two operations from one session can legitimately differ in scope: reads at the book, one edit at the
series. Ambient state cannot represent that — not merely because it is fragile under concurrency, but
because the feature already requires two answers at once. Scope travels with the request.

### 7. Opening a project keeps its preparation job and loses its ambient one

Opening currently conflates two things. **Preparation** — migrate, validate, record as recent — is
one-time-per-project and idempotent. **Selection** — assigning the ambient path — moves to the
client, which already holds the project path and already re-sends it after a reload.

The wire change is narrow: every frontend call goes through a single request helper, so scope becomes
one header in one function rather than ninety edits. As of `6284bda`, of 117 routes, 98 need a
resolution scope, 11 genuinely do not (machine settings, provider catalogue, directory browsing,
project create/open/health) and 8 already degrade to the machine layer when no project is open. The
split is clean enough to migrate router group by router group.

## Why / rejected alternatives

**A lock around project-changing operations.** Cheapest, and it would close #381. Rejected: it
serialises the straddle rather than removing it, keeps ambient resolution as the design, and cannot
express §5 at all — two scopes in one session is not a race to be excluded, it is a requirement.

**Thread the root through call by call.** This is what the #381 partial fix did for the purge, and it
works. Rejected as the general answer: one adversarial pass over that change found four more
re-resolution sites, and the fix itself exposed a fifth. Whack-a-mole against a model that keeps
generating the moles.

**Abolish "the open project".** Considered and rejected — it is the build target, and it is the
correct concept. The layer id already travelling on the wire, and ADR-0042's picker, are not evidence
that it is breaking; both are meaningless except *relative to* one resolved dependency graph.

**A per-request service instance.** Viable, but it makes every request pay construction and would
scatter the caches #307 wants to keep warm. A scope value passed to a stateless service keeps the
cache keyed where it belongs.

## Consequences

- **#381 dissolves** rather than being patched: a unit of work cannot observe a scope it did not
  start with. Its three remaining windows stop being individually fixable defects and become
  instances of one rule.
- **#307's remaining half gets its owner.** The in-memory index memo is keyed by resolution scope, so
  "who drops the index on project switch" stops being a question — a different scope is a different
  cache entry, and nothing needs invalidating.
- **ADR-0039, ADR-0040 and ADR-0013** each need *"the open project"* read as *"the unit of work's
  resolution scope"*. ADR-0040 carries real coupling — the index is keyed to one root — and should
  say so explicitly.
- **A migration path exists that is not a flag day**: the project-free and degrading routes need
  nothing, and the rest can move a router at a time behind a scope that falls back to the ambient
  value until the last one lands.
- **Preparation stays reachable, and partly moves to the wizard.** With selection client-side,
  nothing calls open implicitly, so a project that has never been prepared must still be migrated and
  validated. Some of that belongs to the create/open wizard (#318), which is the surface that already
  knows a project is being introduced rather than merely visited.
- **Restart is not a switch, and §5 is what covers it.** After an app restart the client re-sends a
  stored path without switching anything, so any rule phrased as "preparation happens on switch"
  skips that path entirely. Today's client does call open on restore, but depending on that is
  depending on client discipline. The choke point in §5 makes preparation unskippable regardless of
  how a scope arrives.

## The two ambient values that are not scope (settled)

Besides the project path, the service caches a **title** and a **last-migration result**. Neither is
scope, both must go somewhere, and they turn out to want *different* answers. Facts below verified
against `6284bda`.

### The title

Four readers, and only one of them genuinely depends on the cache:

- the **layer walk's labelling** uses it as the root layer's display label;
- the **project info response** returns it;
- the **project-node restore** and the **project-node read** use it only as a *fallback*, after a
  manifest or front matter they have already read.

The deciding fact: **the layer walk already reads the project manifest on every walk**, because the
rule that decides where the chain stops reads it. The title is a key in that same file. So deriving
it per unit of work costs one dictionary lookup on a read that is already happening — not an extra
file read.

Three consequences worth weighing:

1. **Cost is effectively zero**, so the "it's hot" objection I raised earlier does not survive
   contact with the walk's actual behaviour.
2. **Rename coherence becomes automatic.** Today renaming a project writes the new title into both
   the manifest and the cache, and the cache is correct only because that second write exists.
   Derived, the next unit of work simply reads the new value.
3. It removes an ambient field rather than relocating one.

**But there is a requirement the cache question has to answer to.** ADR-0042's rail picker lists
layers, and an ancestor layer should read as *its project's title*, not as its folder name. As of
`6284bda` the walk labels ancestors by folder name and only the root layer uses the cached title, so
the picker does not have what it needs yet. Titles for the whole chain mean reading each ancestor's
manifest, not just the root's — so "derive it, it's free" is true for the root and **not** true for
the chain.

**Settled:** the mechanism is an implementation detail and is the implementer's to choose — derive
per walk, cache per scope alongside #307's index memo, or read ancestor titles only when a picker
asks. The *requirement* this ADR fixes is that the picker can show real project titles for the whole
chain, which the walk does not gather today.

### The last-migration result — resolved by reclassifying it

Its one consumer is the project verifier's report, which surfaces it as a list of migrations applied.

**That is a misuse of the verifier**, and Anton's framing supplies the answer my two options missed.
The verifier's purpose is to check derived state against the only source of truth — the `.md` files —
and to force a rebuild of every cache and index built from them. "Which migrations ran when you
opened this" is not a fact about the project's integrity; it is a record of an action.

So it is neither scope nor verifier output. It is a **log entry**, and the log is a missing feature
(#386). The decision this ADR needs is therefore only the architectural half:

- **it stops being ambient process state** — required by §5, and unambiguous;
- **it leaves the verifier's report**, because it was never an integrity fact;
- **it becomes a log entry** — a plain append-only log under `.cache/` (#386), with the designed
  version tracked separately (#387).

**Knock-on worth stating**, because it is the same mistake one level down: the node index carries
`warnings` and `errors` that are persisted into the build cache and surfaced through the verifier.
Those are log material too — a cache should not carry a diagnostic history. #382 currently proposes
giving those diagnostics provenance so a patch can retract them; if they move to a log instead, that
problem dissolves rather than being solved, and #307's "a patch requires a clean index" restriction
goes with it.

**Neither value needs the per-scope cache**, which is the useful outcome: that object exists purely
for #307's index memo, and stays a performance concern rather than becoming a home for orphaned
state.
