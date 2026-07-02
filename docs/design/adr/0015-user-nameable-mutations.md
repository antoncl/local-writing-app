# ADR-0015: Mutations carry an optional user name (a label, not a frame)

- Status: Accepted (v1.1) — 0.4.0, 2026-07-01 · **Amended 2026-07-02: `group=` subsumed (ADR-0016)**
- Feature: #33 mid-scene lore mutations · Doc: `mid-scene-lore-mutations-v1.1.md` §6 · Issue: #65
- Extends: ADR-0001 (marker grammar) · Guards: ADR-0002 (independent interval)

> **Amendment (2026-07-02, ADR-0016)** — the multi-row **carrier subsumes `group=`**: the carrier
> *is* the co-authored unit, and `name=` lives once on its head instead of duplicated per member.
> Legacy `group=` markers parse forever and map to a unit tie in the index; new authoring never
> emits `group=`. The name's semantics are unchanged: a label, not a frame — lifetimes stay
> per-row (rows keep their own ids).

## Decision
A mutation may carry an optional **user name** — a human label for the change ("Honor's promotion",
"Full Moon transformation") — via an optional `name=<url-encoded>` on the marker. Absent, it
**auto-labels** as `field → value` ("rank → Captain"), so naming is never required.

The name is **a mnemonic assist, nothing more** (Anton, 2026-07-01) — it carries no semantic weight:
it is not identity (the `id` is), not a scope, and not a lifetime container.

A co-authored set (a plural `/mutate`, or an applied transformation set, ADR-0011) **shares one name**
across its member markers via a `group=<id>` tie, so the set is a single nameable, close-together
unit. The name/`group` is a **label + create/close-together convenience ONLY** — it does **not** bind
lifetimes; each record's interval stays independent. The machine `id` remains the addressing key for
edit/delete/close-`ref`; the name is display + the human handle for the close picker.

## Why / rejected alternative
Names make every human-facing surface legible: the `/mutate close` picker (ADR-0010) lists "close
«Full Moon»" instead of a raw id; the pill detail box, scrubber tooltips, and timeline (ADR-0013)
read as prose.

Rejected letting the shared name/`group` imply a **shared lifetime** (a frame/stack): that is exactly
the conflation ADR-0002 rejects — co-occurring ≠ sharing a lifetime (the werewolf learns a clue
mid-transform that outlives the transform). A group closing together is a one-gesture convenience over
N still-independent records, not a semantic container.

Rejected a **separate name registry** keyed by group id: it reintroduces the pointer-table
split-brain that Model-A (ADR-0001) avoids. The name rides in the marker; editing a group name
rewrites `name=` on each member via the marker-rewrite spine.

## Consequences
- Grammar gains optional `name=` (+ `group=` for co-authored sets); v1.0 markers (no name) auto-label
  — forward-compatible, no migration.
- Close (ADR-0010), the detail box, and the time-travel scrubber/timeline (ADR-0013) read the name.
- Group-name edits fan out to member markers; no new storage surface.
