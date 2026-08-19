# ADR-0066: A NodeList sets its density; the NodeRow adapts

- Status: **Accepted** — 2026-08-19 (Anton). Ratifies the direction settled over five live mockup rounds.
- Concern: the NodeRow / NodeList density overhaul (this ADR is its design). Gates #1175 (the NodePicker widget-taxonomy reduction), which is out of scope here.
- Follows: ADR-0030 (the design language — "a quiet writing desk"; the kind-stripe and serif=the-work / sans=the-tool contract), the UI widget taxonomy (NodeRow / NodeList / NodeEditor + the color-system widgets), ADR-0064 (FieldValue — the field-level display citizen a NodeRow may host)
- Relates: #1175 (NodePicker reduction — unblocked by this, not done here)
- Mockup at [`../mockups/0066-node-widget-density.html`](../mockups/0066-node-widget-density.html) (iterated live with Anton over five rounds; the rejected turns below are its record)
- **Verified against `ad6a1ed9` (2026-08-19).**

## Context

Everything in the app reduces to a **NodeRow** in a **NodeList** — the manuscript tree, every lore/prompt/assistant list, the pickers. The app shipped the **Editorial Card** direction (ADR-0030's node-widget pass): discrete rounded cards, gentle elevation, serif group headers, tags as pills, a soft-rounded inset kind-stripe. It reads beautifully on a flat lore list. It over-pays in density and hierarchy the moment it is forced into a **dense list, a deep tree, or a picker**. Three concrete symptoms, in the current widget:

- **Tags give up early.** The visible cap is a fixed integer — `TAG_VISIBLE_MAX = 2` (`NodeRow.svelte:161`), applied width-blind: `visibleTags = tags.slice(0, TAG_VISIBLE_MAX)` (`:169`), the rest collapsed to a `+N` chip (`:170`). A wide row still shows two pills and a count over empty space.
- **Rows are tall no matter how little they hold.** A card is `padding: 11px 14px` with a `--fs-lg` (15px) title (`.node-row-text strong`, `NodeRow.svelte:334`); height is content-derived with no `min-height`, but the padding and title size are fixed, so a bare-title row reserves the same slice as a title-plus-detail-plus-tags one.
- **The tree reads upside-down.** A group-header title is `--fs-md` **serif** (13px) — `.node-row.group-header … strong` at `NodeRow.svelte:481`, `font-family: var(--serif)` `:482`, `font-size: var(--fs-md)` `:483` — sitting over leaf titles that are `--fs-lg` **sans** (15px, `:334`). The frame is literally 2px smaller than the leaves it contains. Indent is `depth * 14px` (`indentStyle`, `:163`); children nest in `--tier1/2/3` panels.

The kind-stripe today is the app's **inset band** clipped by the row's rounded corners so it curves at top and bottom — `box-shadow: inset 4px 0 0 0 var(--row-stripe)` (`NodeRow.svelte:256` card, `:291` tree). That treatment is right and stays; it is named here because the overhaul must keep it, not replace it.

The through-line: **the Editorial Card is one point on a density scale that the widget never had.** Everything below gives it that scale without turning NodeRow into a pile of per-aspect flags.

## Decision

**A NodeList sets a density; the NodeRow adapts to it.** Density is the list's call, read by the row the same way layout mode already is — never a bag of booleans on the row.

1. **Density is a NodeList axis, orthogonal to layout `mode`.** `mode: "card" | "tree"` (`NodeList.svelte:39`) stays the **layout** axis (flat cards vs. indented tree). A **new density axis — comfortable · compact · dense** — is set on the NodeList and provided to rows by context, exactly as `nodeListMode` is today (`effectiveMode`, `NodeRow.svelte:168`). A flat lore list stays *comfortable*; a deep tree or an Inputs picker asks for *compact* or *dense*. The two axes compose (a tree can be dense; a card list can be dense) — density never implies a layout.
   - *P7 flag for the implementer:* `density` is already a **local** `$derived` in `ListValueEditor.svelte:43` for a different, shape-derived concept (`"record" | "longtext" | "flat"`). The NodeList axis must not collide — pick a non-clashing prop name (or reconcile the two deliberately), don't silently reuse the word.

2. **Tags pack to the available width; the fixed cap is retired.** Replace `TAG_VISIBLE_MAX`-slicing with a width-aware pack: fill the tag line, and show `+N` only for the genuine remainder. The layout law (already implicit in the taxonomy's "affordances are right-aligned"): **pills grow left→right, the trailing affordances grow right→left**, and `+N` sits where they would meet. On a **two-line card** the tag line runs the **full width below** the title while the affordances sit on the title line — so the reserve-for-affordances case is **single-line only**, not a general constraint.

3. **The frame outweighs its leaves.** A group-header (frame) title steps **up** to `--fs-xl` serif with a trailing **count**; nested leaves **recede** to `--fs-md` and `--text-2`; children carry **indent + a stronger tier tint**, and the dark-theme `--tier` steps are **widened** (they sit ~3% off the surface today and read as invisible in dark). This all lives **inside one NodeRow** via `groupHeader` — no separate header widget — honouring "every tree node is a real Node" (the tree-uniformity rule).

4. **One kind-stripe rule, at every density.** A **member** row carries the app's **curved inset stripe** (`inset 4px 0 0 0 var(--row-stripe)`, clipped by the row's rounded corners so it curves top and bottom); a **group header** (the frame) carries **none** — that is the whole of "when does a strip show." A **dense row is just a tighter rounded card**, so the identical stripe curves along its corners; there is **no** second stripe object. Dense also **drops the horizontal row dividers** — the stripe and row rhythm do the separating.

5. **Density lives on the list; the row grows no density flags.** The NodeRow reads a single density value from context and adapts. It does **not** gain per-aspect boolean props. This is the load-bearing anti-goal — it is what keeps NodeRow one adaptive widget instead of a fork.

## Why / rejected alternatives

**Per-aspect density props on NodeRow** (a `compact`, a `dense`, a `hideTags`, …). Rejected — that is the mode-flag soup the taxonomy warns against, and two lists would drift the moment they set the flags differently. NodeRow already resolves layout from a single context value (`effectiveMode`); density follows the same one-value path. *Density is one axis chosen once per list — not N knobs per row.*

**A `variant` per row for density.** Rejected for the same reason, and it repeats a mistake already being unwound: the legacy `variant` prop on NodeRow (`:57`) is deprecated precisely in favour of setting the axis once on the NodeList.

**A capsule / pill stripe.** Rejected — the app's stripe is the **corner-following inset band**; a floating rounded capsule is a *second, different* stripe object, and it never fit the paradigm. (Tried in the mockup as a way to make the dense stripe "curved"; the real fix is that a dense row is a rounded card, so the existing inset stripe curves for free.)

**A schematic-outline tree** (literal `├─└─` connectors, mono `[count]`). Rejected — a structural-inspector idiom that fights the quiet-writing-desk. (Tried in the mockup; dropped on sight.)

**Keep `TAG_VISIBLE_MAX`'s fixed cap.** Rejected — it wastes horizontal space the width-aware pack reclaims, and the count is meaningless when pills would fit.

## Anti-goals

- **This is the density/hierarchy overhaul — not the NodePicker reduction.** #1175 (folding the hand-rolled NodePicker onto shared NodeRow/NodeList) is a **separate pass** this ADR *unblocks*; it is not designed here, and no mechanism for it is reserved (per the deferral discipline — record that it is out of scope, do not sketch how it slots in).
- **Not new per-type field display.** How a *value* renders is ADR-0064 (`FieldValue`); a NodeRow may *host* a `FieldValue` as a detail, unchanged by this.
- **Not a schematic / structural-inspector tree.** The tree stays the typographic nest.
- **Not density-as-a-row-prop.** Density is a NodeList setting; a row that takes density booleans is the failure this ADR exists to prevent.
- **No pre-1.0 migration.** Presentation only — storage is untouched.

## User journey (definition of done)

A writer opens a deep character tree in a *compact* NodeList: the group header reads first — larger serif, a count — and its leaves recede and indent under a tint that is legible in dark; a flat lore list beside it stays *comfortable*, unchanged from today. They open the Inputs picker (*dense*): rows are tight single-line rounded cards, each with the same curved kind-stripe, no dividers between them; a row's tags **pack to the width** instead of always reading "two and +3". Nowhere does a header read quieter than its own leaves, and nowhere is there a capsule or a square stripe. A second pane built by a cold session gets the same behaviour by setting one density value on its NodeList — it never touches NodeRow.

## Consequences

- **NodeList** gains a density axis, provided to rows by context beside `mode`; **NodeRow** reads it (one value) and adapts padding, title size, and tag/stripe treatment.
- **`TAG_VISIBLE_MAX`** (`NodeRow.svelte:161`) is retired for a width-aware pack; the two-line card's tag line runs full width.
- **Group-header** typography gains a step-up + count; **nested leaves** recede; children gain indent + a stronger tint; the **dark `--tier` tokens are widened**.
- **One stripe recipe** (the curved inset) spans all densities; a dense row is a tighter rounded card; dense drops dividers.
- **#1175 unblocks** once this lands — the NodePicker reduction can target rows whose contract is settled.

## Slice plan

- **S1 — density axis.** Add the density setting to NodeList and have NodeRow read it (comfortable = today's look; no visible change). Establishes the one-value path.
- **S2 — width-aware tag packing.** Retire `TAG_VISIBLE_MAX`; pack to the tag line's width with a true-remainder `+N`.
- **S3 — the tree fix.** Frame typography + count, leaf recession, child indent + tint, widened dark tiers.
- **S4 — the dense step.** Tighter rounded cards, the one curved-stripe rule, no dividers.

Then, separately and behind approval, **#1175** reduces NodePicker onto the settled rows.
