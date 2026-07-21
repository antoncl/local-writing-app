# ADR-0013: The lore entry is time-travel-aware (whole-card effective overlay)

- Status: Accepted (v1.1) — 0.4.0, 2026-07-01 · **Amended 2026-07-19: base at stop 0 is a resolved layer state (ADR-0039)**
- Feature: #33 mid-scene lore mutations · Doc: `time-sensitive-lore-entry.md` · Issue: #64
- Governed by: ADR-0006 (base on the page, effective is an overlay) · Supersedes #57's standalone slider

## Decision
A lore entry with mutations gets a **scrubber strip at the bottom of the card**; **position is the
mode**:
- **Stop 0 (base / book-start) → the card is fully editable** (today's NodeEditor).
- **Any stop ≥ 1 → the whole card becomes a read-only effective overlay** as of that point.

**Scope is total** (purist): `title`, `body`, `aliases`, and every schema field travel — "see the
whole entry as of Scene 5," not a partial rail. Stops are **discrete** (one per marker; effective
state is constant between markers), labelled by scene with a tooltip of the field(s) changing there.

Mutated elements are flagged in the **established mutation-pill vocabulary**: the value renders in
`--mutation-color` (#7c5cbf) with a miniaturized **`⤳`** marker (asterisk-style). The flag signal is
the `effective_state` override map (only-mutated fields), rendered **through each type's widget**
(`FieldValueEditor` read-only), never a raw string.

## Why / rejected alternative
Rejected the v1.0 bolted-on widget (separate slider + raw `field=value` box): it duplicates field
rendering and re-imports string-typing bugs. Making the *real* card time-aware collapses the feature
into `NodeEditor` + `FieldValueEditor` (widget-taxonomy / "everything reduces to NodeEditor").

Rejected an explicit "history mode" toggle: the scrubber's rest position (stop 0) already means
"edit"; a toggle is redundant state. Rejected a metadata-rail-only scope: partial time-travel lies
about title/body, which are mutable too — all-or-nothing is the honest surface.

## Amendment 1 — base at stop 0 is a *resolved* state (2026-07-19, ADR-0039)

> **Resolved by [ADR-0042](0042-inherited-node-edit-gesture.md) (2026-07-21).** Stop-0 editing on an
> inherited entry may now ship: an **authoring-layer picker** in the rail names the write target — at
> the node's owning layer an ordinary write, below it an `overrides/` delta. Two clauses below are
> superseded: the layer axis **does** now select (on the write side only — it still does not scrub the
> *rendering*), and selecting an ancestor collapses this axis to stop 0, since an ancestor has no
> manuscript. The mark question is settled (#304 / PR #320): `ti-versions` for an override, `⤳` for a
> mutation, provenance leading and mutation trailing the value.

Project hierarchies (ADR-0039) make an entry's base potentially composed from several project layers:
an ancestor-owned node is materialized into the open project, with this layer's per-field overrides
folded in. Three clarifications, no change to the decision above:

- **The scrubber is unaffected.** The layer axis has exactly one value per open project — you are
  always at "this project" — so it does not scrub. Stops, discreteness, read-only-above-0 and the
  total scope all stand. Layer resolution completes *before* this axis begins.
- **Stop 0 stays the editable stop, but no longer says what an edit writes to.** When base is
  ancestor + override, editing a field at stop 0 could mean correct the ancestor's canon, or override
  it for this layer. Choosing between them is the fork/override/direct-edit gesture, owned by
  **ADR-0042**; until that lands, stop-0 editing on an *inherited* entry is undefined and should not
  ship.
- **An override needs a tell distinct from a mutation.** `⤳` + `--mutation-color` means "changed by a
  marker at this point in the manuscript". An overridden value is a different fact with a different
  edit affordance and must not borrow that mark. Both marks are settled together in **#304** — `⤳` is
  itself outside the closed glyph lexicon.

A field can be both: overridden at this layer *and* mutated at Scene 5. Precedence is already
determined — overrides fold into base, mutations apply on top — so at stop 5 the mutation wins. Only
the rendering of the doubly-marked field is open (#304).

## Consequences
- New primitives: `FieldValueEditor` **read-only mode** (reusable), a `MutationScrubber` strip, and
  a **buffer-safe read-only body overlay** (flush-on-enter, editable base buffer preserved).
- `MutationTimeline` **shrinks** to just the list; its slider + effective box are removed.
- Scrub state lifts to `NodeEditor`, which fetches `effective_state` and threads
  `effectiveOverrides` + `readOnly` into `MetadataPanel`.
- Depends on the freshness signal (ADR-0014) to stay honest across panes.
