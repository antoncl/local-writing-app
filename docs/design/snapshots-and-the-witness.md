# Design: Snapshots and the witness

> Status: **DRAFT for review** · Epic: [#395](https://github.com/antoncl/local-writing-app/issues/395) ·
> Milestone: 0.8.0
> Decisions of record: **ADR-0043** (the model) and **ADR-0044** (the surface). This document does
> not supersede either. It is the explanatory layer they deliberately left out: ADR-0043 fixes *that*
> a snapshot carries a witness and never defines *what a witness contains*, and the answer turned out
> to need a page of reasoning rather than a sentence.
> Slices 1 and 2 have shipped ([#401](https://github.com/antoncl/local-writing-app/issues/401),
> [#409](https://github.com/antoncl/local-writing-app/issues/409)). Slice 3 is
> [#439](https://github.com/antoncl/local-writing-app/issues/439), and this document is what it
> should be read alongside.

## 0. What a snapshot is, in one paragraph

A snapshot is a **photograph of a scene's prose, plus a witness of the world that gave that prose its
meaning.** The prose is restored byte-exact. The witness is never restored — it exists so that when
the author goes back to an old version, the app can tell them *what has changed underneath it since*.
That asymmetry is the whole design, and it exists because a fully correct snapshot of a scene is not
constructible: what a scene means depends on markers in other scenes, on manuscript order, on lore
entries composed across an ancestor chain, and on the schema those values are read through. ADR-0043
argues that at length and this document takes it as given.

The consequence worth internalising: **the report is the feature.** If drift reporting is the only
protection an author gets, then a report that cannot name what actually changed has not implemented
the design, however correct the storage is.

## 1. What a witness is

> **Settled by Anton, 2026-07-23.** This section is the answer to the question ADR-0043 left open and
> #439 listed first under "settle before starting".

A witness records the scene's **immediate context** — the entities whose state the prose depends on —
and does not branch out past it.

Three sources, unioned:

1. **Mutations**, including intervals **opened in an earlier scene** and still live at this one.
2. **Lore `entity_ref`s** — the scene's own explicit references.
3. **The dynamic context** — the entities implicitly detected in the prose.

### Why not "markers in this scene's body"

That was the narrowest candidate and it is **refuted by ADR-0043's own motivating example.** Consider
five scenes where scene 2 opens an interval and scene 4 closes it. Scene 3 carries no markers at all,
yet what the world *is* during scene 3 is decided entirely by scenes 2 and 4. Under a body-markers
definition, scene 3's witness is empty — and the first entry in ADR-0043's own test surface ("snapshot
a scene inside an open interval; delete the start marker in an earlier scene; assert the restore
reports the changed field and entity") cannot pass.

The mutation half is therefore defined by resolution, not by syntax:

```
{ e in index.by_entity : effective_state(e, scene_id) != {} }
```

— the entities whose resolved state at this scene differs from base. That set falls out of
`effective_state` rather than introducing a new concept, covers the scene-3 case by construction, and
is bounded by markers in the manuscript rather than by the size of the lore.

### No transitive expansion

The one-hop expansion in `_textual_one_hop` (`backend/app/services/ai/helpers.py`) is prompt-assembly
machinery and is **out**. A witness that follows references out of the entities it found stops being a
record of this scene's context and becomes a record of the project.

## 2. The drift axes

ADR-0043 fixes three. Practice added a fourth.

| # | Axis | What it detects | Detector |
|---|---|---|---|
| 1 | **Mutation drift** | the resolved value of a field changed | recompute `effective_state`, compare |
| 2 | **Inheritance drift** | the entity itself changed | the entity's `revision`, as an **opaque** token |
| 3 | **Value reinterpretation** | the *meaning* of a recorded value changed | type + constraints of **only the fields the witness recorded** |
| 4 | **Membership drift** | the entity is in one version's context and not the other's | set difference over the witnessed set |

### Axis 3 is narrow on purpose

Not "the schema changed". A whole-schema hash fires on every schema edit, including the field
additions and deletions the sparse storage model already absorbs harmlessly — so most reports would
announce a change with no consequence. Under an advisory model, **a detector that cries wolf trains
the dismissal that makes the report worthless on the one occasion it mattered.** Detector precision is
part of the report-quality obligation, not separate from it.

### Axis 4 is new, and it corrects #439's acceptance text

> **Settled by Anton, 2026-07-23**, overruling the line in #439 that said otherwise.

If the snapshot referenced Chicago and the current version does not — or the reverse — **that is
reported.** A character who plays a primary role in one version and is absent or deleted in the other
is exactly the information the author needs, and it is not obtainable from any per-entity comparison,
because the entity is missing from one side.

#439's Acceptance currently says *"An entity absent at capture, or deleted since, is not reported as
changed"*. That is wrong as written and should be struck. **The rule is #439's own text, not
ADR-0043's** — no ADR amendment is required for this.

What survives from the reasoning that produced it (#409's "absence is not a claim") is narrower and
still holds: an entity that never participated in *either* version must not be manufactured into the
report. Membership drift is a claim about the **set** — "this scene no longer references Chicago" —
and needs its own vocabulary, kept distinct from field drift.

## 3. Three ways a lore entry changes — and one that nothing currently detects

> Anton's framing, and the sharpest unresolved point in this document.

An entry can change by **direct edit**, by **delta**, or by **scope visibility**.

- **Direct edit** — caught. `_revision` is a SHA-256 over the entity file's bytes
  (`_revision`, `backend/app/services/project_service.py`).
- **Delta** — caught, but by axis 1 rather than axis 2. Mutations are not edits to the file.
- **Scope visibility** — **caught by neither.** Which layer wins, and whether the entry resolves in
  this scope at all, is a property of the *resolved index* (ADR-0039/0040), not of any file. No hash
  over file bytes can see it.

That third case matters because ADR-0043 rests axis 2 on an argument that does not reach it:

> This makes the feature independent of #314 rather than blocked on it. ADR-0039 requires `revision`
> to become a hash over the ancestor file plus every override in the chain […] so snapshots get the
> more correct detector automatically when #314 lands, with no change here.

A composite `revision` over *files* still cannot detect that a different layer now wins, or that the
entry is no longer visible in this scope. **The witness therefore has to record the resolved source
layer per entity alongside the revision token.** This is a gap in ADR-0043 rather than in the slice,
and it wants an amendment.

## 4. Where the dynamic context comes from

This is the part with the least existing machinery, and the part with a live defect underneath it.

**Today there is no single "dynamic context".** The prose editor scans the scene body for lore names
and tells the author those are the words that will feed the model — and nothing on the backend ever
reads the result. The hits are never sent; chat send scans the *composer message*, and prompt
rendering scans the scene's *summary* field. Filed as
[#447](https://github.com/antoncl/local-writing-app/issues/447), and it must be decided before the
witness can claim to record "the" dynamic context.

For the witness specifically, the resolution is:

- **The frontend owns the matcher.** There must be exactly one implementation of alias matching, and
  it should be the one whose results the author can see underlined. A backend rescan would be cheap
  to write (`_alias_match` already takes arbitrary text) but would mean **two matchers that must
  agree** — a TypeScript regex over a ProseMirror document and a Python regex over raw markdown, with
  word-boundary, casing and effective-name rules implemented twice. Every disagreement between them
  would surface as drift on a scene nobody touched, and the report would have no way to distinguish
  "Chicago left this scene" from "the two matchers tokenise apostrophes differently".
- **The frontend sends the full set on every save, never a delta.** A delta cannot express *Chicago is
  gone*: removal has to be inferred from what is missing, which is precisely the absence-is-not-a-claim
  trap that axis 4 exists to avoid. The payload is 2–3 ids typically, and should carry a structural
  cap rather than trusting that estimate.
- **The set is stored only in the snapshot sidecar.** It is not persisted anywhere else, and it must
  never enter the scene's front matter — it is derived data about an authored file, not part of it.

**If a shared matcher is ever unavoidable, agreement must be a gate rather than a hope**: one
hand-authored fixture corpus, both implementations asserted to return the same ids. Hand-authored
rather than generated — slice 2 shipped fixtures generated from the code they graded, which proved
nothing. Per #435 that gate belongs in the test suite, not as a `gates.yml` step, so it runs on
Windows and cannot be deleted unnoticed.

## 5. The allocation model

> **Settled by Anton, 2026-07-23.** Sits *inside* ADR-0043 Amendment 2's session rule; it does not
> replace it.

Capture is a backend concern — automatic capture fires inside the save, from state the frontend
cannot see — but the dynamic context is a frontend product. Allocation is what joins them.

1. **Allocate at the first dirty save** of an editing session. The allocated snapshot holds the
   **pre-save** bytes, per Amendment 2: what this looked like when the author sat down.
2. **Every autosave carries the current dynamic-context set.** It keeps the backend's working set
   fresh **for the next capture**. It does *not* rewrite an allocated snapshot — see the rule below.
3. **Promotion into the keep-five budget** happens either on an explicit *editing finished* signal
   from the author, or lazily at the **next session boundary** on that scene.

### The governing rule: a witness describes the bytes it accompanies

This is the invariant everything else in this section serves, and it is easy to violate by accident.

The captured body is the state **before this session's first edit**. That is not approximate:
`maybe_capture_session_boundary` runs *before* `_write_scene_file`, so at the moment it fires the file
on disk still holds what the *previous* session last wrote. The new body has not been written yet.
Pinned by `test_the_captured_bytes_are_the_pre_save_state`.

**The witness must therefore be frozen at allocation too.** An earlier draft of this document had
every autosave land its dynamic set in the allocated sidecar, which would leave the body at the start
of the session while the witness drifted to the end of it. That is worse than having no witness: it
would report drift against context the snapshotted prose never had, and it would make the sidecar
mutable after the fact, which ADR-0043's immutability rule forbids for good reason.

### Why the start of the session is the state worth keeping

Because it is the only one the author cannot otherwise reach. Undo covers the current sitting — but
undo is in-memory, per-tab, and bleeds across document switches (#368), so it does not merely stop at
the session boundary, it dies with the tab. **Snapshots are the only durable "before" the app has.**
This is also why capture-on-close was rejected: the end-of-session state duplicates Live at the moment
it is written, so it preserves nothing that is not already on disk.

### The one place body and witness disagree

At allocation the freshest dynamic set available describes the body *about to be written* rather than
the pre-edit body — the author has been typing for up to `AUTO_SAVE_MAX_WAIT_MS` before that first
save lands. Exact agreement would need the backend to retain the previous session's last set across
the gap and across restarts.

Anton's call: **accept the imprecision.** The author may be mid-word on a character name; the error is
bounded by one save rather than by the session, and it is self-correcting. What matters is that this
is now the *only* point of disagreement, rather than a drift that grows with the length of the
sitting.

### Why promotion cannot hang on document close

ADR-0043 Amendment 2 rejected capture-on-close because the close event is the one thing the app cannot
observe: there is no `pagehide`/`beforeunload` handler anywhere in `frontend/src`
([#369](https://github.com/antoncl/local-writing-app/issues/369)), and a crash, force-quit or power
loss fires nothing at all.

**The distinction that matters:** what was rejected is *browser/window close*. An **explicit
editing-finished gesture from the author** is a different thing — author-initiated, therefore
observable — and none of the three rejection reasons reach it. It is a legitimate promotion trigger,
and it should be recorded as such so the ADR's "close was rejected" is not read as covering both.

The next-session-boundary rule is the safety net for when the author never signals, and it is free:
it is the same `maybe_capture_session_boundary` call, at the same call site, on the same mtime check
that already exists. It also bounds the failure mode — each new session promotes the previous
session's allocation before allocating its own, so **at most one un-promoted allocation exists per
scene at any moment**, crash or no crash. A scene edited once and never reopened keeps one allocation
outside the budget, which is harmless.

## 6. Report quality: a floor and a goal

> **Settled by Anton, 2026-07-23**, relaxing #439's Acceptance, which reads as if only the goal is
> acceptable.

- **Floor (must have):** *this entry changed.*
- **Goal (nice to have, cost-dependent):** *Tom's eye colour changed from green to blue.*

Both clear ADR-0043's actual bar, which is about **specificity in the author's vocabulary** rather
than about field-level granularity: the thing it forbids is "context has changed since this snapshot
was taken". Naming the entity is a specific claim. The field-and-values form is better and should be
the target, but it is not the gate.

Since the comparison and its presentation belong to the frontend (§7), the floor-versus-goal choice is
a rendering decision made against data already on the wire, not a backend feature needing its own
justification.

## 7. Where the work sits

**The backend captures. The frontend compares and renders.**

Anton's correction, and it retracts an earlier constraint of his own: the diff was pushed to the
backend out of a worry about performance, but *how to present the delta between a snapshot and the
current state* is a rendering decision. Wording in the author's vocabulary, how much to show at once,
the floor-versus-goal call — none of that belongs in a service method.

The one thing that cannot move: **resolved state must come from the backend, both sides.** The
frontend cannot recompute `effective_state`, revision tokens or source layers. So the route returns
the stored witness plus a freshly computed current one, and the frontend diffs two structures it was
handed. That still satisfies slice 2's hardest-won lesson — *both sides of a comparison must come off
the same pipeline* — because both are produced by the same backend code.

### Cost, measured

The capture cost turned out to have nothing to do with snapshots. `build_mutations_index` was
quadratic — **285 s on a 600-scene manuscript** — because it called `read_scene` per scene and
`read_scene` resolves a computed field that reads the whole structure. Fixed in
[#440](https://github.com/antoncl/local-writing-app/issues/440) / PR #443: **1.16 s** at the same
size.

The witness's own work — the per-entity `effective_state` sweep — is **0.7 ms at 150 entities, flat at
every manuscript size.** So the structural cost bound #439 requires belongs on the index build, not on
the witness set, and the question of *which* entities to record is about precision alone.

## 8. What a witness is not

- **Not a restore point for the world.** Nothing in the witness is ever written back. The resolver must
  never read one.
- **Not authoritative.** It is evidence about the graph, not a participant in it. `snapshots/` is
  excluded from the node index once, at the index.
- **Not a cache.** It is irreplaceable and not rebuildable, which is why it cannot live in `.cache/`
  and why the pre-1.0 "bump the version and rebuild" escape hatch does not apply to it.
- **Not a defence against unsaved work.** A snapshot can only ever witness what reached disk. The
  window between a keystroke and the autosave is #369 and
  [#455](https://github.com/antoncl/local-writing-app/issues/455), upstream of this design entirely.

## 9. Open

1. **#447** — which dynamic context is real. §4 gives the witness a workable answer, but the
   underlying divergence between what the editor promises and what the model receives is undecided.
2. **The scope-visibility gap (§3)** — wants an ADR-0043 amendment, since the ADR currently claims
   axis 2 gets complete for free when #314 lands.
3. **Recording the editing-finished trigger (§5)** — ADR-0043 says close was rejected; it should say
   *which* close.
4. **#439's Acceptance text** — strike the absent/deleted line (§2), recast report quality as
   floor-and-goal (§6).
5. **Where the report surfaces while parked** — ADR-0044 designs the strip without it, and the
   compare view already owns the pane and the A/S/B letter keys. May need an ADR-0044 amendment.
