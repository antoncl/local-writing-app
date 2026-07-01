# Design: Mid-scene lore mutations — v1.1

> Status: **DRAFT for review** · Issue: [#33](https://github.com/antoncl/local-writing-app/issues/33) · Milestone: 0.4.0
> Builds on the shipped v1.0 spine — read [`mid-scene-lore-mutations.md`](./mid-scene-lore-mutations.md)
> (v3) and ADRs 0001–0008 first. This doc resolves the v1.1 boundary items sketched in that
> doc's §8 into buildable design. It covers **#58–62**. The **time-sensitive lore entry**
> (#63 staleness + #64 the scrubbed, effective-state metadata rail) is deliberately **out of
> this doc** — it gets its own focused design pass (§7).

## 0. What v1.1 is

v1.0 shipped the spine: independent-interval resolver, one project-wide index, `_format_lore_block`
seam, `/mutate` (plural replace-only, open-ended), the pill + detail box, and the lore-card list +
minimal slider. v1.1 completes the **combine rules and lifetimes that drove the original design** —
the cases a replace-only spine can't express:

| # | Item | The case it unlocks |
|---|---|---|
| #58 | Collection **add / remove** ops + per-mutation op toggle | detective clue accumulation; dropping a base-provided alias |
| #59 | Interval **close** (out-of-order) | werewolf revert, red-herring retraction, scene-scoped sub-goals |
| #60 | `scene_ref` resolution input on the roleplay prompt | interrogate the timeline ("your rank as of scene 5?"); supplies the chat/implicit resolution scene |
| #61 | Effective-**name**-aware matcher | a renamed entity is auto-detected under its effective name at each scene |
| #62 | Reusable **transformation sets** (new Node kind) | DRY authoring of a recurring multi-field transform (werewolf) |

All five stay within the Model-A / independent-interval / resolver-mediated architecture — they are
**additive grammar + one new Node kind**, no storage-format migration (pre-1.0 rule holds).

## 1. Collection mutations — add & remove (#58)

v1.0 markers are scalar **replace**. v1.1 adds two collection operators, gated to the three
collection field types (`multi_select`, `tags`, `entity_ref_list`); every other type stays
replace-only.

### 1.1 Two operators, not one
The design review surfaced **add** (accumulate a clue). Review of *this* doc surfaced its sibling:
**remove**. Remove is not redundant with close (#59):

- **close** ends *a specific record you authored* — "undo my scene-5 add of `The Wolf`."
- **remove** drops a value that has **no record to close** — most importantly a value that came
  from **base** (the lore file). Base is an open-ended record at book-start with no marker id, so
  the only way to retract a base-provided alias/tag mid-manuscript is a first-class remove.

Example: base `aliases = ["Jon"]`; `remove aliases "Jon"` at scene 30 ⇒ "Jon" is gone from scene 30
onward, no close possible. Both operators are value-carrying, live-interval records like any other.

### 1.2 Grammar (forward-compatible extension of ADR-0001)
```
<!-- mutate:entity=<id>;field=<key>;op=add;value=<url-encoded-item>;id=<marker-id> -->
<!-- mutate:entity=<id>;field=<key>;op=remove;value=<url-encoded-item>;id=<marker-id> -->
```
- `op` is **absent** on v1.0 replace markers (implicit `op=replace`) — old markers untouched.
- Each add/remove marker carries **one collection element** in `value`. A `/mutate` gesture that
  adds three tags mints three markers (mirrors the plural-field pattern from v1.0).
- Validation (ADR-0007) runs the *element* through the collection type's item validator
  (`_validate_metadata_field_value` already item-checks `multi_select`/`tags`/`entity_ref_list`).

### 1.3 Resolution
Extends §2.2 of the v1.0 doc. For a **collection** field, effective value at `(scene, pos)` is:
```
effective_collection = (base_set ∪ {live add records}) ∖ {live remove records}
```
- **Set semantics**, deduped by value equality; order among adds/removes is irrelevant.
- **Remove wins** when the same value is both added and removed and both are live (redaction bias:
  a deliberate hide beats an add). To bring a removed value back you close the remove record (#59)
  or add it again *after* the remove's interval — consistent with the interval model.
- Scalar fields are unchanged: latest-started live replace record wins.

### 1.4 Contract widens to `dict[str, str | list]` (ADR-0009)
v1.0's `effective_state() -> dict[str, str]` cannot honestly represent a resolved collection.
Per Anton's purist call, the contract becomes **`dict[str, str | list[str]]`**: scalar fields
resolve to a string (as today), collection fields resolve to a **`list[str]`** — the datatype
matches the field. This ripples to the two consuming boundaries, both of which already type-normalize
so the change is small:
- `effective()` Jinja helper → `_coerce_mutation_value` returns the list for collection fields;
- `FieldValueEditor` / `getEntityEffectiveState` → `normaliseFieldValue` already produces arrays for
  the three collection types.

The v1.0 review's "keep it `dict[str,str]` so the widget can't mis-coerce" concern is preserved by a
*different* mechanism: the value is now correctly typed at the source, so no widget-side string→bool
guesswork is needed (the class of `Boolean("false")` bug stays fixed because the boolean path is
untouched — booleans are still scalars, still strings, still coerced at the boundary).

### 1.5 Authoring
In the `/mutate` form, when the picked field is one of the three collection types, show an
**op selector** (replace-whole / add-item / remove-item). `add`/`remove` take a single item via
that field's item widget (a tag chip, a select option, an entity picker); `replace` keeps the v1.0
whole-value behavior. Non-collection fields show no selector (replace only).

## 2. Interval close (#59)

### 2.1 Close-marker grammar (ADR-0010)
Close is a **separate marker at the close position**, not an attribute on the start marker — the end
of an interval is a different point in the prose than its start, so it must live where it happens:
```
<!-- mutate:close;ref=<start-marker-id>;id=<close-marker-id> -->
```
`ref` names the record being closed (any op: replace, add, or remove — close is op-agnostic). The
close-marker carries its own id so it too can be edited/deleted like any marker.

### 2.2 Resolution — "live at point"
A record with start `S` and a close referencing it at `C` is **live at `P` iff `S ≤ P < C`**
(close is exclusive). Absent a close, live from `S` to end-of-book (v1.0 behavior). The resolver in
§2.2 of the v1.0 doc already computes "records live at `(scene, pos)`"; close simply narrows an
interval's upper bound. **Out-of-order retraction** (close one add while its siblings stand) needs no
special handling — each record's liveness is independent (ADR-0002).

### 2.3 Revert has no stored value
When a closed **replace** record expires, the field reverts to the **next-latest-started still-live
replace record**, ultimately base — "latest live wins" recomputed, *no stored prior value*
(ADR-0002 consequence). Werewolf revert at dawn = the dusk records' intervals end; the base
appearance/abilities resurface automatically. When a closed **add/remove** expires, it just leaves
the live set and the collection recomputes per §1.3.

### 2.4 Authoring
A `/mutate close` slash command at the cursor lists the entity's records **live at that point —
by name** (§6, e.g. «Full Moon»); picking one (or a **co-authored group** — the soft create-together
label from v1.0 §5.2) inserts the close-marker(s) at the cursor. "Close the whole werewolf transform
at dawn" is thus one gesture over the group. Base records are not closeable (no marker id). The
lore-card list (and the eventual time-sensitive rail, §7) can also offer "close here" as a
convenience that drops the same marker.

## 3. Resolution scene input — `scene_ref` (#60)

The roleplay prompt gets an **optional scene picker** so a writer can interrogate the timeline
("what's your rank as of scene 5 vs scene 10?") and so the **chat/implicit path has a scene to
resolve against** (§4.2 of the v1.0 doc — the implicit journal carries only ids). Per Anton, this is
a **new single-select `scene_ref` prompt input type**, not an overload of `context_pick`:

- `context_pick` means "collect these items and *inject* them as context" — plural, additive to the
  envelope. A resolution scene is a **setting**, not injected content; overloading `context_pick`
  would muddy that semantics.
- `scene_ref` is a single scene reference, reusing the existing `NodePicker` constrained to
  `{ kinds: ["scene"] }` for its widget (per `decisions_inputs_fields_uniformity` — same widget per
  ref type). Add the literal to `PromptInputType` (backend `models.py` + frontend `types.ts`).

**Default & fallback:** defaults to the session's **current/anchored scene**. A general chat with no
anchored scene resolves at **end-of-book** (full knowledge) — a non-manuscript chat isn't
redaction-sensitive, so unrestricted is the safe default there; the writer can still pick a scene to
scope it. Threading: the picked scene id flows into `_format_lore_block(scene=…)` for both the
explicit and implicit paths.

## 4. Effective-name-aware matcher (#61) — rescoped

**Grounding correction to ADR-0008.** The ADR modeled this as "N+1 compiled matchers across the
manuscript." The shipped consumers don't scan the manuscript — each resolves at **one** scene:
- **Backend:** `_alias_match()` (`services/ai/helpers.py:748`) scans the **chat user message**,
  resolved at the chat's **one** resolution scene (from #60). Not a compiled automaton — a per-send
  name-set membership scan over titles + aliases.
- **Frontend:** `compileMatcher()` (`lib/editor-core/implicitContextMatcher.ts:62`) is a real
  regex-OR, but the highlighter scans **one open scene's** prose.

So "N+1 segments" collapses to the primitive both actually need: **"the effective name-set as-of
scene X."** The full segment machinery is only warranted if something ever scans *many* scenes in one
pass (a batch re-index) — nothing does today. v1.1 therefore delivers:

- A small backend read: **`GET /api/scenes/{id}/effective-names` → `{entity_id: [effective title + aliases]}`**,
  computed from the mutations index by applying live name/title/alias mutations at that scene
  (end-of-scene). One call, not N per-entity `effective` calls.
- **Backend `_alias_match`** builds its candidate set from that effective map (keyed by the
  resolution scene) instead of raw `title`/`aliases`.
- **Frontend `compileMatcher`** compiles from the effective name-set of the open scene (fetched
  once per scene, invalidated on the mutations-index version). The regex-OR is unchanged; only its
  input name-set becomes scene-effective.

**Known limitation:** resolution is **scene-granular** — a name change *mid-scene* uses the scene's
end-of-scene name-set for the whole scene's highlighting. Acceptable; a mid-scene rename that must
highlight differently before/after its own marker is a rare edge we won't chase in v1.1. ADR-0008 is
amended with this scoping.

**This limitation must be surfaced to the user — not left buried here** (Anton). Two required
touchpoints, both part of shipping #61:
1. **User guide:** `docs/mutations.md` § "How resolution works — and its one limit" explains it in
   plain language (written).
2. **At the point of use:** when the `/mutate` form's picked field is `title`/`name`/`aliases`, show
   a brief inline note ("Name changes resolve per scene — within the scene of the change, detection
   uses one name for the whole scene") linking to that guide section. A rename is exactly when a
   writer should be reminded, so the reminder rides the authoring surface.

## 5. Reusable transformation sets (#62) — a new Node kind

A **transformation set** is a saved, reusable bundle of field mutations (the recurring werewolf
transform: appearance + abilities + name), applied to a chosen entity in one gesture. It **expands to
ordinary inline Model-A markers** — no new storage for the markers, no "linked mutation"
(single-point-edit of a live state stays out of scope, v0.4.0 §8).

### 5.1 Why a Node kind and not a sub-type (ADR-0011)
Checked against `architecture_class_instance_model` (the snippet lesson): a new `kind` is warranted
only when **storage shape genuinely differs** *and* a **new routing surface** is needed — otherwise
write a sub-type. A transformation set:
- has a genuinely different storage shape — an **ordered list of `(field, op, value)` rows** plus a
  target entry-type; no prose body, no reference graph like lore/scene;
- maps onto **no existing kind** (it's not an AI invocation → not `prompt`; not a world fact → not
  `lore`);
- needs a **new routing surface** — its own list pane + editor.

So it clears the bar as a first-class kind: **`kind: transformation`** (working slug). Sub-classing
via `entry_type` stays available (e.g. a "shapeshift" vs "promotion" family) but isn't required.
**Implementation gate:** before adding the slug to the whitelist in
`_validate_metadata_schema_definition`, re-read `docs/metadata-strategy.md` § Class–instance model
& § Invariants (per the memo).

### 5.2 Shape & parameterization
- A set **targets a lore entry-type** (e.g. `character`) → its rows' field pickers are scoped to that
  type's fields (reusing the same field-picker the `/mutate` form uses).
- Each row is `(field, op ∈ {replace, add, remove}, value)` — the **values are fixed** in the set
  (a werewolf's appearance is the same each transform).
- The **entity is bound at apply time**, not stored in the set — so one "werewolf transform" applies
  to Remus, or to a new werewolf, unchanged.

### 5.3 Authoring, discovery & application
**Two ways to create a set — both just produce a `transformation` node:**
- **In-flow capture (the "reusable?" checkbox).** In the `/mutate` form, once the field-change(s) for
  an entity are composed, a **"Save as reusable set"** checkbox + a name. On insert it (a) drops the
  concrete markers for *this* entity as usual **and** (b) saves a `transformation` node holding the
  `(field, op, value)` rows + the entity's **entry-type** — the specific entity is dropped, so it
  becomes a template. Author-once, promote-in-place.
- **The Transformations pane.** Because sets are a Node kind, they get their own list pane (like
  Lore / Prompts) — the browse/curate/rename/delete home. NodeList + NodeEditor; rows reuse
  `FieldValueEditor`.

**Discovery — the picker is type-scoped.** At apply time only sets whose **target entry-type matches
the chosen entity's type** are offered (mutate a *character* → see "Full Moon", "Promotion"; never a
*location* set). This is the answer to "how does the user know which sets apply" — the list is always
relevant, not an undifferentiated pile. The Transformations pane is the full browse surface.

**Application.** In `/mutate`, after picking the entity, choose a mode — **"Set fields manually"** or
**"Apply a saved set."** The latter shows the type-scoped picker (existing `NodePicker` constrained to
`kind: transformation`, filtered by the entity's entry-type). Picking one **expands the set into N
independent inline markers** at the cursor as a **co-authored group whose shared name + `group=`
default to the set's title** (§6) — so an applied "Full Moon" is later closeable in one gesture as
"«Full Moon»" (§2.4). After expansion they are ordinary markers — individually editable/closeable;
the set is a **stamp, not a live link**.

**Three distinct edit surfaces (stamp semantics — do not conflate):**
- **The inline `⤳` pill** (in the scene document) → edits **that one applied occurrence** (the v1.0
  in-editor path).
- **The lore-card mutation list** → **read-only / navigate**: click a row to jump to the marker in
  its scene, then edit via the pill. (The list is not itself an editor — editing lives in the prose,
  ADR-0006.)
- **The Transformations pane** (the `transformation` node's own editor) → edits the **template**;
  changes affect **future** applications only.

Editing an applied occurrence never flows back to the template, and template edits never touch past
applications — that is the stamp. **Edit-once-propagate-to-all** (linked/shared mutation) is the
deferred v2 pull toward a pointer model, tracked as
[#66](https://github.com/antoncl/local-writing-app/issues/66); Anton expects it to be a common
request once public, but it breaks scene self-authority (ADR-0001) and must be designed deliberately,
not admitted through these edit paths.

## 6. Naming a mutation (cross-cutting)
A mutation carries an **optional user name** — a human label for the change ("Honor's promotion",
"Full Moon transformation"). Absent, it **auto-labels** as `field → value` ("rank → Captain"), so
naming is never required.

**Grammar** (extends ADR-0001): an optional `name=<url-encoded>` on the marker —
`<!-- mutate:…;value=…;name=<url-encoded>;id=… -->`.

**Granularity — the name is a label, shared across a co-authored group, NOT a lifetime frame.**
A single mutation's name labels its own marker. A co-authored set (a plural `/mutate`, or an applied
transformation set §5) **shares one name** across its members via a `group=<id>` tie, so the set is a
single nameable, close-together unit. This is v1.0 §5.2's "soft group label" made user-editable and
first-class — and it stays a **label + create/close-together convenience only**: each record's
interval is still independent (ADR-0002). Naming a group is **not** a stack or a frame; the werewolf
who learns a clue mid-transform still keeps the clue after the transform's records close.

**Where it surfaces:**
- **Authoring (`/mutate`):** an optional "name this change" field; one name per plural set. A
  transformation set (§5) defaults the group name to the set's title.
- **Close (`/mutate close`, §2.4):** the live-record picker lists **by name** ("close «Full Moon»")
  instead of raw ids / auto-labels — the biggest payoff.
- **Display:** the pill detail box (v1.0 §5.1), the scrubber stop tooltips, and the timeline list
  (`time-sensitive-lore-entry.md`) all show the name.

**Editing** a group name rewrites `name=` on each member via the marker-rewrite spine — the name lives
in the markers (Model-A self-contained), **no registry**. The machine `id` stays the addressing key;
the name is display + the human handle for the close picker.

## 7. Build order

`{#58, #59}` (core resolver/grammar completion — they share the marker-grammar + resolver touch
points) → `#60` (small; also unblocks the resolution scene #61 needs) → `#61` → `#62`. Mutation
naming (§6) rides along with the authoring surface it touches (#58/#59). The time-sensitive lore
entry (#63/#64) is sequenced after, as its own design pass (§8).

Each item keeps to the v1.0 recipes: mixin-via-MRO on the backend, presentational rune child +
pure `.ts` helper on the frontend, thin intentful routes; verify gates every commit
(`ruff` + `pytest`; `npm run check` 0/0; browser-verify).

## 8. Out of this doc — the time-sensitive lore entry (#63, #64)

#64 ("the lore card's metadata rail becomes time-aware — scrub a strip, the fields show their
effective values as-of that point, base-vs-mutated distinguished, read-only") supersedes v1.0's
standalone slider (#57) and reshapes the whole rail surface; #63 (timeline staleness across panes)
is the same surface and its cross-pane "mutations changed" signal is needed by #64 regardless. Anton
has scoped these as a **dedicated design phase** — they involve `FieldValueEditor` gaining a
read-only mode, threading a scrubbed position up through `MetadataPanel`, and the base-vs-effective
visual language. Not designed here; opened as its own pass.

## 9. ADRs added by v1.1
- **0009** — Collection mutations use **add/remove** operators; `effective_state` contract widens to
  `dict[str, str | list[str]]` (datatype matches the field).
- **0010** — Interval **close** is a separate close-marker referencing a start id; live iff
  `start ≤ pos < close`; revert is recomputed, not stored.
- **0011** — **Transformation sets are a first-class Node kind** (`transformation`) — distinct
  storage shape + routing surface; expands to inline markers, not a linked mutation.
- **0012** — Resolution scene is an explicit **`scene_ref`** prompt input (single-select, not
  `context_pick`), defaulting to the current scene.
- **0008 (amended)** — effective-name matching is **per-resolution-scene** (one effective name-set),
  not precompiled manuscript segments; scene-granular, with the mid-scene-rename limitation noted.
- **0015** — Mutations carry an optional **user name** (`name=`; co-authored sets share it via
  `group=`) — a label + close-together convenience, **not** a lifetime frame.
