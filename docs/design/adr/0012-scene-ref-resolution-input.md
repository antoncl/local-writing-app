# ADR-0012: Resolution scene is a `scene_ref` prompt input

- Status: Accepted (v1.1) — 0.4.0, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `mid-scene-lore-mutations-v1.1.md` §3 · Issue: #60
- Related: `memory/decisions_inputs_fields_uniformity.md`, v1.0 doc §4.2/§6

## Decision
The roleplay prompt gains an **optional single-select `scene_ref` input** naming the scene whose
effective state to resolve against. This adds a new literal to `PromptInputType` (backend
`models.py` + frontend `types.ts`), reusing the existing `NodePicker` constrained to
`{ kinds: ["scene"] }` as its widget. It is **not** an overload of `context_pick`.

The picked scene threads into `_format_lore_block(scene=…)`, so it drives resolution for **both** the
explicit lore block and the implicit/chat journal path (whose entries carry only ids and so need an
external resolution scene). Defaults to the session's **current/anchored scene**; a general chat with
no anchored scene resolves at **end-of-book** (unrestricted — a non-manuscript chat isn't
redaction-sensitive).

## Why / rejected alternative
Rejected overloading `context_pick`: its semantics are "collect items and *inject* them into the
context envelope" (plural, additive). A resolution scene is a **setting** — a point to resolve *at*,
not content to inject. Overloading would blur that and complicate `context_pick`'s expansion logic.
A dedicated single-select ref type keeps each input type's meaning clean, consistent with
inputs/fields-uniformity (same widget per ref type, distinct types for distinct semantics).

## Consequences
- One new prompt input type; no new prompt (keeps the catalog small per `decisions_prompt_model`).
- Verification ("your rank as of scene 5?") rides for free on the resolver — most interesting once
  interval close (ADR-0010) exists, hence v1.1.
- Unblocks the per-scene effective-name resolution the matcher needs (ADR-0008 amended).
