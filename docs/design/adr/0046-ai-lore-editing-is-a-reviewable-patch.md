# ADR-0046: AI-assisted lore editing is a reviewable per-field patch, not prose revision

- Status: **Accepted** — 2026-07-27 (Anton, PR #576). Framed by him, then his review decisions folded in
  the same day: references are **not** AI-generated, the **client-side diff is a precondition** (#573),
  field definitions are treated uniformly whatever their origin, and **generating a new entry is a create,
  not a diff**. Implementation issues to be filed per slice (§6).
- Amended: **2026-07-28** — §5 now names the proposal's **vehicle** (an ideation *chat* that commits a
  whole-entry patch, with an existing entry optionally in its context) and §6 is re-sliced as increments
  of *patch coverage*, not a per-field ladder. The model in §1–§4 is unchanged; the amendment closes a
  gap where §5–§6 read cold as a one-shot, field-scoped reviser.
- Feature: unfiled — issues to be filed per slice on approval (see §6). This ADR is the architecture
  those issues share.
- Follows: ADR-0043 (scene snapshots — the witness), ADR-0044 (the compare view — the **flip-diff**
  whose `DiffRun` runs and atomic `FieldDiff` flips this ADR reuses as its review surface), the
  metadata schema / class–instance model (`kind:entry_type` → fields), the prompt taxonomy and
  `output.kind` seam (in `default_schema.py`).
- Depends on: **#573 — the diff computed client-side is a precondition** (§3). Its benchmark settles the
  cost question: a faithful TS port of the engine, parity 426/426 against Python, **4–6.8× faster than
  CPython**, largest realistic scene **~1.3 ms** — so the shared diff util lands client-side first and
  this feature builds on it with no server round-trip.

> **Code references.** This ADR describes **roles and behaviours**, not call sites. The concrete
> claims about *current* behaviour were verified against **`6283d0e` (2026-07-27)** and are true of
> that tree only. Symbols are named before locations; a reader arriving later should re-verify before
> acting, and should treat a disagreement with the code as evidence the ADR aged, not that the code is
> wrong.

## Context

We revise **prose** with AI today, but that path is not a diff. A `prompt:revise` entry declares
`output.kind = replace_selection`; the backend streams raw tokens; the frontend
(`AiSuggestionController` in `aiSuggestion.svelte.ts`) deletes the selection, streams the tokens into
the gap behind an `aiSuggestion` TipTap mark, and offers accept/revert. It is a **token replacement
marked in place** — it never computes an old-vs-new diff, and it is fenced to prose scenes.

Separately, the **snapshot compare view** (ADR-0043/0044) *is* a real diff-review. It produces a
`SnapshotDiff` carrying `runs: list[DiffRun]` — provenance-tagged prose fragments (`equal`/`now`/`was`,
warm = now, cool = was) rendered client-side into a tinted "flip" — **and** `fields: dict[str,
FieldDiff]`, where a `FieldDiff` is a deliberately-atomic `{was, now}` pair because "a field value is
atomic, so fields flip rather than interleave" (ADR-0044 §F). The author adopts a region or a field and
the result is written back. That is exactly the two-shape review AI lore editing needs.

A **lore entry is not prose**. It is a Node: an identity triple (`id`/`title`/`entry_type`) plus a
`metadata` dict of **typed fields** — twelve types (`text`, `long_text`, `number`, `boolean`, `select`,
`multi_select`, `entity_ref`, `entity_ref_list`, `tags`, `computed`, `color`, `date`) — plus a markdown
`body`. The `entry_type` (an FQN in a single-inheritance hierarchy, `lore:base` → `lore:character`)
determines which fields are legal; references to other nodes are `entity_ref`/`entity_ref_list` field
values. Entries are saved by a whole-document `PUT /api/lore/{id}` carrying the full `metadata` dict;
values are validated by `_validate_entry_metadata` / `_validate_metadata_field_value`.

Two asks are on the table:

1. **Revise an existing entry** — a patch over its fields (the body and `long_text` text-bearing
   surfaces, which can hold substantial prose, and its structured fields), reviewed as a diff.
2. **Generate** a character or location from a brief.

They share one mechanism wherever there is a *prior* state to compare — editing an existing entry is a
diff-review. Generating a **brand-new** entry has no prior state, so it is a create, not a diff (§1). The
decision is how to model editing so per-field revise and enrichment of an existing entry are one
diff-review, without building a second diff mechanism.

## Decision

### 1. The unit is a **patch** — a proposed entry state — reviewed as a diff, adopted per unit

The AI produces a **proposed entry state**: a set of proposed field values, optionally including the
body.

```
EntryPatch = {
  target_entry_id: string,
  fields: { [field_id]: MetadataValue },   // 0..n proposed field values
  body?: string,                            // optional proposed markdown body
}
```

The patch is **reviewed as a diff against the entry's current state**, and adopted **per unit** — accept
or decline each region and field individually, exactly as the current revision UI does (ADR-0044's
adopt-a-run, #419) — with an **"accept everything" (adopt-all)** gesture to take a whole enrichment at
once. The diff always exposes the individual edits; adopt-all is a shortcut over them, not an opaque
blob. **Per-field revise is a patch of size one; enriching an existing entry is a patch that covers many
of its fields.** Same primitive at N=1 and N=all, so there is one review surface, one adopt path, one
write-back — not a per-field path and a separate enrichment path.

Adopting the accepted units merges them into the entry's current `metadata` (and `body`) and saves via
the existing whole-document `PUT /api/lore/{id}` — the same shape as the snapshot compare's adopt, which
re-projects locally and writes rather than calling a server "apply the diff" endpoint. **The write obeys
inheritance**: for a field whose value is inherited from an ancestor layer, adopting writes an **override
delta** at the active authoring layer L, exactly as manually editing an inherited field does today
(ADR-0042 — the existing layered save via `authoring_layer_id` / `clear_override_fields`). No new
mutation endpoint and no new write path: the patch is assembled client-side and written through the door
that exists.

**A brand-new entry is a create, not a diff.** It has no current state to compare against, so nothing
flips: the generated entry is reviewed as a whole proposed entry — accept or discard, then edit normally
— and created through the existing create path. Only *editing* an existing entry (revise a field, enrich
a sparse one) uses the proposed-vs-current diff-review that the rest of this ADR describes.

### 2. The review **reuses the snapshot compare's two diff shapes** — this is the whole point

The proposed-vs-current diff dispatches by field type onto the **shapes ADR-0044 already defines and
renders**:

- **Text-shaped units — `body` and `long_text`** → a **`DiffRun` prose run-diff**, rendered by the
  existing flip renderer (`renderDiffRuns` / `groupRuns` in `diffRuns.ts`), adopted region-by-region as
  in ADR-0044's "adopt a run" gesture (#419).
- **Structured units — `select`, `multi_select`, `number`, `boolean`, `tags`, `color`, `date`** → an
  **atomic `FieldDiff` flip** (`{was, now}`), rendered with the flip UX, adopted whole. There is no prose
  to run-diff on a `select`, which is exactly why `FieldDiff` is atomic — the same reason it is atomic for
  snapshots. (`entity_ref` / `entity_ref_list` are not AI-proposed at all — §4.)

A `long_text` field can hold substantial prose (a multi-paragraph description), so **there is no material
difference between a `long_text` field and the body**: both take the full `DiffRun` run-diff with
region-level accept/decline, not a whole-field replace. **Fields dispatch by type alone**: a field from
the built-in schema and one a user added to their `metadata.schema.yaml` are indistinguishable here, as
they are everywhere else — the layered schema merges both uniformly.

So AI lore editing invents **no new renderer**. It reuses `DiffRun` for prose and `FieldDiff` for
structured fields — the two shapes and the flip review already shipped for snapshot compare. The one
piece of new work on the review is that snapshot compare diffs *snapshot-vs-live*, whereas this diffs
*AI-proposed-vs-current entry*, and its field diff must cover **authored lore-entry metadata**, not just
a scene's own front matter (`_field_diffs`) — an adjacent extension of the same shape, not a new one.

### 3. The diff is computed **client-side** — #573 is a precondition

ADR-0044 computes its diff **server-side** (`snapshot_diff.py`); #573 shows that was a premature
optimization — a faithful TS port is **4–6.8× faster than CPython** and sub-few-ms on a 4000-word scene,
before the round-trip the server path also pays. So this feature **depends on the client-side diff util
from #573 landing first**: a shared module emitting the same `DiffRun` / `FieldDiff` shapes, consumed by
both snapshot compare and AI lore editing, computing nothing on the server. Making it a precondition is
what keeps this to **one** diff mechanism rather than adding a second server call for lore. (The AI path
needs no drift — the one genuinely server-bound part of snapshot compare — so it is pure-client anyway.)

### 4. Structured proposals are **constrained output validated against the schema**

A token stream cannot be trusted to say `status: married`. An entry_type's resolved field list — with
each field's type, `options`, and `picker_config` — **is a JSON Schema**. Structured patches are
produced as constrained JSON / tool-use shaped by that schema and validated on return by the
**existing** `_validate_entry_metadata` / `_validate_metadata_field_value`, which give per-field errors.
The backend gains a validate-a-structured-AI-result role built from validators that already exist. A
field the model cannot fill legally is simply absent from the patch, not a bad write. **References are
excluded**: the model does not propose `entity_ref` / `entity_ref_list` values — there is no realistic
way for it to pick the right existing node id, so linking entries stays a manual author gesture.

### 5. The proposal comes from an ideation **chat**; the commit is a final patch, not a streamed mark

The proposal is the product of an **ideation chat** — the app's core use of AI as a tool for
brainstorming, a back-and-forth that develops an idea, *not* a one-shot generate. It runs in the chat
vehicle the app already has (chat is a Node kind — no new conversation subsystem), and an existing entry
is optionally carried in its context. What the conversation converges on and **commits** is the
whole-entry patch of §1. The target is always the **entry**, never a lone field: a patch of size one is
still a patch over the entry (§1's N=1 case), so there is no field-scoped reviser here — the coverage of
the patch varies (§6), the unit does not.

The prompt that drives the commit is a **specialization of the existing `revise` kind** — a sub-type
whose target is a lore entry and whose `output.kind` is the patch/diff above — **not a fifth prompt
base**. The four-base taxonomy is deliberate, and a new thing earns its own base only when it cannot be
expressed as a sub-type; this can (cf. `roleplay` as a sub-type of continuation).

**What is not streamed is the commit, not the conversation.** The brainstorm streams like any chat; but
the entry is never written by streamed tokens. When the conversation commits, the model returns a
**final** proposed state and the diff is computed over it. The scene `aiSuggestion` streaming mark — a
marked token replacement with no computed diff and no field renderer — is a **different** path and is
**not** extended to lore. The flip-diff already gives us both halves (prose runs and field flips) that
the mark lacks; writing an entry is adopting a reviewed patch, not accepting streamed tokens in place.

### 6. Slicing — the diff util first, then grow what one brainstorm-committed patch covers

Every slice below delivers the **same** vehicle: an ideation chat (§5) that commits a whole-entry patch,
reviewed and written through the one path (§1). The slices are **not a per-field ladder** — they grow
*what the patch covers* and whether there is a prior state to diff against. The unit is always the entry.
Each slice states the **user journey that is its definition of done** and the **adjacent wrong path it is
not**. This is deliberate anti-drift scaffolding: a cold reader who cannot produce the journey, or who
finds themselves building the "*Not*", has veered — the labels alone underdetermine the intent, and the
journey + anti-goal are what pin it.

0. **The client-side diff util (#573).** *(shipped.)* The shared `DiffRun` / `FieldDiff` compute lands
   client-side — the faithful port is most of it — the precondition every slice below builds on.
1. **The review surface — proposed-vs-current on one prose surface.** *(shipped.)* Diff a proposed body
   against the current value and review it with the existing flip renderer + adopt — the review-and-write
   surface every later slice reuses, proven on the shape we already ship.
   - *Not:* a step toward a field-scoped reviser, and no user-facing trigger — this slice is the tested
     seam only (its proposed body is a fixture standing in for a model).
2. **The brainstorm, revising an existing entry's prose.** An ideation chat (§5) carrying an existing
   entry as context converges on a patch over that entry's prose surfaces (the body and the text-bearing
   fields); the commit is reviewed with slice 1's flip and written back via `PUT`. The first product
   slice — the whole point at minimum coverage.
   - *Done when:* the author opens a chat, brainstorms changes to an existing entry that rides in the
     context, commits, sees the proposed-vs-current flip over that entry's prose, adopts what they want,
     and the entry is saved.
   - *Not:* a "revise this field" button or menu on a field. The trigger is the brainstorm, not the
     field; a patch that happens to touch one field is still a patch over the entry (§1's N=1 case).
3. **Grow the patch to structured fields.** Extend the `FieldDiff` flip to authored lore metadata + the
   constrained-JSON output path + schema validation (§4). The same brainstorm now covers
   `select`/`tags`/`number`/`boolean`/`date`/`color` too.
   - *Done when:* the same brainstorm-and-commit also proposes structured field values, each reviewed as
     an atomic flip and validated; an illegal value is dropped per-field, not written, without failing
     the whole patch.
   - *Not:* proposing `entity_ref`/`entity_ref_list` links or `computed` values (both stay out, §4), and
     not a second proposal path — it is the same commit with wider coverage.
4. **The new-entry outcome — no prior state, so no diff.** The same brainstorm with **no** entry in its
   context commits a whole new entry, reviewed whole (§1) and created through the existing create path.
   The "brainstorm a character" ask.
   - *Done when:* the author brainstorms a character from scratch, commits, reviews the whole proposed
     entry (no flip — nothing to diff against), and it is created.
   - *Not:* a diff/flip review (there is no prior state), and not a separate generator mechanism — same
     vehicle, the create branch of the same patch.

The commitment that must hold from slice 1: the patch shape (§1) and the reuse of `DiffRun`/`FieldDiff`
(§2), both resting on the client-side diff util from slice 0.

## Why / rejected alternatives

- **Extend the client `aiSuggestion` streaming mark to lore.** This was the first draft's mechanism and
  it is wrong: the mark is a token replacement with **no computed diff and no structured-field
  renderer**, so it covers neither the "flip" review nor any non-prose field. The snapshot flip-diff
  already provides both, server- or client-computed. Rejected — reuse the diff-review, not the mark.
- **Entrench the server-side diff as a dependency.** Would build this feature on exactly the call #573
  reconsiders, and add a second server round-trip for lore. §3 makes the client-side diff a precondition
  instead. Rejected.
- **Let the AI propose references.** There is no reliable way for a model to name the correct existing
  node id, and a wrong `entity_ref` is a silent mis-link. Linking stays a manual author gesture (§4).
  Rejected.
- **Generate a whole-entry text blob and parse it into fields.** No schema guarantee; collapses the
  moment a `select` is out of range or an `entity_ref` names a missing node. §4 exists to avoid this.
  Rejected.
- **Two mechanisms — a per-field reviser and a separate whole-entry generator.** They review the same
  thing and would drift. §1 makes generation the N=all case of the per-field primitive. Rejected.
- **N independent model calls, one per field, for generation.** No cross-field coherence — three calls
  that never saw each other read like three characters. A patch is one call with the whole entry in
  view. Rejected.
- **A new per-field lore mutation endpoint to apply accepted units.** The whole-document `PUT
  /api/lore/{id}` already saves intentfully; adopt assembles client-side and writes through it, as
  snapshot adopt does. Rejected.

## Consequences

- AI lore editing reuses the snapshot compare's `DiffRun`/`FieldDiff` shapes and flip review — **no new
  diff renderer**. The one new review piece is diffing *proposed-vs-current entry* (vs *snapshot-vs-live*)
  and extending the field diff to authored lore metadata.
- The client-side diff util (§3) gains a second caller — the proposed-vs-current case — so it should be
  factored so "what are the two sides" is a parameter, not snapshot-specific.
- Adopting an edit to an **inherited** field writes an override delta at the active layer (ADR-0042's
  layered save), so AI edits obey the hierarchy exactly as manual edits do — no new write path.
- The backend gains a validate-a-structured-AI-result role, built from the existing entry validators.
- Every AI lore edit — one field or a whole generated character — flows through **one** review-and-write
  path. New field types get AI-editability once the diff dispatch knows their `FieldDiff` render.
- `computed` fields are never proposed (they reject stored values by definition); the patch assembler
  excludes them.

## Non-goals

- **AI-proposed references** — the model does not generate `entity_ref` / `entity_ref_list` values;
  linking entries stays a manual author gesture (§4).
- **New-entry generation as a diff** — creating a brand-new entry has no prior state, so it is reviewed
  whole, not flipped (§1). It reuses §4's proposal machinery but not the diff-review.
- **The snapshot-compare migration** — whether and how #573 rewrites the shipped 0.8.0 server diff is
  #573's scope; this ADR only *consumes* the client util it produces.
- **Cross-entry / graph-aware editing** — consistency checks across entries, gap detection, proposing a
  **time-aware scene mutation** instead of a permanent field change. All reuse this patch/diff primitive,
  but are later work.
- **Scene prose** — unchanged; this ADR is about the lore entry as structured data.

## Open — to settle at implementation

- The **visual layout** of a full-entry review — the body run-diff in the editor, the field flips in the
  rail, under one "accept everything" — is deferred to implementation (0005's lesson). The gesture set is
  decided (§1): per-unit accept/decline plus adopt-all. The diff's "current" side shows the **effective**
  value the author sees, and adopting an inherited field writes an override delta at L (§1).

## Test surface

- Round-trip: a patch adopted and PUT re-reads byte-identically to hand-editing the same fields.
- Validation: a structured proposal with an out-of-range `select` (or any schema-invalid value) is
  dropped per-field, not written, and does not fail the whole patch.
- Reuse: a proposed body renders through the same `DiffRun` flip as a snapshot compare.
- Dispatch: a mixed patch (a `long_text` field + a `select` field) reviews the first as a run-diff and
  the second as an atomic `FieldDiff` flip.
- New entry: a generated new entry is presented whole (no flip) and, on accept, created through the
  existing create path.
- Inheritance: adopting an edit to a field inherited from an ancestor layer writes an override delta at
  the active layer L (not a flat value), and clear-to-inherit still works afterward (ADR-0042).
