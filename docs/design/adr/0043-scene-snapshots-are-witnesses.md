# ADR-0043: Scene snapshots are witnesses — prose is restored, context is only reported

- Status: **Draft — awaiting red pen**, 0.8.0
- Feature: #6 (scopes the "revisions" issue) · Relates: #314 (composite revision) · Follows: ADR-0001,
  ADR-0002, ADR-0003, ADR-0010, ADR-0039
- Supersedes nothing. Settles the four-way scoping question posed in #6.

## Context

Issue #6 records that "revisions" is ambiguous and lists four candidate meanings: per-save snapshots,
named drafts, per-scene git-style history, and a time-travel UI. It asks for one to be picked. The
survey below is why the answer is none of them exactly.

**Saving is not an authoring intent here.** Scene, lore and prompt editors autosave on a 6-second
idle debounce (`AUTO_SAVE_IDLE_MS`, `frontend/src/lib/stores/editorPanes.svelte.ts:88`), re-armed on
each keystroke; there is no manual Save control for those editors. A save boundary therefore means
"the author stopped typing for six seconds", which is not a fact anyone wants to navigate. Per-save
snapshots are not merely expensive at that cadence — they are meaningless.

**There is no git in this codebase.** No dependency in `backend/pyproject.toml`, no subprocess
invocation, no assumption that a project folder is a repository. Git-style history is a new runtime
dependency on a Windows-first application, landing in the cycle before a debt-free 1.0 gate.

**Two words are already taken.** `revision` is the transient optimistic-concurrency token —
`_revision` (`backend/app/services/project_service.py:435`) hashes the file's current bytes and is
compared against `base_revision` on the save request (`backend/app/models/entries.py:117`); it is
never written to disk and there is exactly one live value per file. "Time travel" is the *in-fiction*
scrubber of ADR-0013, which walks a lore entry through story time. A real-world feature reusing
either word would collide with something authors already use.

**Nothing today retains a prior version.** Saves are last-write-wins through one atomic-write
primitive (`_atomic_write`, `backend/app/services/project_service.py:256` — same-directory temp file
then `Path.replace()`); deletes are `unlink`. The only backup mechanism in the product is the
whole-project zip taken before a schema migration (`.migration-backups/`, keep last 3).

### Why a scene's prose does not determine a scene's meaning

Mid-scene mutations are stored as markers *inside scene bodies* (ADR-0001, Model A) and resolve
**cumulatively across the manuscript**. A record is live iff `start ≤ pos < close`, close exclusive
(ADR-0010; `MUTATION_CLOSE_PATTERN` and the note at
`backend/app/services/project/lore_mutations.py:108-115`), and `effective_state`
(`backend/app/services/project/lore_mutations.py:610`) counts a record from an earlier scene as live
regardless of position within the current one.

So consider five scenes where scene 2 opens an interval and scene 4 closes it. **Scene 3 carries no
markers at all**, yet what the world is during scene 3 is decided entirely by scenes 2 and 4. A
byte-exact copy of scene 3's prose is therefore *not* a record of scene 3. Restore it after the start
marker in scene 2 has been deleted and the prose returns identical while the world behind it differs,
with nothing in the scene itself to indicate the change.

Manuscript order compounds this: interval semantics depend on scene ordering, which lives in
`manuscript.structure.yaml` — a different file, which no per-scene history would capture, and
reordering is not a scene edit at all. (A scene absent from the manuscript resolves to base only;
`effective_state` returns `{}` when the scene has no manuscript position,
`lore_mutations.py:651-654`.)

ADR-0039 adds a **second, independent axis**. Once hierarchies land, a lore entry's base is not a file
but a composition across the declared ancestor chain plus `overrides/` deltas. Editing a series-level
entry changes what a book-level chapter meant, with no edit anywhere near that chapter.

There is a **third**, developed below: the field definitions the recorded values are interpreted
against can themselves change. The count is not claimed to be final — the point is that context drifts
along several independent axes, each needing its own detector, and that a design assuming one axis
will be wrong.

**Conclusion: a fully correct snapshot of a scene is not constructible.** That is a property of the
mutation and inheritance models, not a gap to be closed. The decision below is built on accepting it
rather than attempting to defeat it.

## Decision

**A snapshot is a witness, not a restore point for the world.** Prose is restored byte-exact.
Surrounding context is *captured at snapshot time, never restored*, and is reported when it has
drifted.

**The unit is the scene, and v1 covers scenes only.** Scenes are leaf prose — the artifact whose loss
an author feels. Lore entries are the *targets* of both drift axes and their bodies become composed
values under ADR-0039, so including them would mean confronting layer composition on day one for a
much weaker payoff.

**A snapshot record holds two parts.** The scene body as written, and a witness of the context that
gave it meaning: the resolved output of `effective_state` for the entities influencing that scene, and
a change-detection token per influencing entity. The witness is diagnostic only. It is never restored,
never authoritative, and never consulted by the resolver — which preserves the model's existing rule
that effective state is derived and never stored (ADR-0010's revert path recomputes rather than reading
back a stash).

**Drift on the inheritance axis is detected by the entity's `revision`, consumed as an opaque change
token.** The witness stores whatever `_revision` returns for each influencing entity at capture time;
the drift check is a recompute-and-compare, never a re-resolution, and the snapshot code never inspects
the token's structure.

This makes the feature **independent of #314 rather than blocked on it**. ADR-0039 requires `revision`
to become a hash over the ancestor file plus every override in the chain — but that redefines an
existing value rather than adding a new one, so snapshots get the more correct detector automatically
when #314 lands, with no change here. The one seam: tokens captured before that change do not compare
meaningfully against tokens computed after it. Those snapshots report the inheritance axis as *unknown*
rather than as *unchanged* — an honest degradation, and pre-1.0 it needs no migration.

**Storage is full copies, not deltas.** Every snapshot stays independently restorable and readable in
any text editor, with no replay chain whose corruption would forfeit everything after it. Scenes are
kilobytes; the space argument for delta encoding does not clear that bar for the one feature whose
entire job is not losing the author's words. Plain text buys the *diff view* for free — it does not
oblige the *storage* to be delta-encoded, and conflating the two is the error this paragraph exists to
prevent.

**Two capture triggers, with asymmetric retention.** An automatic snapshot at the editing-session
boundary — captured lazily when a pane opens a scene, materialized only if that session goes on to
dirty the document, so clean reads cost nothing. This yields at most one per scene per session and
answers "what did this look like when I sat down". Plus an explicit author-invoked snapshot, as in
Scrivener. The explicit control alone is insufficient because the feature is worth most precisely when
the author forgot to press it; the automatic capture alone is insufficient because only the author
knows which state was worth marking.

**Automatic snapshots retain the last five per scene; explicit ones are never thinned.** Five because
the automatic tier is a prosthetic for the author's own recall of recent states, and that is roughly
the depth a person holds — a human context store, working differently but not unboundedly. Beyond
that the list stops being navigable and becomes an archive nobody reads, which is what the explicit
tier is for. The number is a considered default, not a measured optimum; if it is ever made
configurable, the reason to change it should be evidence about how authors actually navigate the list,
not the assumption that more history is strictly better.

**Restore replaces the scene body and reports drift.** It does not touch the mutation records in other
scenes, the manuscript order, the lore entries, or any ancestor layer.

**Drift reporting is advisory, never blocking.** A restore into drifted context is shown and then
allowed. This app is a tool, not a straitjacket: an author who understands the consequence is entitled
to the outcome, and tools that refuse the unusual case are the ones people work around. There is no
"are you sure" gate, no acknowledgement checkbox, and no restore this feature declines to perform.

The obligation that decision creates is the important half, and it is binding on the surface design:
**if the report is the only protection, the report is the feature.** It must name what actually
changed — the entity, the field, the value then versus now — in the author's vocabulary, not "context
has changed since this snapshot was taken". A vague warning is worse than none, because it trains
dismissal and then fails silently on the one occasion it mattered. Any surface that cannot state the
specific consequence has not implemented this ADR.

**The user-facing surface is not designed here.** How snapshots are listed, compared, named, or
invoked is deliberately left open; this ADR fixes only the contract those surfaces must honour
(advisory, specific, in the author's vocabulary). It is a separate design pass, and nothing in this
document should be read as constraining its shape.

## Identity: a snapshot carries its own id and is never an indexed node

A snapshot must not reuse the source node's `id`. The front-matter `id` is canonical identity
(`project_service.py:374-375`) and the node index maps `id → [candidates by layer]` (ADR-0040) — a
second file bearing a live scene's id is an index collision, not a historical record, and it would make
`_path_for_node_id` non-deterministic and reference resolution ambiguous.

**A snapshot is stored as two files: the captured bytes, and a sidecar describing them.**

- `snapshots/<source-node-id>/<snapshot-id>.md` — a **byte-for-byte copy** of the scene file as it was,
  front matter included. It therefore still carries the *source* node's id, which is correct: it is a
  photograph of that file.
- `snapshots/<source-node-id>/<snapshot-id>.yaml` — the snapshot's own record: `id`, `snapshot_of`
  (the source node id), `captured_at`, the scene's `title` as captured, `retention`, the
  `schema_version` in force at capture, and the witness.

Splitting them is what makes byte-exactness *provable rather than reconstructed*. Restore is a file
copy, not a re-serialization of nested YAML — and for the one feature whose job is not losing the
author's words, a round-trip through a serializer is precisely the risk not worth taking. It also keeps
the witness out of the restored bytes entirely.

**`retention` is `thinned | kept`**, not a boolean. `thinned` is subject to the keep-five policy;
`kept` is not. An enum because the field will plausibly grow a third case (an author-pinned automatic
capture is the obvious one), and a boolean extension point is the shape this repo has had to retire
before.

The sidecar's key names are otherwise unremarkable, and deliberately so: it is a private file the
author never edits, parsed by its own model, namespaced by its own directory. Cross-ADR terminology
discipline applies to words that appear in *design prose and shared code* — where the historical cost
has been human confusion between two ADRs meaning different things by one word — not to internal keys,
which cannot collide with anything.

**The directory layout is the lookup table.** "How many snapshots does this id have, and which?" is a
directory listing — no index to build, invalidate, or repair, and the answer survives any cache
corruption because it *is* the storage. An index is only warranted by a query the filesystem cannot
answer cheaply (project-wide chronological listing is the plausible one), and should be added when such
a surface exists rather than in anticipation of it. Note this deliberately departs from "filenames are
cosmetic": here the *directory* name is the source id, load-bearing and never renamed, because ids are
stable and titles are not.

**Invariant: `snapshots/` is not part of the node index, and is excluded at the index, once.** Not by
a filter at each consumer — an unexcluded store would put five extra members into every view over
scenes, and correcting that at each call site is the defensive shape this repo avoids. The exclusion
belongs where `.cache/` and `.migration-backups/` are already handled, and ADR-0040's staleness
manifest must skip it too, or every capture invalidates the index. Being *node-shaped* is not being an
*indexed node*: a witness is evidence about the graph, not a participant in it.

**Snapshots outlive their source — but only if they remain reachable.** Deleting a scene leaves its
snapshot directory in place, and an earlier draft of this ADR stopped there. That was wrong:
**unreachable data is not preserved data.** The directory is named by node id, the author knows scenes
by title, and once the scene is gone there is no node left to hang an affordance on — so "we kept it"
would amount to disk usage plus a false sense of safety, with recovery available only to someone
willing to grep the filesystem. That is a worse outcome than either honest alternative, because it is
the one that *looks* safe.

Two consequences, and they are a package:

1. **The sidecar denormalizes the scene's `title` as captured.** It is already present in the copied
   `.md`, but an orphan listing must not have to parse every captured body to render a name.
2. **Retention of orphans requires a recovery surface, and that surface is part of v1's acceptance —
   not a follow-up.** Deleting the wrong chapter is precisely the disaster this feature exists for, so
   the case must not be the one that silently fails.

If that surface is judged out of scope, then the honest fallback is to **delete a scene's snapshots
with the scene**, saying so in the confirmation. What must not ship is retention without reachability.

## The third axis is value reinterpretation, not schema change

Schema edits are invisible to the two detectors above — `_revision` hashes the *entity file's* bytes,
while the schema is a separate file merged across layers — so a third token is needed. But the axis is
much narrower than "the schema changed", and getting that boundary right matters more than the token
itself.

**Field availability needs no detector at all.** Stored files are sparse: a missing field is not an
error, and fields with no definition are stripped. So a field *added* after capture is simply absent
from the restored body, and a field *deleted* after capture is dropped on the way in. Both are handled
by the storage model already, and neither changes what the recorded values mean.

What remains is **reinterpretation of a value that is still present**: a field's type changing
(`text` → `multi_select`), or a select's option set changing so that a recorded value is no longer
among them. There the bytes survive and their meaning does not, which is the only case the author
cannot see for themselves.

So the third token covers **the type and constraints of the fields the witness actually recorded** —
not the merged schema as a whole. An earlier draft of this ADR proposed hashing the whole merged
schema; that is wrong, and the reason generalizes. A whole-schema hash fires on every schema edit,
including the additions and deletions the sparse model already absorbs, so most reports would announce
a change with no consequence. Under an advisory model (above) a detector that cries wolf is not merely
noisy — it trains the dismissal that makes the report worthless on the one occasion it mattered.
**Detector precision is part of the report-quality obligation, not separate from it.**

## Snapshots and the 1.0 migration contract

Snapshots introduce a category of data this project has not had before, and the distinction decides
everything else in this section:

- `.cache/` is **rebuildable** — ADR-0040's entire migration story is "bump the format key, rebuild
  once, never write migration code".
- `.migration-backups/` is **disposable** — pruned to the last three by design.
- Scene and lore files are **authoritative**.

Snapshots are none of these. They are **irreplaceable but not authoritative**: losing them destroys
information that exists nowhere else, yet they are not the source of truth for anything. That means
**the pre-1.0 escape hatch does not apply here.** "Bump the version and rebuild" is unavailable
because there is nothing to rebuild from, so a snapshot store written before 1.0 has to be readable
after it.

**Snapshots are immutable; migration happens at restore, not at rest.** A migration must not rewrite
stored snapshots. That is not only a cost argument — rewriting a witness destroys the thing that makes
it a witness. Instead, each snapshot records the `schema_version` in force when it was taken, and a
restore that crosses a version boundary runs the ladder over **that one body**, on the way out, leaving
the stored record untouched.

Two consequences follow, and the first is a **hard requirement on the migration framework that must be
settled before 1.0 freezes it**:

1. **Where a migration transforms document *content*, it must be expressible as a per-document
   function.** Today it cannot be: `MigrationFn = Callable[[Path], None]`
   (`backend/app/services/migrations.py:44`) takes a project root and mutates the filesystem in place,
   and all three registered steps are folder- or file-level (`migrations.py:140-144`). A migration
   authored only in that shape cannot be applied to a single snapshotted body, which makes
   cross-version restore impossible. The framework does not need this today; it needs it before the
   first post-1.0 migration touches scene content, and retrofitting it after the contract is frozen is
   the expensive order.
2. **Snapshots stay out of `SKIP_FROM_BACKUP`'s inverse — they need no migration backup.** Since
   migrations never touch them at rest, the pre-migration zip (`backup_project`, `migrations.py:176`)
   has nothing to protect there, and excluding them keeps the three retained backups from carrying a
   full copy of the project's history each. Immutability at rest is what buys this; the two decisions
   stand or fall together.

## Non-goals

These are excluded, with reasons; this ADR deliberately does not describe how any of them would work,
so that a later design is not bound by a sketch made here.

- **Restoring world state.** Not constructible (see Context), and it would contradict the derived-never-stored
  rule the mutation model is built on.
- **Snapshots of lore entries or other node kinds.** Out of v1 scope; the layer-composition question
  above must be answered first.
- **Whole-project checkpoints.** A coherent but different feature answering a different question. The
  catastrophic case is already partly covered by `.migration-backups/`.
- **Git, or any version-control dependency.**
- **Recovering the ~6 seconds of keystrokes that autosave has not yet written.** That is a separate
  defect (no `beforeunload` handler exists), not a snapshot concern.

## Pre-refuted simplifications

Each of these is tempting, was considered, and breaks. Stated here so a later thread does not
rediscover them as improvements.

- **"The marker diff already shows the consequences."** It shows changes to markers *in the snapshotted
  scene*. It is silent for a scene that sits inside an interval it does not own — the scene-3 case,
  which is the case that matters most. This is why the witness records resolved state rather than
  relying on a textual diff of markers.
- **"Store deltas, it's all plain text."** Conflates storage with display. See above.
- **"Only the whole project is a self-consistent unit."** True, and it is the strongest argument
  against this ADR. Rejected because whole-project restore makes losing unrelated work the default
  failure mode: an author who wants one chapter back does not want the rest of the manuscript rolled
  back with it, and a recovery feature whose safe operation requires that trade will be used once and
  then avoided. The narrow contract plus honest reporting delivers what authors reach for.
- **"Snapshot on every save."** The 6-second autosave debounce makes the boundary meaningless.
- **"Let migrations rewrite the stored snapshots, like they rewrite everything else."** Rewriting a
  witness destroys what makes it a witness — a record of what was there is worth nothing once it is a
  record of what a later migration thought should have been there. It also loses the free result that
  immutability buys: snapshots need no migration backup precisely because migrations never touch them.

## Test surface

The value of the witness framing is that the feature's correctness criterion becomes testable.
"Did we restore the world correctly" admits no test. "Did we accurately report the drift" does:

- Snapshot a scene inside an open interval; delete the start marker in an earlier scene; assert the
  restore reports the changed field and entity.
- Snapshot a scene; reorder the manuscript so the interval no longer spans it; assert the drift is
  reported.
- Snapshot a scene; edit the entry at an ancestor layer; assert the composite-revision comparison
  reports it.
- Snapshot a scene; retype a recorded field in `metadata.schema.yaml`; assert the reinterpretation axis
  reports it — and assert it reports *nothing* on the entity-revision axis, since no entity file
  changed.
- Snapshot a scene; **add** an unrelated field, and **delete** a field the witness recorded; assert
  neither is reported as reinterpretation (the sparse model absorbs both) and that restore succeeds.
  This is the anti-noise test — it pins the detector's precision, not just its sensitivity.
- Snapshot, change nothing, restore; assert no drift is reported and the body is byte-identical.
- Assert the resolver never reads a witness record.
- Assert a migration run leaves every stored snapshot byte-identical.
- Assert a snapshot's id differs from its source's, and that `snapshot_of` round-trips to the source.
- Assert `snapshots/` contributes nothing to the node index: a view over scenes returns the same
  members before and after six captures, and the staleness manifest does not change on capture.
- Capture seven automatic snapshots; assert five remain, that the two dropped are the oldest, and that
  an interleaved explicit snapshot survives regardless of age.
- Delete the source scene; assert its snapshots remain listable **and that each renders a human-readable
  name from the sidecar without parsing the captured body**. The reachability half is the half that
  fails silently, so it is the half worth pinning.

## Naming

**"Snapshot"** is chosen: it is Scrivener's term, so it is the word authors already have, and it
promises a photograph rather than a time machine — which is exactly the contract above. It avoids both
live collisions (`revision`, "time travel").

Disclosure, since the term is not unused: `snapshot` appears in roughly eighteen files as an
implementation noun (AI session state, workspace layout, collapse state) and, more significantly, as
ADR-0040's `.cache/` node-index snapshot (#306) — a real domain noun in the same repo. None are
user-facing. If that overlap is judged too close, the alternative is to name the feature for what it
holds rather than what it does.

## Sequencing

Nothing here is semantically blocked on 0.7.0. The feature reads `effective_state` and `_revision`
without modifying either, so the constraint is **file contention, not dependency order** — the
question to ask before scheduling a slice is whether it edits the same files as work already in
flight, not whether the design depends on it.

On that criterion the backend is close to disjoint from #313/#314: a snapshots service and its routes
are new files, and the touch points into existing ones (mixin registration, route registration, the
capture hook) are thin. The frontend is where the contention is — the editor surface is being reworked
by the hierarchy slices under ADR-0042, so any snapshot UI should follow them rather than race them.
That argues for the backend and its tests landing whenever convenient, and the surface afterwards.
