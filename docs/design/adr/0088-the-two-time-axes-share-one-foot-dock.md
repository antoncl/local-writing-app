# ADR-0088: The lore card's two time-axes share one foot dock; a mode control picks the track, and the keys stay one gesture across both

- Status: **Proposed** — 2026-09-16 (authored by Claude; awaiting Anton's review). Companion **surface** ADR to ADR-0087 (the model), as ADR-0044 was to ADR-0043. **Amends ADR-0044.**
- **Feature:** the on-card surface for node-scoped snapshots (#401 / ADR-0087) — how a lore card shows both its mutation and snapshot timelines at once.
- **Relates to:** ADR-0087 (the model this surfaces), ADR-0044 (**amends** — realizes its "if both axes ever share a card" case), ADR-0013 (the mutation scrubber / in-fiction time), ADR-0042 (the layer axis, "L, not a grid"), ADR-0038 §A (position-is-mode, compact-expand), ADR-0030 (design language).
- **Mockup (normative for this ADR):** [`../mockups/0087-rotary-scrubber.html`](../mockups/0087-rotary-scrubber.html) — iterated live with Anton; the mode gadget, the two-track visual languages, the diff and the per-layer caption were *tried* here, not sketched. A single self-contained file with fixture data; open it in a browser.

> **Verified against `e05b2d99` (2026-09-16).** Citations name the symbol first; the line is a convenience and is what rots.

## Problem

ADR-0087 makes snapshots available to lore, so a lore card now carries **two** timelines — the entity's **mutations** (story time; the beads-on-a-rail scrubber of ADR-0013, `MutationScrubber.svelte`, today docked in the rail with Details, #1249) and its **snapshots** (edit time; ADR-0087) — plus the **layer** scope ("Editing at", `LayerAuthoringBar.svelte`). ADR-0044 built the snapshot strip for scenes and explicitly hedged the lore case: §A named putting "three axes on one card — layer, story time, real time ... where that problem actually bites," and §C chose "notches, not beads" precisely so that if both axes "ever appear on one card they read apart at a glance while the gesture stays identical." ADR-0087 realizes that hypothetical. So the surface question is now live: how do two timelines and a layer scope coexist on one card without the "L-not-a-grid" clutter (ADR-0042), and how does a second, mutation-scrubbing interaction share ADR-0044's *settled* key model (`←→` = when, `A/S/B` = which, `Esc` = live) without colliding with it.

## Intent

**The two time-axes share one foot dock; a click-to-advance mode control picks which timeline the track travels, and the keyboard gesture is the same in both modes — so the card gains an axis without gaining a second interaction to learn.** Layer stays a separate scope the snapshot track reads from. This amends ADR-0044's surface — its scene strip becomes one of two modes of a shared dock — without touching its color rule, its position-is-mode principle, its compact-expand behavior, or its no-held-modifier constraint.

## Anti-goals (what this must not do)

- **Not three always-on axes.** The failure mode ADR-0044 §A named. Only one timeline is on the track at a time; the layer is a header selector, not a third track.
- **Not two interactions to learn.** `←→` must mean the same thing — step along the current track — in both modes; switching mode must not rehome the keys.
- **Not a held modifier.** ADR-0044's constraint stands (Shift trips Windows Sticky/FilterKeys; the read-only parked state frees the whole keyboard anyway).
- **Not a popover.** The mode control is a click-to-advance gadget, not a dropdown — no zoom-anchored popover (the ADR-0074/#245 problem the app has hit before).
- **Not a redesign of the scene strip.** For a scene (one timeline) the strip stays exactly ADR-0044's; the mode control appears only when a second timeline exists.

## Decision

### 1 — One foot dock, two modes
The lore card's foot dock — the slot where `SnapshotStrip` docks for scenes (`NodeEditor.svelte`, gated `documentKind === "manuscript"` today) — hosts a single track in one of two **modes**: **Snapshots** (ADR-0044's strip, unchanged) or **Mutations** (ADR-0013's scrubber, moved here). Position is the mode within each (ADR-0038 §A / ADR-0044): scrubbing off the editable end parks a read-only overlay of that state.

### 2 — A click-to-advance mode control, not a dropdown
The mode is picked by the app's existing click-to-advance idiom (the theme cycle, `TopBar.onCycleTheme`): one bordered control that advances Mutations → Snapshots on click, showing the **current** track's name with an accent tint while a real choice is live (the `ViewSwitcher` live-state pattern, not a glyph-with-tooltip). No popover. It appears only when the node has **both** timelines; a node with one shows that track with no control.

### 3 — Each mode keeps its own visual language — that is what makes the mode legible
- **Mutations:** beads on a rail, home ⌂ at the left, tinted `--mutation-color` (`MutationScrubber.svelte`) — unchanged from today.
- **Snapshots:** notches cut *into* the edge, `Live` at the right, warm/cool (`--diff-now`/`--diff-was`), a camera to capture (`SnapshotStrip.svelte`) — unchanged from ADR-0044.

The notch-vs-bead distinction ADR-0044 chose "so both axes read apart" now earns its keep: the track's *shape* tells you the mode at a glance, so the mode control's label never has to be read to know where you are.

### 4 — The keys are one gesture across both modes (the ADR-0044 reconciliation)
- **`←→` = step along the current track** — through snapshots by time (ADR-0044's "when") or through mutation stops by position (ADR-0013). The same gesture whichever mode is up.
- **`Esc` = return to the editable end** — `Live` (snapshots) or base/stop-0 (mutations).
- **`A/S/B` = compare** (Active / Snapshot / Both) — **snapshots only**. A mutation stop is a single read-only effective state with nothing to compare against, so the compare control is *absent* in Mutations mode, not present-but-inert.
- **One unmodified key cycles the mode** (the keyboard twin of the gadget). Which key is implementation's (bounded by the no-held-modifier rule; the exact letter is 0005's-lesson detail).

### 5 — The mutation scrubber moves to the foot
Today the mutation scrubber lives in the rail with Details (#1249, which overtook ADR-0013/0042/0044's "foot-docked" description of it). It returns to the foot to share the dock. This is the one relocation, justified by the unification (one track, one gesture) over two separate docks (Alternatives).

### 6 — Layer is a header scope; the snapshot track reads from it
The "Editing at" selector stays in the header. In Snapshots mode the track shows the selected layer's file history (ADR-0087 §3/§3b); switching layers swaps the set. A one-line caption on a parked snapshot names the write target ("Restoring writes the **Series** layer") so ADR-0087 §2's inheritance effect reads instead of feeling like a no-op.

## User journey (the definition of done)

Anton opens **Seraphine Vale** at the **Series** layer. She has no mutations, so the foot dock shows the **snapshot** track alone — no mode control. He adds a mutation in a scene; now she has two timelines and the **mode control** appears. He cycles it to **Mutations**: beads-on-a-rail, `←→` steps the stops, `Esc` back to base. He cycles to **Snapshots**: notches, `←→` steps by time, he parks one, `A/S/B` flips the diff, `Esc` back to `Live`. He switches "Editing at" to **Book**; the snapshot set becomes the book override's shorter history, and a parked restore reads "writes the **Book** layer."

## Alternatives considered

- **Two separate docks (mutations stays in the rail, snapshots in the foot).** Avoids the relocation, but puts two timeline controls on one card with two key models — the "two interactions to learn" anti-goal — and keeps the three-things-on-a-card density ADR-0044 §A worried about. Rejected in favor of one mode-switched dock.
- **A dropdown or segmented mode control.** A segmented control shows both options at once but competes for width with the `A/S/B` compare control already on the parked actions row (two segmented controls on one strip), and a dropdown reintroduces the popover. The click-to-advance gadget is one control, no popover. The mockup puts gadget and segmented head-to-head; the model here is "one click-to-advance mode control," and the exact widget stays checkable against the mockup at build.
- **A key that rehomes per mode.** Rejected — violates "one gesture across both modes."

## Consequences

- The mutation scrubber relocates (rail → foot); its Details/rail slot is freed, and `MutationScrubber` gains the foot-dock chrome (it currently renders inline in the rail).
- ADR-0044's strip gains a sibling mode; its color rule, position-is-mode, compact-expand, and no-held-modifier constraint are all unchanged.
- A single mode-cycle key joins the keyboard model.
- Single-timeline kinds (research/prompt/tag/plot from ADR-0087) get the snapshot track with no mode control — this surface degrades to exactly ADR-0044's strip for them.

## Acceptance

1. A lore card with both timelines shows one foot dock plus a click-to-advance mode control; cycling switches the track *and* its visual language (beads ↔ notches).
2. `←→` steps the current track and `Esc` returns to its editable end in **both** modes; `A/S/B` compare appears only in Snapshots mode; no held modifier is required.
3. A single-timeline node (a scene, or a lore entry with no mutations) shows its track with no mode control; the scene strip's behavior is unchanged from ADR-0044.
4. Switching "Editing at" swaps the snapshot set; a parked snapshot names its write layer.

## To verify / build at implementation

- The exact mode-cycle key (no held modifier).
- The mode control's discoverability affordance + a tooltip listing the cycle, and whether the click-to-advance gadget or a segmented control wins — the mockup is the test surface.
- Whether the dock's compact-at-rest height (ADR-0044) needs to grow to seat the mode control, or the control tucks beside the camera.
- The `MutationScrubber` → foot-dock move: it currently renders in the rail (`NodeEditor.svelte`), so it needs the strip's compact-expand chrome, not the rail's.

---

*This ADR amends ADR-0044: its scene snapshot strip becomes one of two modes of a shared foot dock on a multi-timeline (lore) card. ADR-0044's color rule, position-is-mode, compact-expand behavior, and no-held-modifier constraint are unchanged; for a single-timeline node the surface is ADR-0044's strip verbatim.*
