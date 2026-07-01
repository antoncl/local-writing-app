# ADR-0006: Lore context is resolver-mediated at the `_format_lore_block` formatter

- Status: Accepted — 0.4.0 planning, 2026-07-01
- Feature: #33 mid-scene lore mutations · Doc: `docs/design/mid-scene-lore-mutations.md` §4.2

## Decision
Resolve effective state **inside `_format_lore_block()`** (`services/ai/helpers.py`), the single
field-value choke-point where every lore entry's fields are rendered to the `<lore>…</lore>` block.
Make it `(scene, position)`-aware. Both context paths format through it:
- **explicit / one-shot** via `_relevant_lore()`;
- **implicit context** — `context_expander.py` appends detected entity **ids** (not values) to the
  session journal, formatted via `_format_lore_block()` at send.

Because the journal carries only ids, resolving at the formatter covers **explicit and implicit**
context in one place. `read_lore_entry()` and the lore page keep **base** state. Templates may
query **both** forms explicitly: `base(entity, field)` and `effective(entity, field, scene)`.

## Why / rejected alternative
Plugging only into `_relevant_lore` (the v1 draft) **misses the implicit-context path** — exactly
the mutable-metadata dependency the implicit-context design had parked as a follow-up.

A template-time per-field accessor as the *primary* mechanism was rejected: lore is pre-baked to an
XML string, not read field-by-field in templates, so resolution is a pre-bake in the formatter. The
explicit `base`/`effective` helpers are an *addition* for authors, not the main path.

Caching resolved lore on the **lore file's revision** is unsound: mutations live in **scene** files,
so a lore entry's effective value changes without its file changing — the revision-based
stable/volatile partitioning in `sessions.py` would wrongly cache it as stable.

## Consequences
- Thread `(scene, position)` into the formatter. Chat has no inherent scene, so the roleplay
  **scene-picker** (doc §6) supplies the resolution scene (default: session's current scene).
- Mutable resolved values are **cache-volatile**, keyed on the mutations-index version + the
  resolution scene, not the lore file's revision.
- EntryRef helpers (`pov`, `character_thread` — already scene-aware) share the resolver if they
  surface mutable fields; otherwise they read base. Confirm at implementation.
