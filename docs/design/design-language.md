# The design language — a quiet writing desk

Status: Normative from 0.6.0 (#124). Decision record: ADR-0030.
Governs every UI change from 0.6.0 on; the restyle pass (#125) migrates the
existing surfaces onto it. Interaction/structure law consolidated here was
established in the widget-taxonomy, NodeEditor-body-spec, and metadata-revision
memos; this document promotes it into the repo and adds the visual token layer
those memos never defined.

---

## 1. Identity

**The app is a writing desk, not a whiteboard.** Everything on screen is either
*the work* (manuscript, lore, notes — the things the writer made) or *the tool*
(chrome that hosts the work). The design has two voices for the two:

- **The work speaks serif.** `--serif` (Newsreader) marks *editorial* moments:
  document titles, group/section headers, the reading surface. Serif = "this is
  yours."
- **The tool speaks sans.** `--sans` (Inter) for every control, label, input,
  and affordance. The tool's job is to recede: small, quiet, consistent.

Three consequences that decide most day-to-day questions:

1. **The manuscript is the loudest thing on screen.** No piece of chrome may be
   visually heavier than the content it hosts. When in doubt, remove weight from
   the tool, never add weight to compete.
2. **Density first** (carried from the widget taxonomy): single-line layouts by
   default; vertical space is spent on the work, not on chrome or breathing
   room around chrome.
3. **Calm over clever.** No decoration that doesn't encode information. The
   graph-paper workspace background dies in 0.6.0 — the workspace is a flat
   `--board` surface. Color always *means* something (kind, status, ownership);
   it is never garnish.

## 2. Tokens

The single source of visual truth. **Every component style consults tokens;
raw literals are defects.** This `:root` block lands with #125 phase 1 (values
tunable in review; *structure* is the contract):

```css
:root {
  /* — type scale — seven sizes, no fractional px, nothing else — */
  --fs-xs:  11px;   /* caps-labels, keycaps, fine meta */
  --fs-sm:  12px;   /* secondary UI: detail lines, chips, hints */
  --fs-md:  13px;   /* DEFAULT UI: buttons, rows, inputs, menus */
  --fs-lg:  15px;   /* emphasized UI: pane titles, dialog headings */
  --fs-xl:  18px;   /* serif display: group headers, rail sections */
  --fs-2xl: 24px;   /* serif display: document title in the editor */
  --fs-prose: 16px; /* the reading/writing surface (prose bodies) */

  /* — families & weights — */
  --sans:  'Inter', ui-sans-serif, system-ui, sans-serif;
  --serif: 'Newsreader', 'Iowan Old Style', Georgia, serif;
  --mono:  'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
  --w-regular: 400; --w-medium: 500; --w-semibold: 600; --w-bold: 700;
  /* 800 is retired. Display serif carries 700 max. */

  /* — spacing — the only seven gaps/pads/margins that exist — */
  --sp-0: 2px;  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px;
  --sp-4: 16px; --sp-5: 24px; --sp-6: 32px;

  /* — radius — */
  --r-sm: 4px;    /* inputs, chips, keycaps, small buttons */
  --r-md: 6px;    /* buttons, rows, cards */
  --r-lg: 10px;   /* panes, dialogs, popovers */
  --r-pill: 999px;

  /* — elevation — background + border + shadow travel together — */
  --elev-1: /* raised: hover states, dropdowns   */ var(--shadow);
  --elev-2: /* floating: popovers, pinned panes  */ var(--shadow2);
  --elev-3: /* modal: dialogs, command surfaces  */ var(--shadow-pane);
  /* level 0 is flat: border only, no shadow. Raw rgba() shadows are defects. */

  /* — z-layers — six layers, nothing between them — */
  --z-base: 0; --z-sticky: 10; --z-dropdown: 100;
  --z-overlay: 200; --z-modal: 300; --z-toast: 400;

  /* — motion — two durations, one easing, one exception — */
  --t-fast: 80ms linear;     /* color/opacity feedback (hover, focus) */
  --t-base: 160ms ease-out;  /* reveal, expand, slide */
  /* the AI spinner keeps its own animation; honor prefers-reduced-motion
     by disabling --t-base transitions, keeping --t-fast feedback. */
}
```

**Color roles are already tokenized and stay** — `--app-bg / --board / --panel /
--surface / --inset`, `--text`/`--text-2`/`--text-3`, `--border`/`--divider`,
the `--accent` family, `--danger`, `--star` (gold), the `--k-*` kind colors,
and the `--tier1..3` recess ladder. Two corrections:

- **The `--ctx-*` parallel palette (17 tokens) folds into the global roles.**
  The context picker is not a separate visual universe; a popover is `--panel`
  at `--elev-2` wherever it appears.
- **Gold keeps exactly one meaning: the pin** (plus the sanctioned prose-TODO
  anchor, per the NodeEditor body spec). This rule has held since the taxonomy
  memo; the token layer makes it checkable.

## 3. Composition law

Consolidated from the standing memos — now repo-canonical:

1. **Three widgets render every node**: NodeRow (one node in a list), NodeList
   (many rows; search; empty state), NodeEditor (one node's editor: title,
   rail, body). New features compose these; extending a widget beats forking
   it; a bespoke list is the smell to question.
2. **Color attaches to the largest unit it scopes.** Whole row → stripe. Editor
   body → body-stripe. Inline token → chip. Free-floating label → dot. Never
   two color systems on one row.
3. **Affordances are right-aligned and reveal on hover.** Destructive actions
   live on the list row, not inside the item editor.
4. **NodeRows nest**; indent is `--depth * 14px`; a row that owns a card-mode
   child list takes the serif header voice — that's a consequence, not a
   category.
5. **One field-row atom in the rail.** A metadata field renders as exactly one
   row: icon, label, value/control, trailing affordance. Reference fields do
   not render a second serif header row — count and `+ Add` live on the single
   row. (Fixes the current double-render; per the metadata-revision memo.)

## 4. Component rules

**Buttons.** Two sizes: `sm` (`--fs-xs`, `--sp-0` `--sp-2` padding — row and
header affordances) and `md` (`--fs-md`, `--sp-1` `--sp-3` — everything else).
Three variants: `ghost` (no border, hover surface — default inside rows and
toolbars), `outline` (border, transparent — default standalone action),
`solid` (accent — at most one per surface, the primary action). `danger` is a
modifier on any variant, never a fourth style. The current mix of 12/13/16px
buttons for identical jobs converges here.

**Icon-only controls carry meaning, not puzzles.** Every icon-only button has
an `aria-label` and tooltip. Cryptic ASCII compounds (`+>`) are retired —
an affordance is either a recognizable single glyph (`+`, `×`, `⋯`, `⋮⋮`) or
it gets a word.

**Caps-labels** (rail sections, `TITLE`, fine print): one recipe —
`--fs-xs`, `--w-semibold`, `letter-spacing: 0.07em`, `text-transform:
uppercase`, `--text-3`. The ~35 local re-implementations converge on it.

**Inputs** sit on `--inset`, `--r-sm`, `--fs-md`; focus is a 1px `--accent`
ring via `--t-fast`. The search keycap badge (`Ctrl+F`) hides below ~220px of
input width instead of crowding the placeholder.

**Popovers/dialogs** are `--panel`, `--r-lg`, `--elev-2/3`, `--z-dropdown/
modal`. No component defines its own private palette again.

**The shell** (normative for #32): the workspace is a **tiled layout, not a
canvas** — regions fill it edge to edge; nothing floats, nothing overlaps,
nothing cascades. The editor is the primary region; lists are satellites. Pane
chrome budget: one `--fs-lg` title row per region, affordances right-aligned
in it; no per-pane move buttons, no corner resize grips (splitters between
regions instead). Empty space belongs *inside* regions (breathing room around
content), never *between* them (dead board).

## 5. Adding UI — the checklist

Before a PR with visual changes is done:

1. Is every node-list a NodeList of NodeRows, every editor a NodeEditor? (§3.1)
2. Do all values come from tokens — type, space, radius, shadow, z, motion,
   color? `grep` your diff for `px`, `#`, `rgba(` in style blocks: hits must
   be token definitions or documented exceptions.
3. Is color scoped to its largest unit, and is nothing gold but the pin? (§3.2)
4. Are icon-only buttons labeled, affordances right-aligned/hover-revealed? (§4)
5. Single-line first — did anything gain a second line that isn't unbounded
   content? (§1.2)
6. Both themes eyeballed (`data-theme="dark"` + light), and `npm run check`
   clean.

Enforcement note: once #125 phase 1 lands, the file-edit hook gains a style
lint (hex/rgb literals + non-token `font-size` in `.svelte` style blocks fail,
with a grandfather list that shrinks to zero) — same machine-enforced pattern
as the file-size guard.

## Appendix — survey findings (2026-07-05, testbench live-drive)

Why this document exists. Numbers from the audit of `styles.css` + 77
component style blocks; gestalt findings from driving the isolated instance.

| Axis | Found | Target |
|---|---|---|
| font-size | 30+ distinct values (11/12/13 dominate; fractional px noise: 10.5–14.5) | 7 tokens |
| font-family | 3 mono stacks; 2 hardcoded Newsreader bypassing `--serif`; 4 empty declarations | 3 tokens |
| font-weight | 5 weights, 800 in decorative use | 4 tokens, 700 cap |
| spacing | ~100 distinct pad/margin/gap values | 7 tokens |
| radius | 19 distinct (4/6/8 dominate; 7/9/11/12/14 noise) | 4 tokens |
| shadows | 24 hardcoded rgba recipes vs 7 tokenized | elevation tokens only |
| colors | ~299 hardcoded literals in component styles; worst five files carry 62% (TagManagerDialog 43, NodePickerConfigEditor 37, ViewFlowNode 37, GroupsManagerDialog 35, NodePicker 32) | 0 raw literals |
| z-index | 21 distinct values up to 10000 | 6 layers |
| motion | ~12 duration/easing combos | 2 tokens |
| caps-labels | ≥3 competing recipes across 35 uses | 1 recipe |
| local palettes | `--ctx-*` (17 tokens) + per-file mini-systems | fold into roles |

Gestalt defects (dark and light themes alike): free-floating panes overlap and
clip each other; the editor opens as another cascading pane, off-viewport at
narrow widths; ~40% of the screen is dead graph-paper board; every pane spends
chrome on title bar + move button + corner grip; parallel controls disagree on
size (16px `Validate` vs 13px topbar actions); the rail double-renders
reference fields; `+>` affordances are unreadable. The content layer (Editorial
Card editor, NodeRows, stripes, serif group headers) already carries the
intended identity — the dated feel is the shell plus unsystematic values, which
is exactly what #32 (shell) and #125 (values) replace.

Open question, non-blocking: computed borders read 0.909091px (= 1px ÷ 1.1)
in the live app; no global zoom/scale found in the stylesheets. Locate during
#125 (suspect: browser zoom state or an inherited transform on the pane tree).
