# ADR-0074: The context picker curates a set of live refs

- Status: **Proposed** — awaiting Anton's review (revision 3; round one: tri-state confirmed, presets retired, tags/views drillable, plot integrated; round two: `#` made an app-wide convention shared with the Lore search, manuscript containers gain the same expand carets as every other container row).
- Concern: the invocation-time context picker (`NodePicker` hosted by `PromptInputField`) — its selection paradigm, what is pickable, and what a picked value stores.
- Follows: ADR-0068 (the picker composes NodeRow/NodeList — that substrate is kept; this is the feature redesign 0068 explicitly scoped out), ADR-0023 (`NodePickerConfig` = sources + mechanics; its *source* vocabulary is reused here in a second position), ADR-0041 (one view-expr IDL, both runtimes — the resolver this leans on), ADR-0048 (plot boards — plot becomes a context source here; its spoiler gate is bounded below).
- Relates: the author-time tri-state tree (`NodePickerConfigEditor` / `pickerTree.ts`) whose paradigm this adopts; `docs/context-picker.md` (the v1 howto this partially supersedes).
- Review mockup: "Context Picker, Take Two", rev 3 (interactive artifact; not normative — the decisions below are).
- **Verified against `7e5e3554` (2026-08-27).**

**A context_pick value is a curated set of refs the server materializes at render time — and the picker is a set-curation surface: toggle and tri-state everywhere, where the manuscript (whole or by act/chapter), a tag, a saved view, and a plotline are each pickable as a single live ref, drillable to their members, with no preset axis and no second query language.**

## Context — the picker is an append menu asked to do set curation

Dogfooding surfaced three deficiencies in one sitting, and inspection shows they share a root: the invocation picker was built as an "add a reference" dropdown.

1. **Containers are not pickable.** `flattenScenes` emits only `n.type === "manuscript:scene"` nodes (`NodePicker.svelte:258`); acts and chapters are walked for their children and never listed. Including a chapter means clicking each of its scenes, one by one.
2. **Search is title-only.** `filterByTitle` (`NodePicker.svelte:297`) is a case-insensitive substring over `title`. Tags and aliases — which the Lore pane's search does match — find nothing here.
3. **Selection is add-only.** `add()` early-returns on an already-picked ref (`NodePicker.svelte:151-152`); the picked row renders dimmed/inert ("✓ Added"), and the only unpick is the `×` on the picked list outside the menu.

Three latent faults sit in the same area (all verified at the commit above):

- **The manuscript allowlist is a silent no-op.** The config stores manuscript sources under kind `"manuscript"` (`NodePickerConfigEditor.svelte:156-159`), so `pickerMembership` buckets entry-types under `entryTypes.manuscript` — but `flattenScenes` reads `membership.entryTypes.scene` (`NodePicker.svelte:250`), a key that never exists. Author-side act/chapter/scene-subtype selections cannot reach the invocation picker.
- **Saved-view sources are dropped at invocation time.** `pickerMembership` skips any source without a `kind` (`pickerSources.ts:40`, "view-ref: unresolved here"), and nothing else resolves them — a config sourced only from a saved view shows the "no content sources" empty state. ADR-0023's "…or use a saved view" does not function at runtime.
- **`PromptInputField` passes neither `plotEntries` nor `assistantEntries`** to NodePicker (`PromptInputField.svelte:208-217`), so a config allowing those kinds lists nothing, though `ReferencePicker` supplies both from stores.

**Plot is absent from context picking by drift, not decision.** The v1 context picker predates plot boards and deliberately scoped its author UI to scene + lore (excluding snippets and assistants *with stated reasons* — they are template fragments and personas, not story data; `NodePicker.svelte:11-14`); plot was simply not there to consider, and the kinds list never grew. Today plot reaches AI two ways only: the spoiler-gated `plot_context(as_of=…)` template global (ADR-0048 S8b; `helpers.py:553`), and the built-in plot prompts whose target entity is the open editor node. The picker's own plot branch (#742; `NodePicker.svelte:353-361` — whose per-kind entry-type filter, note, reads the *correct* key) serves `ReferencePicker` hosts such as a card picking its plotline, not context_pick.

Meanwhile the *author-time* configurator already embodies the paradigm the writer needs: a tri-state checkbox tree (`pickerTree.ts` — cascade, indeterminate parents, always-visible state). The app has the right mechanism; it is on the wrong side of the flow. NovelCrafter's context menu (the shared reference point) is organized by *dimension* — by structure, by type, by tag, by POV — and each submenu pick is a selector, not a node. The dimension organization is worth adopting; its hover-cascade submenus are not (they hide cross-menu state, host no trees, and clip at viewport edges — the composer sits at the bottom of the pane).

## Decision

1. **Toggling, not appending.** A candidate row in the picker shows its picked state and clicking toggles it — in a search result, in a drill-in panel, and in the picked list alike. The dimmed "✓ Added" inert row is retired (superseding ADR-0068's "keep the disabled row" point: that decision preserved behaviour during a pure widget reduction; this ADR changes the behaviour it preserved, for the reason 0068 itself deferred — the reduction was "not a redesign of the context_pick feature"). Each drill-in panel carries a "Clear" for its own axis.

2. **One container semantics, five container shapes.** The manuscript root ("The Manuscript"), an act, a chapter, a tag, a saved view, and a plotline are each pickable **whole, as one live ref**, and each is **drillable to its members**, which are individually pickable. The same tri-state rules apply to all of them:
   - **Whole = one live ref.** The server materializes it at render time — descendant scenes in manuscript order for structural containers, current members for a tag or view, its cards for a plotline. The set is *live*: a scene added to the chapter, an entry newly tagged, a card added to the plotline is included on the next render.
   - **Absorb:** checking a container removes now-redundant direct member picks and stores the container ref.
   - **Split:** unchecking one implied member replaces the container ref with explicit refs to the remaining members — a deliberate *freeze*, visible in the picked list. No hidden "excluded from container" state: what the picked list shows is exactly what is stored. (If a frozen snapshot is ever genuinely wanted, the split gesture produces exactly that — which is why no separate "freeze" affordance exists.)
   The picked list renders a container ref as one row with a live count ("Ch 2 — The Night Count · 4 scenes", "#heist-thread · 6 items"). ★ target-marking is unchanged and stays scene-only — `scene` carries the implicit-target semantics; containers have no natural equivalent.

3. **Dynamic picks reuse the ADR-0023 source vocabulary; one resolver.** Structural container refs ride the existing `NodePickerRef` shape (`{id, kind, entry_type, title}`, `types.ts:751` — acts, chapters, plotlines, and cards are nodes with ids). Tag and view picks are **selectors**, stored in the same value array using the grammar `NodePickerConfig.sources` already speaks: a `ViewRef` (`{view: id}`) for a saved view, a degenerate `ViewSpec` (`{kind, expr: {tagged: …}}` — a leaf the view grammar already defines, `view-grammar.yaml:85`) for a tag. The stored value type widens from `NodePickerRef[]` to `(NodePickerRef | ViewSource)[]`. The backend materializes selectors through the view evaluator it already shares via the one-IDL grammar (ADR-0041) — **no second query language, no bespoke tag-resolver**. This same materialization path is what makes author-side view sources finally *resolve* at invocation time instead of being dropped.

4. **Plot is a context source kind.** `plot` joins the configurator's source kinds (the class–instance lens: plot cards are Nodes carrying story knowledge, unlike the deliberately-excluded snippets/assistants, whose v1 exclusion reasons still hold and are kept). Plotlines are the containers of decision 2; cards their members. **The spoiler-gate boundary:** ADR-0048's gate belongs to the *derived* `plot_context()` recap, which reasons "up to a point in the story". An explicitly picked card is authorial intent and is rendered ungated — a writer who hand-picks a card wants that card. A future thread must not "fix" explicit picks to be spoiler-gated; the gate and the pick answer different questions.

5. **The preset axis is retired.** Round-one review found presets confusing, and under this model they are redundant or misplaced: "Full Novel Text" *is* checking The Manuscript root (one live ref, counted); "Full Outline" was never a *what* — it is a *rendering*, and the picker's own v1 rule ("the picker is purely about what is picked; the template decides rendering") already ruled that out of the picker. `full_outline()` and `full_text()` remain template globals (`helpers.py:543-544`). **Compatibility:** stored `preset:*` refs in existing values keep materializing exactly as today; the picker simply stops offering new ones, and `NodePickerConfig.presets` becomes inert author-side (removed from the config editor, tolerated in stored configs).

6. **One search, both surfaces.** The picker's search matches title, tags, and aliases — through the *same matcher* the Lore pane's search uses, not a parallel one. A leading `#` restricts the query to tags, and it is an **app-wide convention, not picker syntax**: the Lore pane's search adopts `#` in the same slice, so the two surfaces never disagree about what a query means (`#` is additive there — plain queries behave exactly as today). Search cuts across the axes from the top level, and within a drilled-in panel it filters that panel. Search results are toggle rows like any other; a tag row in the results is the same selector pick as the By-tag panel.

7. **The surface is a drill-in popover, not hover cascades and not (yet) a modal.** One popover: top level = search + axis rows with counts (Manuscript, Plot, Lore, By tag, Saved views — an axis with nothing behind it is dropped, as empty groups are today); tapping an axis pushes its panel with a ← back header. **Every container row carries the same inline expand caret** — acts and chapters exactly like tags, views, and plotlines; no container is always-expanded by privilege. Open-by-default follows the picker's existing rule (`groupOpenByDefault`, `NodePicker.svelte:489-492`): open when small, collapsed past the size threshold, an explicit toggle overrides, and an active search expands every surviving row. Hover-cascade submenus are an anti-goal (state hidden across submenus, no room for a tree, viewport clipping at the composer). A modal re-host of the same panels is the named escalation *if* real manuscripts prove the popover cramped — deliberately not designed here.

8. **The groundwork faults are fixed first, independent of the redesign:** the `entryTypes.manuscript`/`scene` key mismatch, the missing `plotEntries`/`assistantEntries` props, and (as part of decision 3) runtime resolution of view sources.

## Why / rejected alternatives

- **Expand containers at pick time** (checking a chapter stores its 15 scene refs). Rejected — it looks equivalent on day one and isn't: the set is frozen, so a scene written into the chapter next week is silently absent from a prompt that says "Chapter 2"; and the picked list becomes 15 rows of noise. The live ref also keeps the picker's founding constraint — "store refs, never bodies" — doing its job at every scale up to the whole novel.
- **Keep presets as their own axis.** Rejected (decision 5) — one preset duplicates the root container, the other smuggles a rendering decision into a what-picker, and review found the axis confusing in practice.
- **A bespoke tag/type query format for dynamic picks.** Rejected — the view algebra is the app's one way to say "a filtered subset of the node set" (ADR-0037), the grammar already has the `tagged` leaf, and both runtimes already generate from the same IDL. A second vocabulary would drift from the first.
- **Spoiler-gating explicitly picked cards.** Rejected in advance (decision 4) — the gate answers "what does the story know at this point"; a pick answers "what do I, the author, want in context". Gating picks would make a hand-picked card silently vanish from the prompt.
- **Hover-cascade submenus (the NovelCrafter treatment).** Rejected as above; the *dimension organization* is adopted, the menu mechanics are not.
- **A modal dialog now.** Rejected for the common case — "grab that one scene while composing" shouldn't pay a scrim-and-Done ceremony. The panels are self-contained, so a later re-host is not a redesign; the modal must earn its way in with evidence of crampedness.
- **Hiding picked candidates from the list.** Still rejected (as in ADR-0068) — a picked row stays visible; what changes is that it is *toggleable* instead of inert.

## Anti-goals

- **No per-item treatment toggles** (full text vs summary per pick) — unchanged from v1; the template decides rendering. Retiring Full Outline (decision 5) *enforces* this rule rather than bending it.
- **No new query language** beside the view grammar.
- **No hover-cascade submenus.**
- **No change to ★ semantics** — single target, scenes only, `preview.py`'s marked-target resolution untouched.
- **Snippets and assistants stay out of context picking** — their v1 exclusion reasons hold (template fragments are `{% include %}`d; personas are assigned).
- **No parameterized selectors in this ADR** ("Full Text by POV" and kin). Deferred, undesigned — recorded only as out of scope.
- **The author-time configurator is not redesigned here.** It gains the `plot` kind in its existing sources list; its paradigm and layout are untouched.

## User journey (definition of done)

A writer invokes a prompt with a context input. The popover opens on search + five axis rows. They drill into Manuscript and check **The Manuscript** — one picked row: "The Manuscript · 62 scenes" (the old Full-Text preset, as a plain container). They change their mind, uncheck it, and check **Chapter 2** instead; then uncheck one scene of it in the tree — the picked list now shows the remaining scenes explicitly. In **By tag** they expand **#heist-thread** with its caret, see its six members, and check the tag whole: one live row, "#heist-thread · 6 items". In **Plot** they check the plotline **The Heist** — "3 cards" — then drill in and uncheck the card that would spoil the ending, leaving two explicit card picks. A lore entry found by its *alias* is toggled on from the search results, then toggled back off from the picked list without reopening anything. Next week they add a scene to Chapter 2 and tag a new faction #heist-thread — every prompt holding those refs includes them, un-edited. Nothing about ★ or the template surface has changed.

## Consequences

- **Storage widens additively; no migration.** Existing stored values (`NodePickerRef[]` JSON, including `preset:*` refs) remain valid and keep materializing; selector variants only appear once a user picks one. Post-0.9.5 rules apply and are satisfied: no existing shape changes.
- **The backend gains one materializer** (ref/selector → node-set) shared by structural containers, tags, views, and plotlines — built on the walker + view evaluator, not beside them.
- **A `plot` kind colour token does not exist** (`--k-plot` is absent from `styles.css`); the implementation slice that surfaces plot rows decides it with the design-language doc, not this ADR.
- `docs/context-picker.md` needs a rewrite to match (part of the final slice).
- ADR-0023's config contract is untouched except `presets` becoming inert author-side; ADR-0068's widget substrate is untouched (rows stay NodeRow compositions; toggling rides `onClick` + the existing slots).
- The `#1458` collapsed-strip/chevron fix (author-time configurator) is unaffected.

## Slices

1. **Groundwork (bugs, no paradigm change):** the `entryTypes` key mismatch; pass `plotEntries`/`assistantEntries` from `PromptInputField`; each is issue-first per the house workflow.
2. **Toggle semantics:** candidate rows toggle; "✓ Added" inert state retired; per-panel Clear. No storage change.
3. **Search widening:** the shared matcher (title + tags + aliases) in the picker, and the `#` tag restriction landing in *both* the picker and the Lore pane search in one slice — the convention ships whole or not at all.
4. **Structural containers** (root/act/chapter) + tri-state manuscript tree with absorb/split, container refs materialized server-side; presets retired from the picker in the same slice (the root ref replaces Full Novel Text — the two must land together so the capability never regresses).
5. **Selector picks:** tag picks and runtime view-source resolution through the shared evaluator; member drilldown for tags and views; picked-list selector rows with live counts.
6. **Plot integration:** `plot` in the configurator kinds; plotline containers + card members in the picker; the ungated-explicit-pick rendering.
7. **Drill-in panel restructure** of the popover (axes, push navigation) — last, so every panel it hosts already works; includes the `docs/context-picker.md` rewrite.
