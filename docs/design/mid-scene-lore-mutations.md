# Design: Mid-scene lore mutations

> Status: **DRAFT for review** · Issue: [#33](https://github.com/antoncl/local-writing-app/issues/33) · Milestone: 0.4.0
> Seed: `memory/decisions_mutable_metadata.md`. Decisions here supersede the memo where they differ.

## 1. Problem & goal

Some lore fields change over manuscript time — a character's rank, ship assignment,
marital status; a location's ownership. Today a lore entry stores a single "current"
value, which is wrong as AI context for any *earlier* scene: Chapter 1 should see
Commodore-Honor, Chapter 10 Captain-Honor, with no manual syncing.

**Goal:** a field can be declared *mutable*; a writer records a change at the point in
the prose where it happens; every lore-reading path resolves the **effective value for
the calling scene** automatically.

**Acceptance (from #33):** declare `rank` mutable on the character type; add
`<!-- mutate: honor.rank = "Captain" -->` in Scene 5; Scene 1's Roleplay preview sees
Commodore, Scene 10's sees Captain.

## 2. Core semantics (read first — this is the load-bearing part)

Resolution is **cumulative in manuscript order**, not per-scene:

```
effective(entity, scene_T) =
    base_state(entity)                       # the lore file's stored values
  + book_start_overrides(entity)             # project.md `starting_state`, if any
  + apply_in_order(                          # in manuscript (tree) order
        mutations(entity)  ∩  scenes_up_to(scene_T)   # inclusive of scene_T
    )
```

- `scenes_up_to(scene_T)` = every scene at or before `scene_T` in the **manuscript
  structure order** (act → chapter → scene), per `manuscript.structure.yaml`.
- A marker in scene S therefore affects **S and every later scene**. Storage is
  per-scene; *effect* is cumulative. (See ADR-0002 — this is the semantic the initial
  code-scout got wrong, so it is called out loudly.)
- **Granularity (open decision — recommendation):** resolve at **scene granularity,
  inclusive of the target scene**, computed as if at end-of-scene (all of the target
  scene's own markers applied). The position-granular timing rule ("prose after the
  marker sees the new value") is honored as *authoring* guidance, not enforced by the
  resolver in v1. Known v1 limitation: a `replace_selection` generation positioned
  *before* a marker in the same scene will still see the post-marker value. Position-
  granular resolution is a documented future refinement.

## 3. Data model

### 3.1 Schema — `mutable` flag
Add `mutable: bool = False` to `MetadataFieldDefinition` (`backend/app/models.py:141`,
after `group_origin`). Only `mutable: true` fields:
- accept mutation markers,
- appear in the `/mutate` field autocomplete,
- render a timeline on the lore page.

No new field *type* — `mutable` is an orthogonal flag on existing types (text,
entity_ref, select, …). Validation lives with the other field-def checks in the schema
mixin (`services/project/schema.py`).

### 3.2 Mutation marker — scene-body HTML comment
Mirror the embedded-TODO marker (ADR-0001). Proposed grammar:

```
<!-- mutate:entity=<entity_id>;field=<field_key>;value=<url-encoded> -->
```

- Reuses the exact scan/rewrite machinery of `EmbeddedTodosMixin`
  (`services/project/embedded_todos.py`): a module regex, `_scan_*` generator, and the
  capture-group substitution callback in `_rewrite_embedded_todo()` (`:103`) for atomic
  single-marker edits via `_write_scene_file()`.
- `entity` is the lore entry **id** (canonical identity, not title — filenames/titles
  are not identity). `field` is the field key. `value` is url-encoded to survive
  markdown round-trip and arbitrary content (matches the todo `note` encoding).
- Unlike TODO markers, a mutation marker wraps **no content** — it is a point directive,
  so it is a single self-closing comment (no `<!-- /mutate -->`).

## 4. Backend

### 4.1 New mixin — `LoreMutationsMixin` (`services/project/lore_mutations.py`)
Cohesive slice composed onto `ProjectService` via MRO, alongside `EmbeddedTodosMixin`.

- `_scan_scene_mutations(scene) -> Iterable[MutationMarker]` — regex-walk one body
  (mirrors `_scan_embedded_todos`).
- `build_mutations_index() -> MutationsByEntity` — walk all scenes **in manuscript
  order** (from `read_structure()`), producing `{entity_id: [ (scene_order, field, value) ... ]}`
  ordered by manuscript position. Rebuildable cache (fits the `.cache/` "always
  rebuildable" rule); rebuilt on scene save (the save path already touches indexes).
- `effective_state(entity_id, scene_id) -> dict[field, value]` — the resolver in §2.
  O(applicable mutations), not a full scan, by slicing the pre-ordered per-entity list
  at `scene_id`'s manuscript position.
- `add_mutation` / `update_mutation` / `delete_mutation(scene_id, marker)` — intentful
  writers using the rewrite-callback pattern; return the updated `Scene` and flush the
  index (data-loss surface identical to embedded-todos — reuse
  `flushSceneIfDirty` + `reconcileSceneFromServer` on the frontend).

### 4.2 Integration point (critical — NOT `read_lore_entry`)
Effective state is a function of **(entity, scene)**, so it resolves in the **scene-aware
context path**, not the generic entry reader:

- **Plug into `_relevant_lore(scene)`** (`services/ai/helpers.py:555`) — before
  `_format_lore_block()` (`:654`), replace each mutable field's value with
  `effective_state(entity, scene)[field]`. This is the one place all AI context flows
  through; the memo's invariant "helpers return effective state at the calling scene"
  is satisfied here.
- `read_lore_entry()` (`services/project/lore.py:89`) keeps returning **base** state —
  the lore *page* shows base + a timeline (§5.3), and editing happens at the scene, not
  the entry. Do **not** inject effective values there (it has no scene context).
- Roleplay / `character_query` / context-picker resolution consume `_relevant_lore`'s
  output, so they inherit correct effective state for free.

### 4.3 API
- `GET /api/lore/{entity_id}/mutations` — the timeline for the lore page (all markers
  for an entity, ordered by manuscript position, each with originating scene id/title).
- Authoring goes through the **scene** (markers live in scene bodies), reusing the
  scene-todo route shape:
  - `PATCH /api/scenes/{scene_id}/mutations/{marker_id}`
  - `DELETE /api/scenes/{scene_id}/mutations/{marker_id}`
  - insertion is an ordinary scene save (the `/mutate` command edits the doc), so no
    dedicated create route unless we want server-side marker-id assignment.

## 5. Frontend

### 5.1 TipTap mark — `MutationMark` (`lib/editor-core/proseMarks.ts`)
Mirror `TodoAnchor` (`:77`): store `data-mutation-entity`, `data-mutation-field`,
`data-mutation-value` attributes; `renderHTML` emits `<span class="mutation-pill">`.
Like `createCharacterMark` (`:46`), take resolver closures for entity title + field
label so the pill reads "Honor → Captain" with live lore/schema lookups. Scoped
`<style>` in the owning body view (per the P3 co-location rule); inline colored pill,
visually distinct from entity refs and TODO anchors.

### 5.2 `/mutate` slash command
Register in `getSlashCommands()` (`ProseBodyView.svelte:445`). Args:
`/mutate <entity> <field> <value>`. Autocomplete: entities from the lore store; fields
filtered to `mutable: true` defs on that entity's type. `run()` inserts the marker +
mark at the cursor. Reuses the existing entity-lookup infra that
`implicitContextHighlight.ts` already uses.

### 5.3 Lore-page timeline
On a mutable field, show base value + an ordered timeline of mutations annotated by
scene (from `GET /api/lore/{id}/mutations`). **Read-only** at the lore page; click a
timeline entry to navigate to the originating scene. Reduces to a `NodeList` of small
timeline rows — not a bespoke widget.

## 6. AI verification — `character_query` prompt sub-type
Seed a built-in `prompt.character_query` (a prompt *kind* sub-type per
`decisions_prompt_model` — **not** a new subsystem): roleplay the character at the
current scene's effective state so the writer can interrogate the timeline ("what's your
rank?"). Pure composition over the existing prompt + roleplay machinery.

## 7. Reduction check (what is genuinely new vs. reused)
| Piece | Reuses | New? |
|---|---|---|
| Marker scan / atomic rewrite | `EmbeddedTodosMixin` pattern | no |
| `mutable` flag | `MetadataFieldDefinition` | trivial add |
| Resolver injection | `_relevant_lore(scene)` seam | **yes — the resolver** |
| `mutations_by_entity` index | `.cache/` rebuildable-index pattern | yes (small) |
| Editor pill | `TodoAnchor` / `createCharacterMark` | no |
| `/mutate` command | `getSlashCommands()` | no |
| Timeline view | `NodeList` + `NodeRow` | no |
| `character_query` | prompt sub-type + roleplay | no |

Only **two** genuinely new units: the resolver and its index. Everything else is
composition over shipped patterns — evidence the feature does not warrant a new
subsystem.

## 8. Out of scope (v1)
- **Stack-based `unset`** — reversal is re-set to the prior value (ADR-0004).
- **Cross-book mutation walking** — book is the boundary; books declare `starting_state`
  (ADR-0003).
- **Position-granular resolution** within the mutating scene (§2 granularity note).

## 9. Open questions for review
1. **Granularity** (§2) — confirm scene-granular-inclusive, or require position-granular
   from v1?
2. **Marker id** — reuse the todo id scheme (server-assigned on save) or derive
   deterministically from `(entity, field, scene-offset)`? Affects whether insertion
   needs a create route (§4.3).
3. **`book_start_overrides`** — is `project.md starting_state` in scope for v1, or defer
   (a book with no ancestors needs none)?
4. **Index granularity** — one project-wide `mutations_by_entity`, or per-entity lazy?
   (Save-time rebuild cost vs. read-time cost.)

## 10. ADRs to record (after this doc settles)
- 0001 — Mutations stored as scene-body HTML comments.
- 0002 — Cumulative manuscript-order resolution (+ granularity decision).
- 0003 — Book as the resolution boundary.
- 0004 — Reversal by re-set; no `unset` directive.
- 0005 — Lore context is resolver-mediated; base state only at the lore page.
