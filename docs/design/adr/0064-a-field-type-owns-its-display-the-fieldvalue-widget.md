# ADR-0064: A field type owns its read-only display — the FieldValue widget

- Status: **Proposed** — 2026-08-17. Awaiting Anton.
- Issue: #1108 · Pre-1.0 (no release milestone)
- Follows: the inputs/fields-uniformity rule (the *same edit widget per type* across a definition default, options, and the runtime value — GH #40/#36), ADR-0029 (the field model; presentation ops are category-independent), the UI widget taxonomy (NodeRow / NodeList / NodeEditor + the color-system widgets)
- Relates: ADR-0046 / ADR-0044 (the entry-patch diff review already reuses the rail's read-only field widgets)
- **Verified against `f0c20603` (2026-08-17).**

## Context

A field value's read-only *appearance* is re-decided per surface. The type-aware rendering — a `select` as a tinted pill, a `boolean` as a tri-state toggle, a `color` as a swatch, an `entity_ref` as its title, `tags` as chips — exists in **exactly one place**: the read-only branches of `FieldValueEditor.svelte` (used by the metadata rail, and reused by chat's *structured* diff review). `FieldValueEditor`'s own docstring already states the principle: *"each type renders a static display through the same widget vocabulary — never a raw string dump."*

But that renderer produces DOM, and it isn't a standalone widget — so the surfaces that don't reach the rail fall back to a **type-blind** `metadataValueDisplayString` and lose the formatting:

- the chat **create-draft card** (`EntryDraftCard`) renders a plain `<dl>` — a `select` shows its raw value, an `entity_ref` shows the id, a `boolean` shows `true`;
- the **drift / snapshot report** (`DriftReport`) does the same.

So the same value looks like a coloured pill in the rail and like `true` two panes over. This is the read-side gap in a uniformity the app already keeps on the *edit* side: field *editing* has one widget per type everywhere; field *display* does not.

**Scope: UI uniformity only.** The value→text-for-the-AI path (a value rendered inside a Jinja template for the model) is a **different, harder concern** — backend, two-runtime — and is explicitly out of this ADR.

## Decision

**A field type owns its read-only display, as a canonical widget.** Extract the type-aware read-only rendering out of `FieldValueEditor` into a standalone **`FieldValue`** widget, and render every UI surface through it.

1. **`FieldValue` is a canonical widget — the field-level display citizen.** It joins the taxonomy as the *display* sibling of `FieldValueEditor` (edit), exactly as **NodeRow** (display) sits beside **NodeEditor** (edit) at the node level.
2. **`FieldValue` is a type dispatcher, not a leaf.** Per `field.type` it delegates to the color-system widgets that already exist — `select`→ColoredSelect pill, `tags`→TagChip, `color`→SwatchPicker, `boolean`→ToggleSwitch (disabled, tri-state), `entity_ref`→the resolved title, `long_text`/`number`/`text`→static text. Each field type "renders itself" *through* `FieldValue`; no surface re-implements a type.
3. **Every UI surface renders field values through `FieldValue`.** The rail and chat's structured diff already do (via `FieldValueEditor` read-only) and become the reference. The divergent surfaces — `EntryDraftCard` and `DriftReport` — stop calling `metadataValueDisplayString` and render `FieldValue` instead.
4. **`FieldValue` is context-aware, not surface-bespoke.** It may take a density/context hint (a NodeRow detail wants a compact form; the rail wants the full one) — but the *type* owns how it adapts; the surface only passes context. That is what keeps "each node decides the appearance" from creeping back in.
5. **Selection stays with the surface; formatting moves to the type.** *Which* fields a row or panel surfaces remains the surface's choice; *how each value looks* is the type's. A pane still picks its fields; it stops hand-formatting them.

## Why / rejected alternatives

**Leave the read-only rendering inside `FieldValueEditor`.** Rejected — it's DOM trapped inside an *editor* component, so the non-rail surfaces can't reach it and re-derive the value type-blind. A standalone widget is what makes "render it the same everywhere" possible; it's also the honest taxonomy shape (display and edit are separate widgets at the node level; they should be at the field level).

**Keep the type-blind `metadataValueDisplayString` for the "simple" surfaces.** Rejected — that helper *is* the divergence: it drops select labels, swatch names, ref titles, and boolean tri-state, so the same field disagrees with itself across panes.

**Let each surface (or each node type) keep deciding the appearance.** Rejected — that's the fragmentation. Legitimate per-surface variation is *field selection* and *density* (both preserved: selection stays with the surface, density is a context hint the type honours), never per-surface *formatting*.

## Anti-goals

- **Not the Jinja/text unification.** A value's text form for the AI is out of scope — a separate concern with a two-runtime cost. `FieldValue` is a Svelte widget; it serves UI surfaces only.
- **Not a NodeRow rewrite.** NodeRow renders no field values today; it simply gains `FieldValue` as a *hostable* detail. Whether a pane surfaces a field on a row stays that pane's call.
- **Not a new per-type rendering.** The type→widget logic already exists in `FieldValueEditor`; this extracts and shares it, it does not re-author it.
- **No pre-1.0 migration** — a frontend refactor; storage is untouched.

## User journey

A writer commits a brainstorm that proposes a new character. The create-draft card shows *Status: **Alive*** as the same tinted pill they'd see in the rail, *Deceased: (a greyed toggle)* rather than `false`, and *Mentor: **Gandalf*** as the title rather than a raw id — because the card renders `FieldValue`, not a string. Later they open the drift report on a snapshot; a changed `select` reads as the pill on both sides of the flip, matching the rail exactly. Nothing in the app shows the same field value two different ways.

## Consequences

- **`FieldValue.svelte`** is added as a canonical widget (extracted from `FieldValueEditor`'s read-only branches); `FieldValueEditor` becomes the *edit* sibling and may compose `FieldValue` for its own read-only mode.
- **`EntryDraftCard` and `DriftReport`** render `FieldValue` instead of `metadataValueDisplayString`; the type-blind helper is retired from the UI (it may remain only where a genuine plain string is still required outside this scope).
- **NodeRow** gains `FieldValue` as a hostable detail — enabling, not forcing, per-type field display on rows.
- The metadata rail and chat's structured review are unchanged behaviourally (they already render the type-aware widgets; they now do it through the named citizen).

## Slice plan

- **S1 — extract `FieldValue`.** Lift the read-only type-dispatch out of `FieldValueEditor` into `FieldValue.svelte`; `FieldValueEditor` (and the rail) render through it. No visible change.
- **S2 — converge the stragglers.** `EntryDraftCard` and `DriftReport` render `FieldValue`; retire their `metadataValueDisplayString` calls.
- **S3 — expose for rows.** Make `FieldValue` available in NodeRow's detail slot (context/density hint), for panes that want per-type field display on a row.
