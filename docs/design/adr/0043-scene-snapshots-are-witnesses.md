# ADR-0043: Scene snapshots are witnesses — prose is restored, context is only reported

- Status: **Accepted** — 0.8.0, 2026-07-22 (Anton, having read it alongside ADR-0044 and the mockup).
  Accepted covers the whole document **including Amendment 1** — snapshot-as-witness and its stated
  non-goal (context is never restored), scenes-only v1, full copies rather than deltas, the two
  capture triggers with keep-five/never-thinned retention, snapshot identity and the two-file store,
  the directory-as-lookup-table, deletion cascading with the scene, the three drift axes with the
  third narrowed to value *reinterpretation*, immutability with migration-at-restore, and the
  advisory-never-blocking rule with its report-quality obligation.
  · **Amendment 2 (2026-07-22, #395):** the session boundary is the backend's, inferred from save
  cadence at *N* = 30 minutes — replacing the pane-open wording in the capture-triggers paragraph.
- Feature: #6 (scopes the "revisions" issue) · Relates: #314 (composite revision) · Companion:
  **ADR-0044** (the surface) · Follows: ADR-0001, ADR-0002, ADR-0003, ADR-0010, ADR-0039
- Supersedes nothing. Settles the four-way scoping question posed in #6.

## Amendment 1 — what the surface pass found (ADR-0044)

The document was held open on the argument that designing the surface would probably expose
something the model was missing. It did. Three author actions had no place in the model, and all
three are the same insight from different angles: **the author needs control over what the strip
holds, and the strip must not lose anything without their say-so.**

**A snapshot can be deleted.** The model had automatic thinning (keep five) and cascade (delete the
scene, its snapshots go), but no author verb for a single snapshot. There now is one.

*This does not contradict immutability.* "Snapshots are immutable" means a migration must never
rewrite one at rest — falsifying a witness destroys what makes it a witness. It has never meant
undeletable. The two are stated together here because a later reader will otherwise see a collision.

Deletion is also trivially safe *because* snapshots are full copies (below). Under delta storage,
removing a middle snapshot would mean rebasing every later one against a new base — a chain repair on
the one feature whose job is not losing words. The full-copy decision was argued on restore
integrity; it turns out to pay for deletion too.

**A snapshot can be pinned**, flipping `retention` from `thinned` to `kept`. This is the third case
the enum was chosen for. It means an automatic snapshot the author notices is worth keeping does not
have to be re-captured to become permanent, and it makes delete one of a coherent pair rather than an
odd single verb.

**Restore captures first, automatically.** An earlier reading of this ADR held that restore was
recoverable because the author *could* capture beforehand — which rests the safety property on
foresight, the same weakness already identified in the explicit tier ("worth most precisely when you
forgot to press it"). Restoring therefore takes an automatic snapshot of the current state before
overwriting it. Two consequences:

- It is what actually justifies **advisory, never blocking** (below). A restore into drifted context
  proceeds with no gate not merely because the author is entitled to their choice, but because the
  action is *undoable*.
- It sharpens the contrast with delete. Restore is reversible → no confirmation. Delete is
  irreversible → confirm, naming what is going. Two destructive-looking actions in one strip get
  opposite treatments, on a principle rather than an aesthetic.

**Side effect worth stating rather than discovering:** the auto-capture is a `thinned` snapshot, so
on a scene already holding five it evicts the oldest. Restoring costs the author their oldest
automatic snapshot. That is the right trade — the state about to be overwritten is worth more than a
five-sessions-old one — but it reads as a bug when hit without having read this.

**The sidecar gains an optional one-line `description`.** Note this is *not* the denormalized `title`
that was removed earlier: `title` was a copy of data already in the byte-copy's front matter, whereas
a description is original data that exists nowhere else. Same file, opposite reasoning. Its
presentation is ADR-0044's, and deliberately open.

## Amendment 2 — the session boundary is the backend's (2026-07-22)

Settled on #395 before slice 1, and recorded here because the original wording above described a
*mechanism* the decision has since replaced. The rule:

> **On a save, if the last save to this scene was more than *N* minutes ago, capture the pre-save
> state first.**

The wording it replaces — "captured lazily when a pane opens a scene, materialized only if that
session goes on to dirty the document" — is a **frontend** concept. It makes pane open/close part of
the contract, needs a new event, and requires the two sides to agree on what a session is. The rule
above needs none of that: the backend already has the file, its modification time, and the save.

**Capture on session *close* was the first proposal and is rejected**, for three reasons in order of
weight:

- **The close event is the one thing the app cannot observe reliably.** There is no
  `pagehide`/`beforeunload` handler today (#369), and a crash, force-quit, OS kill or power loss
  fires nothing at all. The session that ended badly would be the session with no snapshot — the
  feature failing exactly where it is meant to help.
- **Tab lifetime is not a work session.** A browser left open for two weeks with daily editing yields
  *one* snapshot. The boundary that means something is a gap between **edits**.
- **It captures the wrong content.** The end-of-session state duplicates Live at the moment it is
  written. What an author wants back is the *pre-edit* state.

***N* = 30 minutes, and it is a constant, not a setting** — long enough that lunch does not split a
sitting, short enough that a morning and an evening are separate. A named constant in one place with
the reasoning beside it, so evidence makes it a one-line change.

A setting earns its place when users genuinely differ, the user can tell which value they want
*without understanding the implementation*, and a wrong value causes real harm. *N* passes only the
first: a wrong *N* cannot lose work, and "how many minutes constitutes a new session?" is
unanswerable without knowing how capture, thinning and pinning interact. The author already has
controls in both directions that require no knowledge of the rule — press the camera, pin what should
survive. **A parameter that cannot hurt you has not earned a place in the settings surface.** When
evidence arrives, the setting to add is the *goal* (how much history to keep), not the *lever*.

**Watch for the sprinter case:** short bursts with sub-*N* gaps collapse a day into one snapshot. If
that shows up in real use the answer is probably a second trigger — accumulated change since the last
snapshot — rather than a smaller *N*, because it adapts instead of asking the author to tune it.

## Amendment 3 — `revision` does not reach scope visibility, so the witness records the layer (2026-07-23)

Found while building slice 3 ([#439](https://github.com/antoncl/local-writing-app/issues/439)), and
recorded because this ADR currently rests the inheritance axis on an argument that does not carry the
whole load. The claim below is still true as far as it goes:

> This makes the feature independent of #314 rather than blocked on it. ADR-0039 requires `revision`
> to become a hash over the ancestor file plus every override in the chain […] so snapshots get the
> more correct detector automatically when #314 lands, with no change here.

**A lore entry changes in three ways, and the token sees one.** Anton's framing:

- **direct edit** — caught: `_revision` is a SHA-256 over the entity file's bytes;
- **delta** — caught, but by axis 1 (mutations are not edits to the file);
- **scope visibility** — **caught by neither**, and not by a composite `revision` either. Which layer
  wins, and whether the entry resolves in this scope at all, is a property of the *resolved index*
  (ADR-0039/0040), not of any file. No hash over file **bytes** can see a change that is entirely
  about which bytes were chosen.

**The amendment:** the witness records the **resolved source layer** per entity alongside the
revision token, and the drift report treats a moved layer as its own axis. It fires with no file
edit, and it is the only axis that can — which is exactly why it cannot be folded into axis 2.

**It records the layer's *label*, never its id**, and that constraint is part of the amendment rather
than an implementation note. `_layer_id_for_folder` is a SHA-256 over the resolved folder path, and
`layers.py` states the invariant it rests on: *"the cache is safe only because layer ids are never
persisted… a path-hash id survives neither a moved project folder nor a re-resolved symlink"*. A
witness is durable by definition, so storing one would make this axis fire on every witnessed entity
of every existing snapshot the first time the project folder moved, a drive letter changed, or
Windows handed back a different short-path spelling — a cry-wolf failure on a scale that would
discredit the whole report.

This does not weaken the independence argument, which was about *not blocking on #314*. It narrows
what #314 will fix for free: the token gets better, and this axis still needs its own record.

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
boundary, which **the backend decides from save cadence**: on a save, if the last save to this scene
was more than *N* minutes ago, the pre-save state is captured first
([Amendment 2](#amendment-2--the-session-boundary-is-the-backends-2026-07-22)). This yields at most
one per scene per session and answers "what did this look like when I sat down". Plus an explicit
author-invoked snapshot, as in Scrivener. The explicit control alone is insufficient because the feature is worth most precisely when
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
  (the source node id), `captured_at`, `content_written_at`, `retention`, the `schema_version` in
  force at capture, and the witness.

  **The record carries two times** (#458, 2026-07-23). `captured_at` is when the record was made:
  monotonic, so it is the listing's sort key and what thinning means by "the oldest".
  `content_written_at` is the scene file's mtime at capture — when the bytes it copied were written
  — and it is what ADR-0044's strip positions and labels by, because the automatic trigger fires
  *before* the save and so photographs the previous sitting's prose. Two facts and not one: captures
  of unchanged content share an mtime, so content time ties where creation time cannot. A snapshot
  taken before the field existed reads back with `content_written_at` falling back to `captured_at`
  — exactly what such a record has always displayed — because a stored snapshot is never rewritten.

  The sidecar carries no denormalized copy of the scene's `title`. An earlier draft did, first to let
  an orphan listing render a name, then — once orphans were retired — on the argument that `title` is
  mutable so the captured name can differ from the current one. Both are gone. Nothing is lost by
  removing it: the captured title is already in the byte-copy's front matter, so any surface that wants
  it can read it. What the field actually was is a denormalization with **no consumer that exists**,
  and this repo has paid for that shape before — mechanisms built for a render surface that never
  arrived, used by nothing, deleted later. If a surface materializes that needs the lookup to be cheap,
  it can denormalize then, with a reason.

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

**Deleting a scene deletes its snapshots.** The confirmation says how many are going.

An earlier draft of this ADR kept them, on the reasoning that destroying the last copy of an author's
prose is the opposite of the point. That was wrong, for a reason worth stating because it generalizes:
**unreachable data is not preserved data.** The directory is named by node id, the author knows scenes
by title, and once the scene is gone there is no node left to hang an affordance on — so retention
without a recovery surface is disk usage plus a false sense of safety, with the data available only to
someone willing to grep the filesystem. Of the three options that is the worst, precisely because it is
the one that *looks* safe. Building the recovery surface is the other coherent answer, and it is out of
scope here: it grows the feature well past snapshot-and-restore, for a case a general undelete should
own rather than one per feature.

Deleting also keeps snapshots consistent with the app as it stands — scene and lore deletes are hard
deletes (`path.unlink()`), and there is no soft-delete or trash anywhere. A feature that quietly
retained data after a delete would be the only such thing in the project, which is how a surprising
invariant gets established by accident.

**The durable property, which holds either way: a scene and its snapshots are one unit of deletion.**
That is true under today's hard delete, and would remain true under any future undelete or trash
metaphor — the snapshots travel with the scene rather than needing a concept of their own. If such a
surface is ever built, whether and how snapshots participate is a decision for that design, not a
commitment made here.

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

  **Membership alone is not a sufficient assertion, and the reason is a property of this design.**
  A snapshot's byte-copy claims its *source scene's* id, and the collector drops a second claimant of
  an id at the same layer. So a walk that reached the store would collide with the live scene, lose,
  and leave the index looking untouched — the invariant broken and every membership assertion still
  green. The assertions that survive that are the **staleness manifest** (it fingerprints every file
  the walk reads) and the **duplicate-id error** (it names both paths). Landed ahead of the store
  itself, so slice 1 cannot introduce a store that is walked.
- Capture seven automatic snapshots; assert five remain, that the two dropped are the oldest, and that
  an interleaved explicit snapshot survives regardless of age.
- Delete the source scene; assert its snapshot directory is gone and nothing is left behind under
  `snapshots/`. A partial delete would leave exactly the unreachable residue this ADR rejects.

## Naming

**"Snapshot"** is chosen: it is Scrivener's term, so it is the word authors already have, and it
promises a photograph rather than a time machine — which is exactly the contract above. It avoids both
live collisions (`revision`, "time travel").

Disclosure, since the term is not unused: `snapshot` appears in roughly eighteen files as an
implementation noun (AI session state, workspace layout, collapse state) and, more significantly, as
ADR-0040's `.cache/` node-index snapshot (#306) — a real domain noun in the same repo. None are
user-facing. If that overlap is judged too close, the alternative is to name the feature for what it
holds rather than what it does.

## Why this was held a Draft — and what it caught

> **Resolved.** The UX pass ran (ADR-0044) and returned the three additions in Amendment 1. Kept
> because the reasoning is the argument for holding the *next* model ADR the same way, and because it
> records that the hold was not procedural.

This document was held open until the user-facing surface had been thought through, and **not**
because it was waiting in a queue for a signature. The reason was evidence from its own drafting: the
sharpest corrections to it did not come from reading it, they came from asking what using it would be
like.

- *"How will the user know the ID of the scene they deleted?"* overturned orphan retention entirely —
  twice-written, and wrong, because the data was reachable only to someone willing to grep the
  filesystem.
- *"How does a snapshot avoid colliding with the scene it copies?"* produced the whole identity and
  store-layout section, which had no place in the design before it was asked.
- *"Which fields can actually change under a restore?"* narrowed the third drift axis from "the schema
  changed" to value reinterpretation, and retired a detector that would have cried wolf on every
  harmless schema edit.

Three of this ADR's load-bearing decisions arrived that way. That was a strong prior that a surface
pass would turn up more, and every one it found is cheaper now than after implementation. **Approving
it before then would have converted an untested assumption into a decision of record** — the failure
mode this repo has already paid for, where a document sketched something it had not thought through
and a later thread honoured the sketch.

**The prior held.** The pass returned three (Amendment 1), and the most consequential — restore
capturing first — changes what gets *written to disk*, which is exactly the class of finding that
would have been expensive to discover after the backend was built. The hold was worth its cost.

Consequence, per the approval gate: **no snapshot implementation starts until both this and ADR-0044
are approved.**

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
