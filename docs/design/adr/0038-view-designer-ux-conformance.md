# ADR-0038: View designer UX — inspector rail, uniform slots, shell zoom

- Status: Accepted — 2026-07-12 (Anton approved iteration 2: expand-in-place, params-only rail,
  leaf canonicalization, glyph-flood-as-one-pass)
- Feature: epic #218 "view designer UX conformance" (sub-issues #219-#223, mapped in §Rollout).
  Absorbs #188 (canvas too small); siblings #186 (mid-drag PUT storm) and #187 (undo/redo) join the
  epic unchanged; #215 (picker-roster intersection) and #206 (inactive-node affordance) land inside
  the surfaces this ADR defines.
- Follows: ADR-0027 (approachable flow: injectors/filters/named handles — this ADR revises its
  *presentation*, not its model), ADR-0030 (design language — the conformance target), ADR-0031/0032
  (promote-in-place parameters — generalized here), ADR-0036 ("All" lowers to the kind universe —
  enables the palette dedupe), ADR-0037 (grouping is view algebra — its Organize controls land on the
  surfaces defined here)
- Governed by: `docs/design/design-language.md` (NORMATIVE), `memory/decisions_design_language.md`,
  `memory/decisions_184_entity_vs_value_parameters.md`

## Context

The view designer works, but it reads as bolted-on: it neither looks nor behaves like the rest of the
app. The 2026-07-12 audit found the causes are structural, not cosmetic:

**1. All configuration lives inside the node bodies.** `ViewFlowNode.svelte` (891 lines, one component
for all ~17 node kinds) renders every dropdown, field editor, promote button, and parameter card
*inside* the canvas nodes. Nothing else in the app edits inline in a diagram. Consequences: nodes are
large (min/max-width 150/230px of mostly form controls), the canvas is cramped even for small flows
(#188), config UX differs per node kind, and the one component keeps absorbing every new affordance
(it is one of the design-language appendix's named worst-offender files).

**2. The stock SvelteFlow skin violates the design language directly.** `ViewBodyView.svelte:14`
imports `@xyflow/svelte/dist/style.css` wholesale, including the dotted `Background` — and §1.3 is
explicit: *the graph-paper workspace background dies; the app is a writing desk, not a whiteboard.*
The designer's own `<style>` blocks are largely token-clean already; the violation is the imported
chrome (dot grid, stock controls, stock selection/edge styling) plus stray `color: #fff` literals
(`ViewBodyView.svelte:823`, `ViewFlowNode.svelte:807`) and untokenized pixel geometry that ignores
`--ui-scale`.

**3. The palette presents the same concept twice.** The predicate leaves `type / descendants_of /
tagged / field` exist both as standalone injector nodes and as `Filter` predicate kinds; both lower
through the same `commonLeafExpr` (`viewGraph.ts:648`) and render through the same config snippets
(`ViewFlowNode.svelte:449-477`). Two palette entries, two node chromes, one meaning — the "several
kinds of injectors with overlapping functionality" complaint is this duplication.

**4. Parametrization is a special case of one slot.** Only the field-predicate value slot can promote
to a parameter (`ViewFlowNode.svelte:96-135`, `field_param` in `viewGraph.ts:246`). Type, tag, nest
join-field, highlight color, view-ref — all other config is stuck as literals. And once a view *has*
parameters, nothing shows them at a glance; they are discoverable only by hunting promoted slots
node by node.

**5. Insertion is click-to-staircase.** `addNode` places new nodes at a fixed top-left stagger
(`ViewBodyView.svelte:473-477`), ignoring viewport pan/zoom and pointer. SvelteFlow's standard
drag-from-palette pattern (`draggable` items + canvas `ondrop` + `screenToFlowPosition()`) is unused.

**6. The pane is width-starved with no relief.** The designer gets one tile of the tiled workspace;
inside it a fixed 260px preview aside squeezes the canvas further (`ViewBodyView.svelte:882`). No
maximize/zoom affordance exists anywhere in the app, and the design language sanctions no floating
fullscreen (§4: nothing floats, overlaps, or cascades).

**7. Typed value entry is wired correctly but dead inside the canvas** *(corrected 2026-07-12 after
live dogfooding — the initial audit verified the wiring, which is right, and missed that it fails
only when hosted in the canvas).* Field values do route through `FieldValueEditor` to typed widgets
(swatches, `ColoredSelect`, `TagPicker`, `ReferencePicker`), but those widgets' `position: fixed`
popovers are trapped by the transformed SvelteFlow ancestor, and the value slots lack the
`nodrag`/`stopPointerdown` wrapper — so the pickers render and do nothing. Exactly one widget got
the full treatment (the `hand_picked` NodePicker: body-portal + `nodrag`, `ViewFlowNode.svelte:559`,
`NodePicker.svelte:668`); the rest degrade to typing CSV into text inputs. Filed as #225 (dead
pickers — fixed by portaling the widgets to `<body>` + wrapping the value slots in
`nodrag`/`stopPointerdown`; a prerequisite of §A's expand-in-place editing, see §A) and #226 (the
intrinsic `entry_type` value renders as raw text although the set is closed; home: §C/#222). The
remaining residue: `inferInputKind` feeds the *field* pickers but not the *tag/type/hand-picked*
rosters (#215's territory).

## Decision

### A. Nodes are compact at rest and edit in place; the rail is view-level only

*(Revised after Anton's red-pen, 2026-07-12. The first draft put all config in a selection-scoped
inspector rail. That was rejected: it forces the eye off the node being edited to the far side of the
pane on every interaction — a real ergonomic cost — and the size pressure that motivated the rail is
not uniform. Set ops are glyph-only nodes (§G) and already tiny; the bloat is concentrated in a few
kinds. So config editing stays local to the node; the rail shrinks to the one thing that is genuinely
a whole-view concern — the Parameters overview.)*

**At rest, every node is compact:** glyph + title + ports + a one-line value summary (e.g.
`Filter · status ∈ {draft, revised}`), stripe-colored by payload kind as today. Set ops are
glyph-only (∪ ∩ − ∁), carrying no config, so they never grow.

**Editing happens in place: the selected node expands to reveal its config, right where it sits.**
Focus never leaves the node. Only the selected node is expanded; everything you are not editing stays
compact, so the canvas-footprint win holds. An expanded node uses the same field-row atoms, caps-label
sections, and standard input treatment the rest of the app uses — it is the *node* that changes size
on selection, not a separate surface that config migrates to.

`ViewFlowNode.svelte` decomposes along the way: the compact summary is the resting body; each kind's
config editor becomes its own component rendered only in the expanded state — which is also how the
file gets back under the size cap and off the worst-offender list. The preview aside becomes
**collapsible** (default open, fold state on the view node's `/ui` per ADR-0036).

The #206 inactive/unbound affordance lands on the node itself: an unbound-parameter or inactive node
shows a quiet tint at rest and a plain-words explanation in its expanded body.

**Consequence for #225 (dead pickers):** expand-in-place keeps the value widgets hosted inside the
SvelteFlow-transformed node, so — unlike the rejected rail — it does **not** fix the trapped
`position: fixed` popovers for free. The pickers must be portaled to `<body>` (exactly as NodePicker
already does, `NodePicker.svelte:668`) and the value slots wrapped in `nodrag`/`stopPointerdown`.
That is the correct fix regardless of surface, and #225 already scopes it; it is now a prerequisite of
this slice rather than a side effect of the rail.

### B. The palette is sources vs operations; duplicate leaves retire from the palette

The palette reorganizes around the algebra:

- **Sources** — All, Hand-picked, View ref, This entry (`$self`).
- **Operations** — Filter (predicate picker inside), Field of, set ops (∪ ∩ −  ∁), Arrange
  (sorter / highlight / nest).

The standalone `type / descendants_of / tagged / field` **leaf nodes leave the palette**. The grammar
keeps accepting them indefinitely (saved views must reopen), but new authoring composes `All → Filter`
— identical lowering, one UI path. Post-ADR-0036 `All` is a real kind universe, so nothing is lost.
The palette becomes a proper grouped surface (caps-label groups, one-line items with kind glyphs)
instead of inline toolbar buttons.

**Canonicalize on open (Anton's red-pen, 2026-07-12).** Retiring the leaves from the palette
interacts with ADR-0036's system-default views, which are *copyable-but-read-only*: the user
duplicates a default and edits the copy. A default (or any older saved view) authored with a bare
`type`/`tagged`/`field` leaf would, on open, restore a node the palette can no longer produce — the
user sees vocabulary they cannot recreate, and the "duplicate a default to learn how you'd build it"
intent breaks. So **`specToGraph` normalizes any bare predicate leaf into the `All → Filter` form on
open.** It is lossless — both forms already lower through the same `commonLeafExpr`, so the resolved
spec is byte-identical — and it repairs *every* reopened view, not only the defaults. Paired
requirement: the **shipped default-view specs are authored in the `All → Filter` idiom** from the
start, so a fresh duplicate matches the palette without leaning on the normalizer. (The normalizer is
the safety net for pre-existing user views; the authored defaults are the primary fix.)

### C. Every config slot follows one model: literal | promoted formal | wired source

The three fill modes the field value slot already has (ADR-0031/0032) become **the uniform slot
model**. Every configurable slot — type, tag, field value, nest join-field, highlight color, sort
field, view-ref — renders in the expanded node (§A) as the same slot row: its typed widget, plus a
promote affordance (`field_param` generalizes to a per-slot `param`), plus a wire indicator where the
slot's payload type admits wiring (value-set/node-set slots only; a color slot promotes but never
wires). Promotion keeps ADR-0032 semantics exactly: authored literal becomes the overridable default;
`collectParams` walks slots generically instead of special-casing the field predicate.

### D. Parameters at a glance: the rail's one job

The rail (§A) is **not** where per-node config lives — that edits in place. Its sole content is the
view-level **Parameters** overview, which is inherently a whole-view question ("what parameters does
this view expose?") rather than a per-node one, so a persistent reference surface fits it and costs no
mid-edit focus shuttle. It lists every formal with its label, inferred type, default, and bound/unbound
state; each row navigates to (and expands) the owning node on click. This is the at-a-glance surface
(the "d" ask) and the management surface for §C. Runtime *binding* stays where ADR-0032 put it — the
render surface's param strip (#182/#199); the rail edits declarations, never ephemeral bindings. When a
view has no parameters the rail is empty/collapsed — it never becomes a dumping ground for node config.

### E. Insertion is drag-and-drop; click remains as fallback

Palette items become drag sources; the canvas accepts drops at the pointer via
`screenToFlowPosition()`. Click-to-insert stays (accessibility + speed) but places at the **viewport
center**, not the fixed staircase. (SvelteFlow edge/canvas behavior cannot be verified in the
headless preview — this slice needs a human eyeball on the testbench.)

### F. Zoom is a shell affordance, not an editor feature

A **zoom toggle on `workspaceLayout`**: zoom maximizes the active tab's tile to the full workspace;
toggling back restores the exact prior layout (the split tree is retained, not rebuilt — tmux-zoom
semantics). Because it lives in the shell, *every* editor and region inherits it for free, satisfying
"then all editors should support it" by construction. Surface budget: a glyph in the pane title row +
a keyboard shortcut; the design language §4 shell contract gets a one-paragraph amendment sanctioning
zoom as a shell affordance (a zoomed tile still fills edge-to-edge; nothing floats). Zoom state is
ephemeral (not persisted in saved layouts).

### G. The skin becomes the house skin

- The dotted `Background` component is removed; the canvas is flat `--board` (§1.3).
- SvelteFlow chrome (controls, selection, edges, handles) restyles onto tokens via the existing
  `:global(.svelte-flow__…)` seam; the stock stylesheet stays imported for layout/behavior only.
- Node geometry (widths, port sizes, radii, gaps) moves onto `--sp-*` / `--r-*` so `--ui-scale`
  reaches the designer; `#fff` literals die.
- Glyph affordances follow the lexicon (§4): `+` under labeled palette groups, `⋯` for node menus,
  words for anything without an agreed glyph. Edge/port marks stay a sanctioned domain toolbar
  exception where no lexicon glyph carries the meaning.

**Anticipate a glyph flood — handle it as one deliberate amendment, not slice-by-slice drift.** The
design language grows the lexicon one mark at a time, by PR; this epic wants a whole batch at once —
source/operation node marks, the Venn set ops (∪ ∩ − ∁), the §F zoom glyph, node expand/collapse, a
drag handle (`⋮⋮`), possibly a "flooded" summary/overflow mark. Introducing those ad-hoc across five
slices is precisely the drift §4 guards against. So the glyph work is a **single lexicon pass**: audit
the full set the designer needs up front, split it cleanly into (a) **general marks that earn a place
in the global §4 lexicon** (zoom, expand/collapse, drag handle — reusable app-wide, so amend the doc
table once) and (b) **domain marks that stay a self-contained designer toolbar exception** (Venn set
ops, edge/port/direction marks — they mean something no global glyph should carry, exactly the §4
"domain toolbars" clause). Some already exist and are reused, not reinvented (`ViewGlyph` ships
`⇒`/`◉` for `field_of`/`$self`). Anything without a self-evident mark stays a **word until a glyph is
agreed** — the flood is not a licence to coin glyphs under deadline. Net: one design-language
amendment PR lands the (a) set with the §F zoom glyph; the (b) set lives and is documented in the
designer itself.

## Rejected

- **Floating fullscreen / F11 overlay for the designer** — violates the shell law (§4). Zoom-a-tile
  delivers the same room inside the tiled contract, for every editor at once.
- **All config in a selection-scoped inspector rail** (the first draft's §A) — rejected on Anton's
  red-pen: it forces the eye off the edited node to the far side of the pane on every interaction, and
  the size pressure it solved is not uniform (glyph-only set ops are already tiny). Expand-in-place
  keeps focus local and still compacts the resting canvas; the rail survives only as the view-level
  Parameters overview (§D).
- **Keeping config inline in fixed-size nodes and just restyling** — restyling alone doesn't fix the
  cramped canvas, per-kind inconsistency, or the monolith. Expand-in-place (compact at rest, full
  config only when selected) is the middle path: local focus *and* a small resting footprint.
- **Removing the duplicate leaves from the grammar** — pure churn; saved views would need rewriting
  for zero expressive gain. Palette-level retirement gets the UX win at no compat cost.
- **A separate "parameter node" on the canvas** (declared-source style) — stays deferred as before
  (ADR-0031); promote-in-place + the Parameters rail section covers declaration and visibility.
- **Replacing SvelteFlow** — the library is fine; only its default skin conflicts.

## Consequences & rollout

Pulled into 0.7.0 (2026-07-12, Anton's call) to land with the rest of the views work now that #213
has merged to master (merge `1be1ee7`) — the file-collision gate that held §A-§G is lifted. The
build order stands regardless:

1. **§F shell zoom** (#219 — workspace files only, `workspaceLayout.svelte.ts` / `WorkspaceNode.svelte`;
   no designer files, so independent of the rest).
2. In order: **§A rail + compact nodes** (#220, the substrate; folds in the collapsible preview and
   the #206 affordance) → **§B palette + §E drag-and-drop** (#221) → **§C/§D uniform slots +
   Parameters section** (#222) → **§G skin/token pass** (#223 — last, so it styles the final
   structure; the same restyle-after-shell ordering ADR-0030 used).

#186 (PUT storm) and #187 (undo/redo) are independent epic members, schedulable any time after #213.
#188 is expected to close with §F + §A. Each slice runs the standard gates and gets a testbench
eyeball in both themes; SvelteFlow edge rendering is verified by hand, not the headless pane.

The conformance test for the epic: open the designer next to Lore and Draft — if you can't tell which
surface was "bolted on", it's done.
