# ADR-0030: The design language — a quiet writing desk, tokens as contract

- Status: Proposed — 0.6.0, 2026-07-05
- Feature: #124 (design language) · steers #32 (layout shell) and #125 (restyle pass)
- Normative document: `docs/design/design-language.md`
- Consolidates: widget-taxonomy, NodeEditor-body-spec, and metadata-revision
  memos (interaction law, previously memory-only, now repo-canonical)

## Context

0.6.0 is the UI overhaul: replace the MDI pane shell (#32), refresh the look
and feel, and — the durable half of the ask — leave behind rules that steer
every future UI change, so visual quality stops depending on per-change taste.

A live survey of the app (testbench drive, both themes) plus a full audit of
`styles.css` + 77 component style blocks found:

- **Interaction law exists and is good.** The widget taxonomy (NodeRow /
  NodeList / NodeEditor, density-first, color-scoping, gold-is-the-pin) and the
  Editorial-Card editor survived contact with real refactors. The content layer
  already has an identity.
- **Visual law does not exist.** The 72 CSS custom properties are color/surface
  roles only — there is no type scale (30+ distinct font-sizes, fractional px
  noise), no spacing scale (~100 distinct values), no radius/elevation/z/motion
  tokens (19 radii, 24 hardcoded shadows, 21 z-indices up to 10000, ~12
  duration/easing combos), ~299 hardcoded color literals in component styles,
  and a 17-token parallel palette (`--ctx-*`) private to one component family.
- **The dated gestalt is the shell**: floating, overlapping, cascading panes on
  a dead graph-paper board — plus the unsystematic values above. Not the
  widgets.

## Decision

1. **Name the identity: a quiet writing desk.** Two voices — serif
   (`Newsreader`) marks *the work* (titles, group headers, reading surface),
   sans (`Inter`) is *the tool* and recedes. The manuscript is the loudest
   thing on screen; chrome may never be heavier than the content it hosts;
   decoration that encodes nothing is removed. The graph-paper board dies.

2. **A full token layer becomes the visual contract**: 7 type sizes (integer
   px, deliberately modest display sizes — the document title stands out
   through serif voice, weight, and isolation, not size), 7 spacing steps, 4
   radii, 3 elevation levels, 6 z-layers, 2 motion durations, 3 font stacks, 4
   weights (800 retired). Type tokens compose a `--ui-scale` factor, so a
   future user-facing type-size setting (master scaler, per-role overrides) is
   a settings write, not a rework. Raw literals in component styles are
   defects. Color roles keep the existing (good) architecture; `--ctx-*` folds
   into the global roles; gold keeps exactly one meaning (pin, plus the
   sanctioned prose-TODO anchor).

3. **Interaction law is promoted from memory memos into the repo** (composition
   rules §3 of the language doc) and extended with component rules: two button
   sizes / three variants, glyph-first affordances drawn from a closed lexicon
   (tooltip + aria-label mandatory; cryptic `+>` compounds retired; words
   reserved for primary/destructive actions), one caps-label recipe, one
   field-row atom (the rail's ref-field double-render collapses), popovers on
   shared panel/elevation tokens.

4. **The shell contract for #32 is spatial, not implementation**: a tiled
   workspace — regions fill it, nothing floats/overlaps/cascades, the editor is
   the primary region, splitters replace per-pane move buttons and corner
   grips. On top of the gestalt, a **surface taxonomy** (region / editor tab /
   rail / popover / dialog, with an ordered classification walk) answers
   "where does a new feature live?" the way the widget taxonomy answers "how
   does a thing render?" — documents never spawn surfaces of their own, and
   the shell owes extension guarantees (keyboard reachability, saved layouts
   tolerate unknown regions, regions collapse to tabs below a minimum width).
   #32 chooses the mechanism; this ADR fixes the contract it must implement.

5. **Enforcement follows the house pattern** (machine-enforced, not prose):
   after #125 phase 1, the PostToolUse hook + pre-commit gain a style lint —
   hex/rgb literals and non-token `font-size` in `.svelte` style blocks fail,
   with a grandfather list that shrinks to zero. Same shape as the file-size
   guard.

6. **Sequencing**: the token layer + content-surface migration (#125 phase 1)
   can land before the new shell — tokens apply to content that survives the
   shell swap. Chrome polish waits for the #32 shell; restyling MDI chrome the
   shell deletes is throwaway. Serialize through master as established in
   0.5.5.

## Why / rejected alternatives

- **Rejected: adopt a component library (shadcn-svelte, Skeleton, etc.).** The
  house widget taxonomy is already canonical and battle-tested; a library
  brings its own row/list/dialog idioms and would fork the taxonomy rather
  than strengthen it. The gap is *values*, not components — a token layer
  closes it without importing someone else's identity.
- **Rejected: utility-CSS framework (Tailwind).** The codebase pattern is
  scoped component styles consulting tokens; Tailwind would be a whole-app
  rewrite of the styling idiom to solve what 40 custom properties solve, and
  arbitrary values (`p-[7px]`) would re-open the very zoo being closed.
- **Rejected: keep per-component freedom, fix only the worst files.** That is
  the status quo that produced 30 font sizes and 299 hardcoded colors under an
  explicit density-first design culture. Without a contract, drift is the
  steady state; the audit is the proof.
- **Rejected: restyle first, shell later.** The shell is the loudest dated
  element; polishing chrome that #32 deletes is wasted motion. Inverted
  instead: tokens (survive the swap) → shell → chrome polish.
- **Why "quiet writing desk" and not a bolder direction.** The app's identity
  already exists in the Editorial-Card editor and serif/sans split — the survey
  showed the content layer reads as intended and the *chrome* betrays it.
  Sharpening what exists is cheaper and truer than inventing a new face, and
  a fiction-writing tool should spend its personality on the manuscript, not
  the chrome.

## Consequences

- `docs/design/design-language.md` is normative for every UI change from
  0.6.0; its checklist (§5) is the review gate for visual PRs.
- #125 phase 1: `:root` token block + worst-five color files + `--ctx-*` fold;
  phase 2: remaining surfaces + caps-label/button/field-row convergence;
  chrome polish rides the #32 shell. Every visible change is eyeballed in the
  interactive session, both themes.
- #32 inherits the spatial contract (§4 "The shell" in the language doc).
- Follow-up after phase 1: wire the style lint into
  `.claude/hooks/check_edited_file.py` + `.pre-commit-config.yaml`.
- The three governing memos remain as history; the repo doc supersedes them
  where they overlap.
