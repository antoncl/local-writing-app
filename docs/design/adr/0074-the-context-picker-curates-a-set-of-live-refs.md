# ADR-0074: The context picker curates a set of live refs

- Status: **Proposed** — awaiting Anton's review. Design for #1458's parent concern (invocation-time picker UX), from dogfooding 2026-08-27.
- Concern: the invocation-time context picker (`NodePicker` hosted by `PromptInputField`) — its selection paradigm, what is pickable, and what a picked value stores.
- Follows: ADR-0068 (the picker composes NodeRow/NodeList — that substrate is kept; this is the feature redesign 0068 explicitly scoped out), ADR-0023 (`NodePickerConfig` = sources + mechanics; its *source* vocabulary is reused here in a second position), ADR-0041 (one view-expr IDL, both runtimes — the resolver this leans on).
- Relates: the author-time tri-state tree (`NodePickerConfigEditor` / `pickerTree.ts`) whose paradigm this adopts; `docs/context-picker.md` (the v1 howto this partially supersedes).
- Review mockup: "Context Picker, Take Two" (interactive artifact; not normative — the decisions below are).
- **Verified against `7e5e3554` (2026-08-27).**

**A context_pick value is a curated set of refs the server materializes at render time — and the picker is a set-curation surface: toggle and tri-state everywhere, with containers, tags, and saved views pickable as single live refs, not as N frozen leaf picks.**

## Context — the picker is an append menu asked to do set curation

Dogfooding surfaced three deficiencies in one sitting, and inspection shows they share a root: the invocation picker was built as an "add a reference" dropdown.

1. **Containers are not pickable.** `flattenScenes` emits only `n.type === "manuscript:scene"` nodes (`NodePicker.svelte:258`); acts and chapters are walked for their children and never listed. Including a chapter means clicking each of its scenes, one by one.
2. **Search is title-only.** `filterByTitle` (`NodePicker.svelte:297`) is a case-insensitive substring over `title`. Tags and aliases — which the Lore pane's search does match — find nothing here.
3. **Selection is add-only.** `add()` early-returns on an already-picked ref (`NodePicker.svelte:151-152`); the picked row renders dimmed/inert ("✓ Added"), and the only unpick is the `×` on the picked list outside the menu.

Three latent faults sit in the same area (all verified at the commit above):

- **The manuscript allowlist is a silent no-op.** The config stores manuscript sources under kind `"manuscript"` (`NodePickerConfigEditor.svelte:156-159`), so `pickerMembership` buckets entry-types under `entryTypes.manuscript` — but `flattenScenes` reads `membership.entryTypes.scene` (`NodePicker.svelte:250`), a key that never exists. Author-side act/chapter/scene-subtype selections cannot reach the invocation picker.
- **Saved-view sources are dropped at invocation time.** `pickerMembership` skips any source without a `kind` (`pickerSources.ts:40`, "view-ref: unresolved here"), and nothing else resolves them — a config sourced only from a saved view shows the "no content sources" empty state. ADR-0023's "…or use a saved view" does not function at runtime.
- **`PromptInputField` passes neither `plotEntries` nor `assistantEntries`** to NodePicker (`PromptInputField.svelte:208-217`), so a config allowing those kinds lists nothing, though `ReferencePicker` supplies both from stores.

Meanwhile the *author-time* configurator already embodies the paradigm the writer needs: a tri-state checkbox tree (`pickerTree.ts` — cascade, indeterminate parents, always-visible state). The app has the right mechanism; it is on the wrong side of the flow. NovelCrafter's context menu (the shared reference point) is organized by *dimension* — by structure, by type, by tag, by POV — and each submenu pick is a selector, not a node. The dimension organization is worth adopting; its hover-cascade submenus are not (they hide cross-menu state, host no trees, and clip at viewport edges — the composer sits at the bottom of the pane).

## Decision

1. **Toggling, not appending.** A candidate row in the picker shows its picked state and clicking toggles it — in a search result, in a drill-in panel, and in the picked list alike. The dimmed "✓ Added" inert row is retired (superseding ADR-0068's "keep the disabled row" point: that decision preserved behaviour during a pure widget reduction; this ADR changes the behaviour it preserved, for the reason 0068 itself deferred — the reduction was "not a redesign of the context_pick feature"). Each drill-in panel carries a "Clear" for its own axis.

2. **Containers are pickable and store one live ref.** Acts and chapters appear in a tri-state manuscript tree (the `pickerTree.ts` paradigm). Checking a container stores a single ref to that node — the existing `NodePickerRef` shape already carries it (`{id, kind: "manuscript", entry_type: "manuscript:act" | "manuscript:chapter", title}`, `types.ts:751`) — and the server expands it to its descendant scenes at render time, in manuscript order. The set is *live*: a scene added to the chapter later is included on the next render. Tri-state edits stay lossless in both directions:
   - **Absorb:** checking a container removes now-redundant direct picks beneath it and stores the container ref.
   - **Split:** unchecking one implied child replaces the container ref with explicit refs to the remaining children. No hidden "excluded from container" state — what the picked list shows is exactly what is stored.
   The picked list renders a container ref as one row with a live count ("Ch 2 — The Night Count · 4 scenes"). ★ target-marking is unchanged and stays scene-only — `scene` carries the implicit-target semantics; containers have no natural equivalent.

3. **Dynamic picks reuse the ADR-0023 source vocabulary; one resolver.** "Everything tagged heist-thread" and "the scenes in this saved view" are picked as **selectors**, stored in the same value array as node refs, using the grammar `NodePickerConfig.sources` already speaks: a `ViewRef` (`{view: id}`) for a saved view, a degenerate `ViewSpec` (`{kind, expr}` — e.g. `expr: {tagged: "heist-thread"}`, a leaf the view grammar already defines, `view-grammar.yaml:85`) for a tag pick. The stored value type widens from `NodePickerRef[]` to `(NodePickerRef | ViewSource)[]`. The backend materializes selectors through the view evaluator it already shares via the one-IDL grammar (ADR-0041) — **no second query language, no bespoke tag-resolver**. This same materialization path is what makes author-side view sources finally *resolve* at invocation time instead of being dropped.

4. **Search matches what the app already knows.** The picker's search matches title, tags, and aliases — the Lore pane's fields — across all axes from the top level, and a leading `#` restricts the query to tags. Search results are toggle rows like any other; a tag row in the results is the same selector pick as the By-tag panel.

5. **The surface is a drill-in popover, not hover cascades and not (yet) a modal.** One popover: top level = search + axis rows with counts (Presets, Manuscript, Lore, By tag, Saved views — an axis with nothing behind it is dropped, as empty groups are today); tapping an axis pushes its panel with a ← back header. Hover-cascade submenus are an anti-goal (state hidden across submenus, no room for a tree, viewport clipping at the composer). A modal re-host of the same panels is the named escalation *if* real manuscripts prove the popover cramped — deliberately not designed here.

6. **The groundwork faults are fixed first, independent of the redesign:** the `entryTypes.manuscript`/`scene` key mismatch, the missing `plotEntries`/`assistantEntries` props, and (as part of decision 3) runtime resolution of view sources.

## Why / rejected alternatives

- **Expand containers at pick time** (checking a chapter stores its 15 scene refs). Rejected — it looks equivalent on day one and isn't: the set is frozen, so a scene written into the chapter next week is silently absent from a prompt that says "Chapter 2"; and the picked list becomes 15 rows of noise. The live ref is also the existing pattern — presets already store one ref (`preset:full_text`) that the server materializes (`docs/context-picker.md`), and the picker's own constraint is "store refs, never bodies". *The tempting simplification is pre-refuted: if a frozen snapshot is ever genuinely wanted, explicit scene picks — which the split gesture produces — are exactly that.*
- **A bespoke tag/type query format for dynamic picks.** Rejected — the view algebra is the app's one way to say "a filtered subset of the node set" (ADR-0037), the grammar already has the `tagged` leaf, and both runtimes already generate from the same IDL. A second vocabulary would drift from the first.
- **Hover-cascade submenus (the NovelCrafter treatment).** Rejected as above; the *dimension organization* is adopted, the menu mechanics are not.
- **A modal dialog now.** Rejected for the common case — "grab that one scene while composing" shouldn't pay a scrim-and-Done ceremony. The panels are self-contained, so a later re-host is not a redesign; the modal must earn its way in with evidence of crampedness.
- **Hiding picked candidates from the list.** Still rejected (as in ADR-0068) — a picked row stays visible; what changes is that it is *toggleable* instead of inert.

## Anti-goals

- **No per-item treatment toggles** (full text vs summary per pick) — unchanged from v1; the template decides rendering.
- **No new query language** beside the view grammar.
- **No hover-cascade submenus.**
- **No change to ★ semantics** — single target, scenes only, `preview.py`'s marked-target resolution untouched.
- **No parameterized presets in this ADR** ("Full Text by POV" and kin). Deferred, undesigned — recorded only as out of scope.
- **The author-time configurator is not redesigned here.** It already has the tri-state paradigm; it gains nothing from this ADR beyond its view sources finally resolving at runtime.

## User journey (definition of done)

A writer invokes a prompt with a context input. The popover opens on search + five axis rows. They drill into Manuscript, check **Chapter 2** — one row appears in the picked list: "Ch 2 — The Night Count · 4 scenes". They uncheck one scene of it in the tree; the picked list now shows the three remaining scenes explicitly. They type `#heist` — tag rows appear; checking **heist-thread** adds one selector row ("#heist-thread · 6 items"). A lore entry found by its *alias* is toggled on from the search results, then toggled back off from the picked list without reopening anything. Next week they add a scene to Chapter 2 in another prompt's project — every prompt holding that chapter ref includes it, un-edited. Nothing about ★, presets, or the template surface has changed.

## Consequences

- **Storage widens additively; no migration.** Existing stored values (`NodePickerRef[]` JSON) remain valid as-is; selector variants only appear once a user picks one. Post-0.9.5 rules apply and are satisfied: no existing shape changes.
- **The backend gains one materializer** (ref/selector → scene-set) shared by containers, tags, and view sources — built on the walker + view evaluator, not beside them.
- `docs/context-picker.md` needs a rewrite to match (part of the final slice).
- ADR-0023's config contract is untouched; ADR-0068's widget substrate is untouched (rows stay NodeRow compositions; the toggle affordance rides `onClick` + the existing slots).
- The `#1458` collapsed-strip/chevron fix (author-time configurator) is unaffected.

## Slices

1. **Groundwork (bugs, no paradigm change):** the `entryTypes` key mismatch; pass `plotEntries`/`assistantEntries` from `PromptInputField`; each is issue-first per the house workflow.
2. **Toggle semantics:** candidate rows toggle; "✓ Added" inert state retired; per-panel Clear. No storage change.
3. **Search widening:** title + tags + aliases, `#` tag restriction.
4. **Containers + tri-state manuscript tree** with absorb/split, container refs materialized server-side.
5. **Selector picks:** tag picks and runtime view-source resolution through the shared evaluator; picked-list selector rows with live counts.
6. **Drill-in panel restructure** of the popover (axes, push navigation) — last, so every panel it hosts already works; includes the `docs/context-picker.md` rewrite.
