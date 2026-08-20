# ADR-0068: A picker composes NodeRow through its existing slots

- Status: **Accepted** — 2026-08-20 (Anton). Design for #1175.
- **Amendment 1 (2026-08-20, PR #1184):** the "no change to NodeRow's contract" claim holds for the *contract* (no prop added), but one NodeRow **CSS** change did land — the reduction surfaced a latent bug (a non-clickable tree row rendered ~8px shorter than a clickable one, because the tree row's padding lived on the click button), so a picked candidate looked smaller. Fixed by pinning a NodeRow **invariant: a row's height must not depend on `clickable`** — a non-clickable tree row's text now carries the same padding the button would (dense exempt; padding is on the row there). Read "NodeRow is unchanged" below as "no new props; one CSS invariant fix."
- Concern: reducing the hand-rolled `NodePicker` onto the shared `NodeRow` / `NodeList` widgets — and, in doing so, deciding what (if anything) `NodeRow`'s contract must grow.
- Follows: ADR-0066 (a NodeList sets its density; the NodeRow adapts — the `dense` capability was landed *for this*), the UI widget taxonomy (NodeRow / NodeList + the color-system widgets; "one canonical widget per role", "one color treatment per row"), ADR-0023 (`NodePickerConfig` = sources + mechanics — the picker's config contract, unchanged here)
- Relates: #1175 (this is its design); ReferencePicker (already composes NodeRow — the precedent this generalizes)
- **Verified against `e74f7425` (2026-08-20).**

## Context

`NodePicker.svelte` is **1218 LOC** and the one picker that **hand-rolls its own row and chip markup** instead of composing `NodeRow` / `NodeList`. It re-implements, in `.ctx-item` / `.ctx-chip` CSS, four things the shared row already owns or should: kind-colour resolution (`colorStyleForRef`, `NodePicker.svelte:40`), a leading colour glyph, title rendering, and the selected/removable treatment. Every hand-rolled list is a second copy that drifts — the exact smell the widget taxonomy names ("a bespoke list that won't reduce to those widgets is the smell to question").

The reduction is now unblocked on both ends: ADR-0066 gave `NodeList` a `density="dense"` axis **explicitly for the Inputs-dialog picker column**, and **ReferencePicker — NodePicker's own parent — already composes `NodeRow` + `ViewNodeList`** for its selected refs (`ReferencePicker.svelte:204`, `:247`), grouped under a `groupHeader` row with a count pill and a `nested` list, each ref a stripe-coloured `NodeRow` with a trailing `.row-action-delete`. That is the pattern to generalise.

The through-line of this ADR: **a picker should *compose* the shared row, not grow it.** The reduction is mostly deletion; the one real question is which picker affordances, if any, justify a change to `NodeRow`'s contract — and the answer is *none*.

### What the candidate/chip rows carry today

- **Colour glyph (the "monogram").** Each candidate row shows a small rounded tile bearing the first letter of the item's sub-type, tinted with the kind/sub-type hue (`itemMonogram`, `NodePicker.svelte:399`; `--mono-bg`/`--mono-color` via colour-mix). It signals "this belongs to kind X" — the same job the `NodeRow` **stripe** does.
- **Search-term highlighting.** The title wraps matched substrings in `<mark>` (`highlightSegments`, `:534`).
- **Picked / "✓ Added" state.** An already-selected candidate renders disabled with a badge.
- **Click-to-add** as the row's primary action; **★ target-marking** on scene chips; **kind groups** with a collapse threshold (`collapseThreshold`, `:522`); **compact mode** (`compact`, `:73`) for the narrow Inputs column.

## Decision

**NodePicker renders its candidates and chips through `NodeRow` / `NodeList`, mapping every affordance onto a slot or prop `NodeRow` already has — with no change to `NodeRow`'s contract.**

1. **Delete the bespoke rows.** The `.ctx-item` candidate button (`NodePicker.svelte:683`) and the `.ctx-chip` selected strip (`:567`), their CSS, and the duplicated colour/monogram logic are removed (~330 LOC of the 1218). Candidates become `NodeRow`s in a `NodeList`; each kind group is a `groupHeader` `NodeRow` with a count pill over a `nested` list — the ReferencePicker pattern.

2. **Affordances map to `NodeRow`'s existing contract — no new per-aspect props.** This continues ADR-0066's load-bearing anti-goal (NodeRow does not grow a bag of flags):
   - **click-to-add** → `onClick`.
   - **picked / "✓ Added"** → `dimmed` + `clickable={false}` (`NodeRow.svelte:95`, `:59`) + a "✓ Added" badge supplied to the **`trailing`** slot (`:116`). No `disabled` prop is added.
   - **★ target-marking** → a caller-supplied **`trailing`** button reusing the existing `.row-action-pin` (`--star`) treatment. No target concept enters NodeRow.
   - **kind groups + collapse** → `groupHeader` (`:87`) + `nested` (`:132`) + count pill, exactly as ReferencePicker.
   - **compact** → `NodeList density="dense"` (ADR-0066). The picker's own `compact`-specific CSS is retired in favour of the density axis.

3. **The candidate drops the monogram; the stripe carries kind identity.** Kind/sub-type colour resolves to a hex (the existing `resolveColor` path stays) and is passed to `NodeRow` **`stripeColor`** (`:44`) — one colour treatment per row, matching ReferencePicker and the taxonomy's "never two colour systems on the same row". The monogram tile and its `--mono-*` colour-mix are deleted. This is an intentional visual *alignment* of the menu to the shared row, not a regression to be preserved.

4. **Search-term highlighting is dropped — the filter makes it redundant.** The menu's search *filters*: `filterByTitle` (`NodePicker.svelte:296`) removes every candidate whose title doesn't contain the query, and empty groups vanish, so every surviving row is already a match. The old `highlightSegments` (`:534`) only bolded *where* in a survivor's title the hit landed — negligible for short titles in an already-filtered list. Dropping it means **`NodeRow`'s contract does not change at all**: the whole reduction is composition through existing slots plus deletion.

5. **Picker chrome stays on NodePicker.** The portal-positioned dropdown (`use:portalToBody`, `:620`), the single menu-level search box, the live result count, keyboard/open-close handling, the trigger button, and the empty states are legitimately picker-specific and do not move.

## Why / rejected alternatives

**Extend `NodeRow` to "render the row body — monogram / colour / title / highlight / added-state"** (the shape #1175 first sketched). Rejected — that is prop-creep into the app's most-reused atom, the precise failure ADR-0066 guarded against. Every one of those affordances already has a home in an existing slot or prop; only highlighting had a claim to anything new, and that claim doesn't survive (below).

**Keep the monogram (option A).** Rejected in favour of decision 3. Two colour treatments on one row (a monogram tile *and* a stripe) violate the taxonomy; a monogram *instead* of the stripe would make the menu the one surface that signals kind differently from every other list and from its own selected chips. The stripe is the one treatment.

**Add a `titleMatch` prop to `NodeRow` to keep highlighting.** Rejected — with the search already filtering non-matches out (`filterByTitle`), highlighting only marks the matched substring within survivors, which does not earn a new prop on the shared atom. Dropping the affordance is the cleaner trade: zero contract change for a negligible loss.

**Hide already-picked candidates instead of dimming them.** Rejected — the disabled "✓ Added" row is a deliberate cue ("you already have this"); hiding it is a behaviour change, not a reduction.

## Anti-goals

- **Not NodeRow prop-bloat.** The reduction adds **zero** NodeRow props. Monogram, added-state, target-marking, grouping, and search all compose from existing slots or are dropped — nothing new lands on the shared atom.
- **Not a behavioural change to the picker.** Search, portal dropdown, grouping/collapse, ★ target-marking, compact density, click-to-add, and the `onChange {value}` payload all behave exactly as before (browser-verified — portal/dropdown surfaces need the real browser).
- **Not a redesign of the `context_pick` feature or `NodePickerConfig`.** ADR-0023's config contract is untouched; this is a pure widget reduction.
- **Not the selected-side's problem to re-solve.** ReferencePicker already renders selected refs through `NodeRow`; this only brings NodePicker's *own* chip strip (the non-`hideChips` path) onto the same pattern.
- **No pre-1.0 migration.** Presentation only; storage and wire formats are untouched.

## User journey (definition of done)

A writer opens a prompt's context picker. The candidate menu reads like every other list in the app — a left colour **stripe**, the title, grouped under **serif kind headers** with counts — no bespoke monogram tiles. Typing in the search box filters the groups down to matches; already-picked rows sit **dimmed with a ✓ Added** and can't be re-added. Picking a row adds a **chip that is itself a NodeRow** (stripe + type pill + ×), and for scenes a **★** to mark the target. In the narrow Inputs dialog the same picker is **dense**. Nothing about the picker *behaves* differently from today; it simply *is* the shared row now. `NodePicker.svelte` drops under the 1200-LOC warn line, the `.ctx-item` / `.ctx-chip` markup and CSS are gone, `svelte-check` is 0/0, and the existing NodePicker tests (snippet hide-filter, plot-source grouping, `onChange` payload + append order) still pass.

## Consequences

- **NodeRow** is unchanged — no new props; the reduction is pure composition + deletion (`highlightSegments` is retired with the `.ctx-item` markup).
- **NodePicker** sheds ~330 LOC (chip + item + group markup and CSS, plus the monogram/colour-mix logic) → back under the 1200 warn line; keeps ~880 LOC of genuine chrome.
- **The monogram is retired**; kind colour rides the stripe everywhere.
- **Consumers are unaffected** — `PromptInputField` (`:161`), `ViewFlowNode` (`:911`), and `ReferencePicker` (`:217`) call the same props; only NodePicker's internals change.
- Future picker changes ride the shared row instead of a second implementation.

## Slice plan

- **S1 — candidate rows onto NodeRow/NodeList.** Groups as `groupHeader` + `nested`; each candidate a stripe `NodeRow` with `onClick`, and `dimmed`+`clickable={false}`+a trailing ✓ for already-picked. Delete `.ctx-item` + its CSS + the monogram (`itemMonogram`, and `colorStyleForRef`'s `--mono-*` path — feed the resolved hex to `stripeColor`); retire `highlightSegments`.
- **S2 — selected chips onto NodeRow.** Stripe `NodeRow` + trailing type pill + `.row-action-delete`, and `.row-action-pin` ★ for scenes when `allow_target_marking`. Delete `.ctx-chip` + its CSS.
- **S3 — compact → dense.** Set `density="dense"` on the picker's NodeList and retire the `compact`-specific CSS in favour of the ADR-0066 axis.

Each slice keeps the existing NodePicker tests green; the final behavioural parity (portal, keyboard, grouping, ★, dense) is browser-verified.
