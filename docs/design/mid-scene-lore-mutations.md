# Design: Mid-scene lore mutations

> Status: **DRAFT for review (v3 — review round incorporated, verified against code)** · Issue: [#33](https://github.com/antoncl/local-writing-app/issues/33) · Milestone: 0.4.0
> Seed: `memory/decisions_mutable_metadata.md`. Decisions here supersede the memo where they differ.
> This revision supersedes the v1 draft after the 0.4.0 planning thread: the `mutable`
> flag is gone, resolution is position-granular, and the stack/frame model is replaced by
> independent intervals. v3 folds in the review round — the resolver seam, validation, and
> implicit-context coverage are now verified against the current pipeline. See §9 (resolved
> questions) and §10 (ADR set).

## 1. Problem & goal

The real problem is **information leakage from the future into the past**. When a prose
generation flounders it builds on everything the model "knows" about the story, and what
it knows includes events that, in manuscript time, haven't happened yet. The feature's job
is therefore **redaction**: give any generation only what is knowable *at its point in the
manuscript*.

Some of that knowable state changes over manuscript time — a character's rank, ship
assignment, marital status; a location's ownership; what a detective has deduced so far. A
lore entry today stores a single "current" value, which is the wrong AI context for any
*earlier* scene: Chapter 1 should see Commodore-Honor, Chapter 10 Captain-Honor, with no
manual syncing — and Chapter 3 must never see that Chapter 12 knows it was the butler.

**Goal:** a writer records a change at the point in the prose where it happens; every
lore-reading path used for generation resolves the **effective value for the calling
(scene, position)** automatically.

**Acceptance (from #33):** add `<!-- mutate: honor.rank = "Captain" -->` in Scene 5;
Scene 1's Roleplay preview sees Commodore, Scene 10's sees Captain — with no `mutable`
declaration step first.

## 2. Core semantics (read first — this is the load-bearing part)

### 2.1 Every mutation is an independent interval
A mutation is **not** grouped into a frame or a stack. It is a self-standing record with:

- a **start** — its marker position in manuscript+prose order,
- an **optional end** — another marker that closes *this specific* mutation (absent = runs
  to end of book),
- a **combine rule** — *replace* a scalar field (latest-started-live wins) or *add* to a
  collection field (union of live records),
- an **identity** — so an end / edit / delete can address exactly one record.

**Why not a stack/frame** (this is the decision that shaped the model, ADR-0002): a frame
conflates *co-occurring in time* with *sharing a lifetime*. Counterexample: a detective who
is also a werewolf learns a clue while transformed. The transformation ends at dawn; the
clue is forever. Any model where lifetime belongs to a *group* would pop the clue with the
transformation. Lifetime belongs to each individual change, so the primitive is one
independent record — smaller than a stack, not bigger.

### 2.2 Resolution is cumulative, in manuscript order, position-granular
```
effective(entity, scene_T, pos_P) =
    for each field:  latest-started record whose interval is LIVE at (scene_T, pos_P)     # replace
    plus:            union of all live additive records                                    # additive
```
- **Live at (scene_T, pos_P)** = the record's start is at or before that point in manuscript
  order (act → chapter → scene, then prose position within the scene), and its end (if any)
  is strictly after it.
- **Base state falls into the same shape**: the lore file's stored values are open-ended
  *replace* records starting at book-start; a later `rank = Captain` simply shadows
  `rank = Commodore` by start-order, no explicit close needed.
- **Position-granular** (ADR-0003): resolution takes a position, not just a scene. Only
  `replace_selection` has a real cursor, so in v1 only it passes a live offset; all other
  surfaces (`append_to_body`, roleplay, preview, timeline) resolve at **end-of-scene** —
  which is their natural position, not a compromise. A record's marker location in the prose
  is therefore meaningful: prose before it sees the old value, prose after it the new.

### 2.3 The interval shapes, by use case
| Use case | Combine | Interval | Notes |
|---|---|---|---|
| Rank / name change / broken leg | replace | open-ended | the #33 case; shadowed by the next same-field record |
| Werewolf transform | replace (multi-field) | `[dusk, dawn)` | several independent records, co-authored, closed together at dawn |
| Clue accumulated (detective) | additive | open-ended | permanent knowledge |
| Red herring / retracted testimony | additive | closed **out of order** | closing one record while others stand — this is what *forces* per-record identity |
| Scene / sequence sub-goal | additive (or replace) | scoped to the scene/sequence | bounded override, does not propagate past its scope |

## 3. Data model & on-disk storage

### 3.1 No `mutable` flag — every field is mutable
The v1 draft's `mutable: bool` on `MetadataFieldDefinition` is **dropped**. Requiring a
schema edit before recording a change is a context-switch out of creative flow into admin,
so it would not get used. Every field can carry mutations; almost none ever will. The
`/mutate` autocomplete listing *all* of an entity's fields is the discovery surface — no
schema ceremony, no validation of a flag.

### 3.2 Marker = self-contained scene-body HTML comment (Model A, ADR-0001)
The value lives **in the marker, in the scene body, at the point of change** — not in a
central pointer table.

```
<!-- mutate:entity=<lore-id>;field=<field-key>;value=<url-encoded>;id=<marker-id> -->
```

- **Scene authoritative.** Everything reconstructs from lore files + scenes; the marker
  travels with the prose, so moving a scene moves its mutations and deleting a scene deletes
  them — no orphan management, no second source of truth. This is the decisive reason over a
  pointer model (B): position is semantically meaningful and position lives where the prose
  is, so the data must too.
- **`entity`** is the lore entry **id** (canonical identity, not title/filename). **`field`**
  is the field key. **`value`** is url-encoded (survives markdown round-trip; matches the
  todo `note` encoding).
- **Identity: reuse the embedded-todo id scheme — the marker id is minted client-side at
  insertion** (ADR-0002). Verified against the code: the backend scan expects the `id` already
  present in the marker, and `PATCH`/`DELETE` rewrite it in place — `save_scene` does not mint
  ids. So `/mutate` mints the id when it inserts the marker and an ordinary scene save carries
  it; **no create route**. Deriving the id from `(entity, field, offset)` instead is fragile —
  offsets shift as prose is edited and two mutations of one field in a scene collide; v1.0 needs
  stable ids for edit/delete and v1.1 close *references* an id, which settles it.
- **Forward-compatible grammar.** v1.0 markers are "set a scalar" (op implicit). Later
  additions are purely additive to the grammar, leaving v1.0 markers untouched:
  - additive → an `op=add` (v1.1 also `op=remove`; see the v1.1 doc §1);
  - close → a separate close-marker referencing an `id` (v1.1 doc §2);
  - naming → an optional `name=` label (+ `group=` for co-authored sets), a label not a frame (v1.1 doc §6);
  - per-knower → an optional `knower=<lore-id>` scope.

### 3.3 Performance & the index
Displaying a lore card must not scan all scenes. A derived `mutations_by_entity` index lives
in `.cache/` (rebuildable, fits the project's cache rule), rebuilt on scene save. Card
display and the time-slider read a **pre-ordered per-entity slice** — O(applicable
mutations), not a re-scan. A full scan happens only on a cold rebuild, the same class as
every other index in the app. Start with **one project-wide index**; move to per-entity-lazy
only if a large manuscript makes save-time rebuild measurably slow.

### 3.4 Validation — a mutation value is a field value
A `/mutate rank = "Captain"` value must satisfy the target field's constraints exactly as a
base value does (a `select` value in options, an `entity_ref` pointing to a real entity, a
number parsing, …). This reuses `_validate_metadata_field_value()`
(`services/project/metadata_values.py:174`) — the same validator base values already run through
on save. Two wiring points:
- **`save_scene()`** (`services/project/manuscript.py:361`) — the marker scan (which also builds
  the index) validates each mutation value before persisting; a bad value is rejected/flagged
  like any invalid metadata.
- **`validate_project()`** (`services/project/lifecycle.py:239`) — add a scene-mutation scan
  loop mirroring its existing lore/scene walks, so project-wide validation covers markers.

The scan that feeds the index is the natural hook for both — one walk, index + validation.

## 4. Backend

### 4.1 New mixin — `LoreMutationsMixin` (`services/project/lore_mutations.py`)
Cohesive slice composed onto `ProjectService` via MRO, alongside `EmbeddedTodosMixin`, whose
scan/rewrite machinery it mirrors (module regex → `_scan_*` generator → capture-group
substitution callback for atomic single-marker edits via `_write_scene_file()`).

- `_scan_scene_mutations(scene) -> Iterable[MutationMarker]` — regex-walk one body, carrying
  each marker's prose offset (needed for position-granular).
- `build_mutations_index() -> MutationsByEntity` — walk all scenes **in manuscript order**
  (from `read_structure()`), producing per-entity records ordered by `(manuscript-position,
  prose-offset)`. Rebuildable cache; rebuilt on scene save.
- `effective_state(entity_id, scene_id, position=END_OF_SCENE) -> dict[field, value]` — the
  resolver in §2. Slices the pre-ordered per-entity list at `(scene, position)`; O(applicable).
- `add_mutation` / `update_mutation` / `delete_mutation(scene_id, marker_id)` — intentful
  writers using the rewrite-callback pattern; return the updated `Scene` and flush the index.
  Data-loss surface is identical to embedded-todos — reuse `flushSceneIfDirty` +
  `reconcileSceneFromServer` on the frontend.

### 4.2 Integration point (verified against the pipeline)
Effective state is a function of **(entity, scene, position)**, so it resolves in the
**scene-aware context path**, not the generic entry reader. The code trace changes where we
plug in:

- **The single field-value choke-point is `_format_lore_block()`** (`services/ai/helpers.py:772`),
  where every lore entry's fields are read and rendered to the `<lore>…</lore>` XML block. It is
  called from **both** context paths: explicit/one-shot via `_relevant_lore()` (`:555`), and the
  **implicit-context chat path** — where `context_expander.py` scans the user message, appends
  detected entity **ids** (not values) to the append-only session journal, and the journal is
  formatted via `_format_lore_block()` at send (`main.py:1237`). Because the journal carries only
  ids, resolving effective state *at the block formatter* covers explicit **and** implicit
  injection in one place. This is exactly the mutable-metadata dependency the implicit-context
  design parked as a V2 follow-up ([[decisions-implicit-context]]).
- **So: make the block formatter scene+position-aware** — thread `(scene, position)` into
  `_format_lore_block`, resolving each entry's mutable fields via `effective_state(entity, scene,
  position)` as it formats. `_relevant_lore` passes the calling scene; v1 threads a live position
  only from `replace_selection` (end-of-scene elsewhere).
- **Correction to an earlier assumption:** lore is *pre-baked to an XML string*, not read field
  by field in templates — so this is a pre-bake inside the scene-aware formatter, **not** a new
  template-time field accessor. (The `entry()`/`pov()`/`character_thread()` EntryRef helpers can
  expose entry attributes; `pov`/`character_thread` are already scene-aware, so if they surface
  mutable fields they take the same resolver — otherwise they read base. Flag at implementation.)
- **Chat needs a resolution scene.** A chat session isn't always at a scene, so the implicit path
  needs a scene to resolve against — supplied by the roleplay **scene picker** (§6), defaulting to
  the session's current scene.
- **Template query access — both base and effective.** Beyond the auto-resolved `<lore>` block,
  a template can ask for a specific field explicitly, in *both* forms: its **initial/book (base)**
  value and its **effective** value at a scene. Expose as helpers `base(entity, field)` (reads the
  lore file) and `effective(entity, field, scene[, position])` (runs the resolver) — or the
  equivalent on the EntryRef (`entry('honor').base.rank` vs a scene-resolved accessor). The
  auto-resolved block uses `effective` at the calling scene; the base accessor lets an author show
  "then vs. now." Both are pure reads over the resolver + base state; no new storage.
- `read_lore_entry()` (`services/project/lore.py:89`) keeps returning **base** state — the lore
  *page* shows base + the timeline/slider (§5.3). Do **not** inject effective values there.

**Cache coherence (do not miss this):** effective state depends on mutation markers that live in
**scene** files, so a lore entry's file-revision no longer captures its effective value — the
revision-based stable/volatile partitioning in `sessions.py` would treat a mutable entry as
"stable" while its resolved value changes scene to scene. Mutable-field resolved values must go in
the **volatile** partition, or the cache key must include the mutations-index version + the
resolution scene. (Ties back to §3.3 — the index carries a version the cache can read.)

### 4.3 API
- `GET /api/lore/{entity_id}/mutations` — the timeline for the lore page (all records for an
  entity, ordered by manuscript position, each with originating scene id/title + field).
- `GET /api/lore/{entity_id}/effective?scene={id}[&pos={offset}]` — effective state for the
  time-slider (drives the card re-render at a scrub point).
- Authoring goes through the **scene** (markers live in scene bodies), reusing the scene-todo
  route shape:
  - `PATCH /api/scenes/{scene_id}/mutations/{marker_id}`
  - `DELETE /api/scenes/{scene_id}/mutations/{marker_id}`
  - insertion is an ordinary scene save — the client mints the marker id (§3.2), so no create
    route.

### 4.4 Mutable names and the implicit-context matcher
Most field mutations only change *resolved values* (cheap, resolver-time). But **name / title /
alias** fields are also the strings the implicit-context matcher ([[decisions-implicit-context]])
compiles into its regex-OR / automaton to auto-inject mentioned entities. If those fields are
mutable the matchable set is **not constant over manuscript time**: a "John" who legally becomes
"Jonathan" at scene 50 must be detected as "John" before and "Jonathan" after.

So the matcher must be **effective-name-aware**. Only matchable-field mutations change the set, so
they partition the manuscript into at most **N+1 segments** (N = count of name/title/alias
mutations — rare), each with a constant name-set. Two designs:
- **Per-segment matchers (precise):** one compiled matcher per segment (compile is <5ms even at
  10k patterns, and compile-rare), keyed on the mutations-index version; scan each scene with its
  segment's matcher. Correct even when a name is reused by a different entity in a different span.
- **Union matcher + post-filter (simple):** compile once over *every* name-form any entity ever
  has; on a hit, keep it only if that form is effective at the scene. One compile, but over-matches
  on cross-era name collisions.

Recommendation: **per-segment** (N is small and it's correct). Applies to **both** the backend
send-time scan and the frontend per-keystroke highlight matcher. Non-name field mutations never
touch the matcher.

**Scope:** this is the one place mutable metadata reaches past value-resolution into the detection
layer. Since implicit context's send-time pipeline is itself only partly built, treat
matcher-segmentation as **v1.1+**; v1.0 may compile from base names only (a renamed entity just
isn't auto-injected under its new name yet) and note the limitation. (ADR-0008.)

## 5. Frontend

The editor cluster needs **no preparatory refactor** (verified against the current tree):
NodeEditor (1308 LOC) routes body views + owns the metadata/backlinks rail; ProseBodyView
(1335) owns TipTap + already-extracted marks/slash infra; MetadataPanel (591) and
BacklinksPanel (121) are thin and clean. The feature composes in.

### 5.1 TipTap mark — `MutationMark` + detail box (`lib/editor-core/proseMarks.ts`)
A compact inline pill alone is not enough — the writer must be able to see *exactly* what is
being mutated. So it's a **combo**: a small **inline pill** that marks the position and keeps the
prose readable, plus a **detail box** on hover/click (news-article-callout style) showing
**entity · field · old → new value · scope**. Add a factory
`createMutationMark({ entityTitleForId, fieldLabelForId })` mirroring `createCharacterMark`
(`:46`) — resolver closures so the pill reads "Honor → Captain" with live lore/schema lookups.
Attributes `data-mutation-entity/-field/-value`; `renderHTML` emits `<span class="mutation-pill">`.
Built in ProseBodyView `onMount`, added to the extensions array (same wiring as CharacterMark).
The hover/click detail box reuses the Floating-UI popover pattern already used for the
implicit-context hover preview. Scoped styles in ProseBodyView's `<style>`, visually distinct from
entity-ref and TODO pills — the pill *is* the "the change happens here" visual, so it sits in the
text flow (not a margin note).

### 5.2 `/mutate` slash command — **plural fields**
Register in `getSlashCommands()` (`ProseBodyView.svelte:445`). A single gesture sets **one or
more** fields (a promotion = rank + title + uniform; a werewolf transform = appearance +
abilities + name), producing **N independent markers** (co-authored, independent lifetimes —
§2.1). Flow: pick entity (lore store) → pick field(s) → enter each value using **that field
type's own input widget** (per `decisions_inputs_fields_uniformity`) → insert marker(s) +
mark(s) at the cursor. The co-authored set may carry a soft group label (create-together,
later close-together at dawn) — a UI convenience, **not** a semantic frame. Reuses the
existing entity-lookup infra that `implicitContextHighlight.ts` uses.

### 5.3 Lore-page effective-state view — list + time-slider
New `MutationTimeline` component composed into the rail (alongside MetadataPanel /
BacklinksPanel). Two views of one ordered dataset:

- **The list** mirrors `BacklinksPanel` exactly — a `NodeRow` group header with a count pill
  + a `NodeList` (tree mode) of per-mutation rows (field · value · originating scene); click a
  row to navigate to the scene. Read-only here (editing lives in the prose, per ADR-0006).
- **The time-slider** is the trust surface: its stops are the entity's ordered mutation points
  (from the index); scrubbing recomputes effective state at that `(scene, position)`
  (`GET …/effective`) and re-renders the card, so the writer can *see* "Honor as of Scene 5"
  and trust the redaction. Clicking a list row moves the slider to that point. v1.0 ships a
  minimal stepped scrubber; polish (drag, per-field diff highlight) is later.

Note: lore renders today via ProseBodyView (`body_shape: "prose"`) with the metadata rail;
`FieldsOnlyView` (17-LOC stub) covers `body_shape: "none"`. The `MutationTimeline` lives in
the rail so it applies regardless of body shape.

## 6. AI verification — a scene picker on the roleplay prompt (NOT a new prompt)
Do **not** seed a `character_query` prompt. `decisions_prompt_model` explicitly de-seeded it —
it's "a general roleplay sub-type" a user makes, and the catalog is kept deliberately small
(prompt count grows until you forget what each one does). Instead, add an **optional scene-picker
input** to the existing general/roleplay prompt: it selects which scene's effective state to
roleplay at (defaults to the current scene), so the writer can interrogate the timeline ("what's
your rank?" as of scene 5 vs scene 10). This adds zero prompts, and the same picker supplies the
**resolution scene for the chat/implicit path** (§4.2). Verification therefore rides for free on
the resolver; it's a v1.1 polish only because interrogating *closed* intervals is most
interesting once close exists.

## 7. Reduction check (what is genuinely new vs. reused)
| Piece | Reuses | New? |
|---|---|---|
| Marker scan / atomic rewrite | `EmbeddedTodosMixin` pattern | no |
| Marker identity | embedded-todo id scheme | no |
| Resolver injection | `_relevant_lore(scene, position)` seam | **yes — the resolver** |
| `mutations_by_entity` index | `.cache/` rebuildable-index pattern | yes (small) |
| Editor pill | `createCharacterMark` / `TodoAnchor` | no |
| `/mutate` command | `getSlashCommands()` | no |
| Timeline list | `BacklinksPanel` → `NodeList`/`NodeRow` | no |
| Time-slider | — | yes (small widget) |
| Mutation-value validation | `_validate_metadata_field_value` | no |
| Verification | scene picker on existing roleplay prompt | no (no new prompt) |

Genuinely new: the **resolver**, its **index**, and a small **slider** widget. Everything else
is composition over shipped patterns — evidence the feature does not warrant a new subsystem.

## 8. Scope & boundary
**v1.0 — the spine (proves the whole architecture against #33):**
- Independent-interval resolver + one project-wide index, at the `_relevant_lore(scene,
  position)` seam (position live only for `replace_selection`; end-of-scene elsewhere).
- **Replace, open-ended only** — rank/name/broken-leg.
- Every field mutable (no flag); base = open-ended records at book-start.
- `/mutate` (plural fields) + `MutationMark` pill + detail box + the lore-card **list + minimal
  time-slider** — the slider is in v1.0 to prove the UI paradigm is feasible (not for correctness
  verification).

**v1.1 — richer combine & lifetime (the cases that drove the design):**
> Now specified in its own doc: [`mid-scene-lore-mutations-v1.1.md`](./mid-scene-lore-mutations-v1.1.md)
> (covers #58–62; the time-sensitive lore entry #63/#64 is a separate design pass). The forward-compat
> grammar hooks in §3.2 are resolved there (`op=add`/`op=remove`, the close-marker).
- **Additive** (accumulation) — clue accumulation. **Field type gates it**: where accumulation
  is meaningless (e.g. boolean) it's replace-only; where it makes sense, a **per-mutation toggle**
  (replace vs. add) lets the writer choose at authoring time (not a global setting, not pure
  type-inference). Required for the feature to be complete; phased here only to keep v1.0 lean.
- **Interval close** (end + close-by-identity, incl. out-of-order retraction) — werewolf
  revert, red-herring, scene/sequence-scoped sub-goals.
- Roleplay **scene-picker** verification (§6); **reusable transformation sets** (a saved
  plural-field bundle re-applied for recurring werewolf — DRY at authoring time over inline
  Model-A markers).

**v2+ (post-v1.1):**
- **Per-knower / perspectival knowledge** — Peter knowing X must not imply Alice knows X. The
  grammar's optional `knower` scope + additive facts scoped to a knower grow into this without
  a rewrite; not built until after v1.1.

**Out of scope / deferred:**
- `book_start_overrides` (`project.md starting_state`) — deferred (a standalone book needs
  none; ADR-0005 still records book as the boundary).
- **Cross-book** mutation walking — book is the boundary.
- **Character-arc planning tool** — the slider is the *read* twin of that eventual *write*
  tool; the planner itself is out.
- **Linked/shared mutation** (single-point-edit of a recurring state — the only true pull
  toward a pointer model) — opt-in later if it ever earns its keep; does not change v1 storage.
  Tracked as **[#66](https://github.com/antoncl/local-writing-app/issues/66)** (v2). Anton expects
  this to become a common user request once the app is public — it is deferred on *cost* (a stamped
  marker would have to remember its source, breaking scene self-authority, ADR-0001), not on doubt
  about demand.

## 9. Resolved in review (2026-07-01)
1. **Time-slider in v1.0 — YES**, minimal stepped scrubber. Rationale: it's needed to test whether
   the UI paradigm is *feasible*, independent of correctness verification.
2. **Additive combine rule — field-type-gated, per-mutation toggle.** Field type decides whether
   accumulation is offered at all (boolean → replace only); where it is, the writer toggles replace
   vs. add per mutation. (Still v1.1; the v1.0 grammar stays forward-compatible for it.)
3. **Marker id — client-minted, no create route** (§3.2), mirroring embedded-todos.
4. **Resolver seam — the `_format_lore_block` formatter** (§4.2), which covers explicit *and*
   implicit context; mutation-value validation reuses `_validate_metadata_field_value` (§3.4).

## 10. ADRs to record (after this doc settles)
- 0001 — Mutations stored as **self-contained scene-body HTML-comment markers** (value inline,
  Model A), **client-minted id, no create route**; scene authoritative, index derived.
- 0002 — **Independent-interval model**: each mutation is an identified record with its own
  lifetime; **no stack/frame** (co-authored ≠ shared lifetime); closing ends one record by id.
  *Supersedes the v1 draft's "reversal by re-set / no `unset`."*
- 0003 — **Cumulative, position-granular resolution** in manuscript order (position live only
  where a caller has a cursor).
- 0004 — **Every field is mutable** (no `mutable` flag); base = open-ended records at book-start.
  *Implication: the resolver must cover the **implicit-context** path too, not just explicit
  lore — see 0006.*
- 0005 — **Book as the resolution boundary** (`book_start_overrides` deferred; cross-book out).
- 0006 — **Lore context is resolver-mediated at the `_format_lore_block` formatter**, the single
  field-value choke-point through which explicit *and* implicit context flow; base state only at
  the lore page; effective state surfaced via the slider and the roleplay scene-picker. Templates
  can query **both** base (`base(entity, field)`) and effective (`effective(entity, field, scene)`)
  values. Cache: mutable resolved values are volatile (keyed on the mutations-index version +
  resolution scene), not on the lore file's revision.
- 0007 — **A mutation value is a field value**: validated with `_validate_metadata_field_value`
  on scene save and in `validate_project`, via the same scan that builds the index.
- 0008 — **Mutable names segment the implicit-context matcher**: name/title/alias mutations
  partition the manuscript into ≤N+1 segments, each with its own compiled matcher (per-segment
  over union+post-filter); other field mutations don't touch the matcher. Deferred to v1.1+.
