# Spike #396 — does a word-level markdown diff survive rendering?

- Asked by: [#396](https://github.com/antoncl/local-writing-app/issues/396), blocking slice 2 of the
  snapshots epic ([#395](https://github.com/antoncl/local-writing-app/issues/395))
- Settles: the risk ADR-0044 §G records against §F
- Outcome: **2 of the issue's three — it holds, with constraints.** Three of them, and one is
  load-bearing enough that §F's own stacked/inline rule has to move into the diff.
- Harness: `scripts/spike_396_runs.py` (the diff) + `frontend/spikes/396-diff-render.test.ts` (the
  render), report at `frontend/spikes/396-report.txt`. Reproduce with:

```bash
python scripts/spike_396_runs.py && (cd frontend && npx vitest run spikes/396)
```

## Method

The harness exercises the real path on both ends rather than a model of it. The diff is the same
`difflib.SequenceMatcher` over word tokens that §G names for the runs endpoint. The render is the
app's actual `sceneMarkdownToHtml` (`frontend/src/lib/utils/markdown.ts`) — which matters more than
it looks, because that function does **not** just call `marked`: it first rewrites the
`<!-- mutate: … -->`, `<!-- embedded-todo: … -->` and `<!-- character: … -->` comments into `<span
data-…>` atoms with regexes over the source. So a run boundary can break a *marker* as well as an
emphasis span, which is a failure mode neither ADR anticipated.

Eighteen fixtures, each a probe at one hazard: an edit inside emphasis, straddling its start,
straddling its end, inside nested emphasis, inside a link's text, inside a link's target, adjacent
to a mutation marker, inside a mutation marker, inside a todo anchor's wrapped prose, a paragraph
split, a paragraph join, inside a table cell, across a list-item boundary, emphasis added around
existing words, emphasis removed from them, inside a heading, inside a blockquote, and clean prose
as a control.

The last four came from a second adversarial pass over the first fourteen, asking what an author
does that the fixtures didn't cover. Two of them broke — which is the argument for the pass, not an
aside.

**Three oracles, because the obvious one is not enough.** The natural check — wrap the runs, render,
strip the wrappers, compare against a plain render — passes on cases that are badly broken. It was
worth writing down where that goes wrong, because it is the check anyone would reach for first:

> `<span class="r-was"><strong>very</span> <span class="r-was">tired</strong></span>` strips to
> exactly the baseline. It is also HTML no browser will build as written. The parser's fixup
> reparents the tint, so the colour ends up on the wrong words — silently, and only in a browser,
> which is the one place the test wasn't looking.

So the oracles are: (1) strip-and-compare against a plain render, for the single views; (2)
**well-formedness** — every tag closes inside the element that opened it; (3) **leak detection** —
no `](`, `**`, `~~` or `|` reaching the reader as literal text. All three run against all three view
states (`now`, `was`, `both`), because `both` is where the runs actually interleave and it has no
baseline to compare against.

## Result: 8 of 18 fixtures damaged as designed

| what breaks | fixtures | what the author sees |
|---|---|---|
| a run boundary falls **between an inline construct's delimiters** | emphasis start, emphasis end, link target | the tint element overlaps `<strong>` / `<a>`; in `both`, `](lore://loc-westquay)` leaks into the prose as literal text |
| a construct exists **on one side only**, so the boundary is inside it in one text and not the other | emphasis added, emphasis removed | same overlap, and this is the *common* edit — an author bolding or unbolding a phrase they already wrote |
| a run **spans a block boundary** | paragraph split, paragraph join | the wrapper contains `</p><p>` — an inline element wrapping two paragraphs |
| a run **cuts an HTML-comment marker** | mutation-marker value edit | the marker preprocessing no longer matches, so the pill silently degrades to a raw comment; in `both` the two versions merge into one malformed comment |

Two results are worth having explicitly, because they bound the problem rather than restate it:

- **An edit strictly *inside* a construct is already safe.** `**she had ever seen it**` →
  `**she had ever once seen it**` — the issue's canonical case — renders clean, as do nested
  emphasis, link *text*, table cells, list items, headings and blockquotes. The problem is never
  "inline markup is present"; it is only ever a boundary landing *between* a construct's delimiters.
- **The wrapper element is irrelevant.** A control run with real `<span class="r-now">` wrappers
  produces the identical nesting errors on the identical fixtures. This is not a
  custom-element artefact.

## The constraints, and that they are sufficient

All three are implemented in the harness and all eighteen fixtures then pass all three oracles in
all three views.

1. **Diff per block; word granularity only *inside* a block.** Blocks are diffed first; a word-level
   diff runs only where one block maps to one block. A run can then never contain a blank line.
   This is §F's structural inline-vs-stacked rule, moved one layer down from the renderer into the
   diff — which is where it was always doing the work.
2. **Snap run boundaries out of inline constructs.** A boundary falling between a construct's
   delimiters is expanded until the run encloses the whole construct, merging adjacent runs as
   needed. An HTML comment counts as a construct, which is what keeps the markers whole. `**very` +
   `tired**` becomes one run, `**very tired**`, which renders on its own.
3. **A change that spans blocks is wrapped around the *rendered* output, never injected into the
   source.** Constraints 1 and 2 leave one residue: when a block splits or joins, the changed region
   genuinely is two paragraphs on one side and one on the other, and no inline element can wrap
   that. §F already says such a change stacks — this makes the diff say so too, by flagging the run,
   and the renderer wrap the rendered HTML in a block container. The mockup's `.blk-now` / `.blk-was`
   divs are already exactly this; what was missing was the run carrying the flag.

The shape that falls out: **the runs endpoint returns runs that are complete markdown fragments, and
each run is either inline-within-a-block or block-spanning, never both.** That property is what the
frontend needs in order to wrap anything at all, and it is cheap to state as a contract.

## What this costs, stated so it is not later read as a defect

**The diff is coarser than word-level near markup.** With constraint 2, changing one word inside
`**very tired**` marks the whole emphasised phrase as changed on both sides. The author sees
`**very tired**` → `quite **tired**` rather than `very`→`quite`. This is a real loss of precision
and it is confined to the neighbourhood of markup, which in fiction prose is rare. It also arguably
reads *better*: the emphasised phrase is one thing to the eye, and half-tinting it would be the
odder rendering.

## Two things for slice 2 to carry, not decided here

- **The construct scanner must not be regex in production.** The harness detects constructs with a
  list of regexes, which is enough to answer *whether a snapping rule suffices* but will mis-handle
  escaped delimiters, code spans containing asterisks, and unbalanced markup. Production should take
  the intervals from a real inline scan. This is an implementation choice, not an open design
  question.
- **`both` puts two copies of a marker in the DOM at once.** When a marker's value is what changed,
  the compare view renders the old and new pill adjacent — two elements carrying the same
  `data-mutation-id`. The overlay is read-only rendered HTML and never feeds TipTap, so nothing is
  corrupted; but any code that looks up a marker by id within the overlay would find two. Worth a
  test in slice 2 rather than a discovery in slice 3.

## Fixtures kept

`frontend/spikes/396-runs.json` is generated, not hand-authored — regenerate it rather than editing
it. The eighteen cases are the regression surface for slice 2: each one is a rendering the runs
endpoint must not produce.
