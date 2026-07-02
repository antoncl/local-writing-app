# ADR-0013: The lore entry is time-travel-aware (whole-card effective overlay)

- Status: Accepted (v1.1) — 0.4.0, 2026-07-01
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

## Consequences
- New primitives: `FieldValueEditor` **read-only mode** (reusable), a `MutationScrubber` strip, and
  a **buffer-safe read-only body overlay** (flush-on-enter, editable base buffer preserved).
- `MutationTimeline` **shrinks** to just the list; its slider + effective box are removed.
- Scrub state lifts to `NodeEditor`, which fetches `effective_state` and threads
  `effectiveOverrides` + `readOnly` into `MetadataPanel`.
- Depends on the freshness signal (ADR-0014) to stay honest across panes.
