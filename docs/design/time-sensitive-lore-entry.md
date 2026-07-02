# Design: The time-sensitive lore entry

> Status: **DRAFT for review** · Issues: [#64](https://github.com/antoncl/local-writing-app/issues/64)
> (the time-aware card) + [#63](https://github.com/antoncl/local-writing-app/issues/63) (cross-pane
> staleness) · Milestone: 0.4.0 (v1.1)
> Part of #33 mid-scene lore mutations. Read the v1.0 doc
> [`mid-scene-lore-mutations.md`](./mid-scene-lore-mutations.md) (esp. ADR-0006) and
> [`mid-scene-lore-mutations-v1.1.md`](./mid-scene-lore-mutations-v1.1.md) first. This is the
> dedicated design pass that §7 of the v1.1 doc deferred. Supersedes v1.0's standalone slider (#57).

## 1. What & why

A lore entry today renders **one** state (base). Once it carries mutations it really has a
*timeline* of states, and the writer needs to stand at any manuscript point and see **how the entry
looks as of there** — the redaction trust surface ("Chapter 3 must never see it was the butler").
v1.0 bolted this on as a separate widget: its own slider plus a raw `field=value` box. This pass
deletes that second rendering and makes the **real card** time-aware — header, prose body, and every
metadata field show their **effective** values as the writer scrubs.

The anchor is **ADR-0006**: *base lives on the lore page; effective state is a read-only overlay.*
You **edit base** here; you **author mutations** in the prose. That single rule shapes everything
below — the card has exactly two states.

## 2. Interaction model — position is the mode

A slim **scrubber strip docked at the bottom of the lore card** (the NodeEditor shell), shown **only
when the entry has mutations**. Its stops are this entity's ordered mutation points from the index —
**discrete, not continuous**: effective state is constant *between* markers, so there is nothing to
interpolate.

- **Stop 0 = "Base — book start" = the card is fully editable** (today's NodeEditor: editable title,
  prose body, metadata rail). Home *is* edit — no separate "history mode" button, because the
  scrubber's rest position already carries "am I editing or viewing?".
- **Any stop ≥ 1 → the whole card flips to a read-only effective overlay** as of that point, with
  changed elements flagged (§3). Scrub back to 0 to return to editing.

**Scope is total (purist rule): everything mutable travels.** Not just the metadata rail —
`title`, `body`, `aliases`, and every schema field. "See the whole entry as of Scene 5," not a
partial view. Concretely, at a stop ≥ 1:
- **Header** shows the effective **title** (read-only).
- **Body** shows the effective **prose body** (read-only — see §4.4 for the buffer-safe overlay).
- **Rail** shows effective **metadata incl. aliases** (read-only via `FieldValueEditor`).

**Stops & labels.** One stop per marker (per-marker granularity matches position-granular
resolution), labelled by originating scene; when a scene holds several of the entity's mutations they
disambiguate (`Scene 5 · #2`). Each stop carries a **tooltip**: scene + the field(s) that change
there (+ old → new where cheap). The strip and the mutation **list** (§4.3) share the same points —
clicking a list row moves the scrubber to that point.

## 3. Visual language — reuse the mutation pill's vocabulary

The base-vs-mutated distinction leans into the **established in-prose language** rather than
inventing a rail-only treatment:

- **Colour:** the mutated value renders in **`--mutation-color` (#7c5cbf, the violet)** — the same
  token the `.mutation-pill` uses, deliberately distinct from teal character/context marks and amber
  TODO anchors.
- **Marker:** a **miniaturized `⤳` (U+2933)** — the pill's "squiggly arrow" — sits on the field row
  like a form's required-field asterisk, signalling "this changed by here." Unchanged rows render
  plain read-only; only mutated rows get the violet + `⤳`.
- **Signal source is free & exact:** `effective_state()` returns an **override map of only the
  mutated fields**, so "flag this row" ≡ "the field key is in the override map." No diffing needed.
- **Render through the widget, never a raw string** (the banked constraint, ADR-0009): read-only
  rendering routes through each type's `FieldValueEditor` widget (multi_select → static chips,
  `color` → the swatch, `entity_ref` → the entity name, `aliases`/`tags` → chips). A raw string dump
  would reintroduce the `Boolean("false")` bug class. After #58 the value is correctly typed
  (`str | list`), so the widget receives the right shape.
- The header `title` and the body get the same treatment: a `⤳`/violet accent on the header title
  when mutated; a slim violet "body as of «scene» — mutated" ribbon on the read-only body when a body
  mutation is live.

## 4. Components & data flow

State moves **up** out of the self-contained `MutationTimeline` into the `NodeEditor` shell; the
feature **shrinks** the component surface.

### 4.1 NodeEditor owns the scrub state
- Owns `scrubPoint` (null = base/edit; else the selected mutation point) and, when it changes,
  fetches `effective_state(entity, scene, pos)` → an override map.
- Passes down `effectiveOverrides: Record<field, string | string[]> | null` + `readOnly: boolean`.
- Renders the read-only body overlay (§4.4) and the effective header title when scrubbed.

### 4.2 MetadataPanel + FieldValueEditor
- **MetadataPanel** gains optional `effectiveOverrides` + `readOnly`. When set, it overlays overrides
  on base per field, renders read-only, and applies the §3 marker to rows whose key is in the
  override map.
- **FieldValueEditor** gains a **`readOnly` mode** — the one genuinely new frontend primitive. Each
  per-type branch renders a static display instead of its interactive control, through the same
  widget. This is reusable well beyond mutations (any read-only field view).

### 4.3 MutationScrubber + the reduced MutationTimeline
- **New `MutationScrubber.svelte`** — the bottom strip: ordered stops, per-stop tooltip, current
  "as of" label; emits `scrubPoint` up to NodeEditor.
- **`MutationTimeline.svelte` loses its slider and its raw effective-values box** (that job is now the
  real card). It keeps only **the list** — the `BacklinksPanel`-style enumeration of every change
  (field · value · originating scene, click-to-navigate). List + strip are two views of one ordered
  dataset.

### 4.4 The read-only body overlay (buffer-safe)
Scrubbing must not endanger unsaved base edits. Entering a stop ≥ 1 **flushes the editable buffer
first** (reuse `flushSceneIfDirty`), then renders the **effective body read-only** (TipTap
`editable: false`, or a read-only markdown view) as an overlay layer, leaving the editable base
buffer intact underneath. Scrub back to 0 → the editable buffer returns untouched. Effective body =
base body unless a live `body` mutation replaces it.

## 5. Cross-pane freshness — the `mutationsVersion` signal (#63)

The scrubber, list, and effective rendering all read the mutations index. When the writer authors /
edits / deletes a mutation in a **scene** pane while the lore card is open in another pane, the card
must refresh — otherwise the trust surface lies. Design (per #63):

- A rebuildable **`mutationsVersion`** counter in a store, **bumped on a scene save whose mutation
  markers changed** (ProseBodyView already tracks the entry's mutation nodes / enforces unique ids —
  compare the set on save). It owns **no** mutation state — a derived signal over the index-of-nodes
  model.
- The card's fetch effect keys on **`(entityId, mutationsVersion)`**, so authoring anywhere
  invalidates the open card.
- **Fallback:** if "changed?" detection proves fiddly, bump on **every** scene save — the refetch is
  one cheap index read, so over-invalidation is acceptable (Anton's call).

## 6. Scope & build order

**In:** whole-card time-travel (header/body/all fields), scrubber strip + tooltips, `FieldValueEditor`
read-only mode, the violet + `⤳` marker, the `mutationsVersion` signal. Removes #57's standalone
slider + raw effective box.

**Build order:** (1) `mutationsVersion` store + wire the existing MutationTimeline to it (lands #63
standalone, low-risk); (2) `FieldValueEditor` read-only mode; (3) lift scrub state to NodeEditor +
`MetadataPanel` effective overlay + the §3 marker; (4) `MutationScrubber` strip + reduce
MutationTimeline to the list; (5) read-only body overlay + effective header title. Verify gates every
commit (`npm run check` 0/0 + `ruff`/`pytest`; browser-verify — this is a visual, interaction-heavy
surface).

**Depends on:** #58 (the `str | list` contract, so collection fields render right when scrubbed) is
adjacent but not strictly blocking for scalar fields; sequence after the core v1.1 grammar so the
scrubber has add/remove/close intervals to show.

## 7. ADRs
- **0013** — The lore entry is **time-travel-aware**: a scrubber makes the *whole card* (title, body,
  all fields) a read-only effective overlay at stops ≥ 1; base is editable at home (stop 0).
  Position is the mode; scope is total (ADR-0006 governs base-vs-effective).
- **0014** — A rebuildable **`mutationsVersion`** cross-pane signal keys the card's refetch; bumped on
  mutation-changing scene saves, owning no state (index-over-nodes model). Resolves #63.
