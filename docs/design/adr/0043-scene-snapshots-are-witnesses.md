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

**Drift on the inheritance axis is detected by the composite revision from #314.** ADR-0039 already
requires `revision` to become a hash over the ancestor file plus every override in the chain. That is
precisely the "has this composed value changed?" primitive the witness needs, so the snapshot stores it
per influencing entity and the drift check is a recompute-and-compare rather than a re-resolution.
This is a reason to want #314 landed first, not merely a reason to avoid conflicting with it.

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
Scrivener. Automatic snapshots are thinned by a retention policy; explicit ones are named and kept
until deleted. The explicit control alone is insufficient because the feature is worth most precisely
when the author forgot to press it; the automatic capture alone is insufficient because only the author
knows which state was worth marking.

**Restore replaces the scene body and reports drift.** It does not touch the mutation records in other
scenes, the manuscript order, the lore entries, or any ancestor layer.

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

## Test surface

The value of the witness framing is that the feature's correctness criterion becomes testable.
"Did we restore the world correctly" admits no test. "Did we accurately report the drift" does:

- Snapshot a scene inside an open interval; delete the start marker in an earlier scene; assert the
  restore reports the changed field and entity.
- Snapshot a scene; reorder the manuscript so the interval no longer spans it; assert the drift is
  reported.
- Snapshot a scene; edit the entry at an ancestor layer; assert the composite-revision comparison
  reports it.
- Snapshot, change nothing, restore; assert no drift is reported and the body is byte-identical.
- Assert the resolver never reads a witness record.

## Naming

**"Snapshot"** is chosen: it is Scrivener's term, so it is the word authors already have, and it
promises a photograph rather than a time machine — which is exactly the contract above. It avoids both
live collisions (`revision`, "time travel").

Disclosure, since the term is not unused: `snapshot` appears in roughly eighteen files as an
implementation noun (AI session state, workspace layout, collapse state) and, more significantly, as
ADR-0040's `.cache/` node-index snapshot (#306) — a real domain noun in the same repo. None are
user-facing. If that overlap is judged too close, the alternative is to name the feature for what it
holds rather than what it does.

## Open questions

1. **Is drift reporting blocking or advisory on restore?** Whether a restore into drifted context
   requires explicit acknowledgement, or merely shows the report and proceeds. A judgement about how
   much friction the safety is worth.
2. **Does this wait on #314, or is it designed now and built after?** The composite revision is the
   detector for the inheritance axis. Designing now and building after 0.7.0 closes appears correct,
   but the sequencing is a release-planning call.
