# ADR-0044: The snapshot strip is the scrubber's third axis; comparison is a flip, not a split

- Status: **Accepted** — 0.8.0, 2026-07-22 (Anton, having read it alongside the mockup). Accepted
  covers §A–§L: the strip as the scrubber's third axis, position-is-the-mode governing size as well
  as contents, notches with Live at the right, log-scaled spacing, the track-width invariant, flip
  rather than split with the tint held in every compare state, rendered HTML in the read-only overlay
  slot, the warm/cool hue axis with chroma halved for light, the key map, and the
  glyph-vs-colour rule. The five items under "Open" stay open by design — they are implementation
  judgements, not unresolved decisions.
  · **Amendment 1 (2026-07-22, #396):** the §G risk is settled — runs must be complete markdown
  fragments; §F stands.
  · **Amendment 2 (2026-07-22, #409):** the greyscale channel is the edge's **shape**, not its
  colour — which settles Open item 5; and a block the construct scan cannot account for stacks
  rather than being wrapped whole.
- Feature: #6 · Companion: ADR-0043 (the model) · Follows: ADR-0013 (the scrubber), ADR-0030 (the
  design language), ADR-0038 §A (compact at rest), ADR-0042 (the layer picker, the same gesture on
  the hierarchy axis)
- Evidence: [`../mockups/0044-snapshot-strip.html`](../mockups/0044-snapshot-strip.html) — an
  interactive mockup on the real token layer, iterated with Anton over one session. The geometry, the
  keys and the diff rendering below were all *tried*, not sketched. Open it in a browser; it is a
  single self-contained file with fixture data and no build step.

## Context

ADR-0043 settles what a snapshot **is** — a witness: prose restored byte-exact, context captured and
only reported when it has drifted. It deliberately did not design the surface, and was held open as a
Draft on the grounds that a UX pass would probably find something the model was missing. It did:
three model-level gaps, folded back into 0043 as amendments (delete, pin, capture-before-restore).

This ADR is that pass. It exists separately for the reason ADR-0039 and ADR-0042 are separate — the
model and the gesture are each arguable on their own terms, and a reviewer of one should not have to
accept the other.

## Decision

### A. The strip is the third axis of a control the app already has

Two surfaces already solve *this document has an ordered set of states; pick one; position is the
mode*: the mutation scrubber on story time (ADR-0013, foot-docked on a lore card) and the layer
picker on the hierarchy axis (ADR-0042, header-docked). Snapshots are the same problem on **real**
time, so they get the same gesture rather than a new one. **The burden is on any departure from the
scrubber, not on the reuse.**

The slot is free: the scrubber renders only for lore (`NodeEditor.svelte`, the `documentKind ===
"lore"` guard on the `MutationScrubber` mount), and scenes are book-scoped so they carry no layer
axis either. The scene editor has no axis picker today, so there is no competition for the foot dock
and no mode to collide with.

This is also a better argument for 0043's scenes-only v1 than the effort one it gives: ADR-0042 had
to establish that two axes form **an L, not a grid**. Snapshots on lore entries would put *three*
axes on one card — layer, story time, real time — which is where that problem actually bites.

### B. Position is the mode, and it governs the strip's size too

At **Live** the only action is capture. Parked on a notch, the strip offers **Restore · Pin ·
Delete** plus the compare toggle. No context menus, nothing behind a right-click — clicking a notch
already means "view this one", so the actions simply apply to wherever you are.

**Compact at rest.** While writing, the strip is a quiet ruled line: small notches, camera only, no
labels, transparent until the pointer nears it. Parking is what earns the taller strip, the scale
ticks and the controls. This is ADR-0038 §A's compact-at-rest / expand-on-engage shape, applied to
the strip's *size* rather than only its contents.

### C. Notches, not beads; time runs left to right

The scrubber uses round stops on a rail. Snapshots cut **into** the edge instead — so if both axes
ever appear on one card they read apart at a glance while the gesture stays identical. Tall and
filled = explicit (kept); short and faint = automatic (thinned).

**Live sits at the right end**, deliberately *not* the scrubber's home-at-left. There, base is
*earliest*, so home and origin coincide. Here the rest position is the **present**, and time reads
rightward. Copying the scrubber's home position would make the two strips look alike while reading
backwards, which is the worse kind of consistency.

### D. Spacing is the timeline, and it cannot be linear

Notches sit at their **age**, so the gaps carry meaning: a tight cluster is an afternoon's work, a
long run is a week away from the scene. Edits cluster, which is precisely why the spacing is worth
having — and precisely why linear time fails. One snapshot from last week plus four from this
morning piles the recent four into an unreadable clump at the right edge, and those are the ones an
author reaches for.

**A log scale** spreads recent history and compresses deep history. Faint `1h / 1d / 1w` ticks make
the scale legible rather than merely implied, and a minimum gap keeps notches from touching however
they bunch.

**Known ambiguity, stated so it is not later mistaken for a defect:** under keep-five thinning, a gap
can mean *"a week passed"* or *"a snapshot used to be there"*. A lone explicit notch far left is
"the oldest thing I chose to keep", not "the oldest thing that existed".

### E. Nothing inside the strip may change the track's width

Notches are positioned as percentages of the track, so anything beside it that grows or disappears
slides every notch along the timeline — the strip silently claims a snapshot happened at a different
time than it did a moment earlier. **A timeline that moves *because you used it* cannot be read.**

Therefore: everything sharing the strip's row is **fixed width** (the camera is a fixed square in
both states), and everything variable — the `Snapshot · 2 hours ago` label above all — lives in the
actions row, which only exists while parked and can be any width it likes.

**This is emphatically not "the track is a fixed size".** The track is fluid and **must** rescale
with the editor pane: it fills whatever width the pane gives it, and the notches keep their
proportional positions, so a resized pane shows the same timeline larger or smaller. A fixed-width
track in a resizable pane would leave dead space or overflow, and would look broken.

The invariant is about *cause*, not *dimension*:

> The track's width is a function of the pane's width **and nothing else**. Parking on a notch,
> labels appearing, controls changing state — none of these may move a notch.

Resizing the pane moves every notch, and that is correct: the author changed the container, so the
timeline redraws to fit. What must never happen is the timeline shifting under a gesture that was
about *reading* it.

### F. Comparison is a flip, not a split

Two synced columns make the reader do the comparison manually, line by line. Flipping the **same
region** between two states makes the difference announce itself: the eye is poor at parallel
scanning and excellent at change detection. It also dissolves the sync problem by construction —
there is only ever one column.

**The colour says which version the text belongs to.** Warm = in the scene **now**; cool = in the
**snapshot**. Everything else falls out of that one rule: an addition is warm because it exists only
in the current scene, a deletion is cool because it exists only in the snapshot, and a modification
is simply the two adjacent. Three cases that could drift apart become one that cannot.

**The tint stays in every compare state, not only "both".** An earlier iteration rendered the single
states as unmarked prose, on the theory that the same control could then serve reading as well as
judging. That broke the gesture: with nothing marked, a flip changes words *somewhere* and the eye
has no anchor. **The tint is the anchor** — the words swap underneath a patch that does not move.
Only **Live** is unmarked, because there is nothing to compare it against.

**Inline vs stacked is structural, never a length threshold.** A change contained within one block
renders side by side; a change spanning block boundaries stacks. A word count deciding the layout
makes it jitter as the author types, and the structural rule matches how the change reads: a
substitution inside a sentence *is* inline; a rewritten paragraph *is* a block.

**Fields flip, and never interleave.** A field value is atomic — it resolves in one blink — so
interleaving would only make a cramped row cramped. Same colours, same meaning, no second vocabulary:
**the colour means temporal provenance everywhere, and location carries the subject.**

### G. This is rendered HTML, not a TipTap decoration layer

The mechanism already exists and is proven by the scrubber: when scrubbed, the card renders a
read-only effective-body overlay while **the editable TipTap buffer stays mounted and hidden
underneath**, so unsaved edits survive the round trip untouched.

That is not a workaround, it is the better design on three counts. The live buffer is never touched
by the feature whose job is not losing words. The inline-vs-stacked layout above is near-intractable
as ProseMirror decorations and trivial in rendered HTML. And it reuses a pattern the author has
already seen on lore cards.

**The diff itself is computed backend-side, and ADR-0025 authorises this rather than tolerating it.**
That ADR defers server-side evaluation "until something that cannot see the frontend needs it" — and
a snapshot body is exactly that: it lives on disk under `snapshots/` and the frontend has never
loaded it. Its two objections both invert here. The premise "*the data is already frontend-side, so a
round-trip costs more than the in-memory pass*" is false — the frontend would have to be *sent* the
snapshot body first, so the round-trip happens either way; sending runs instead of a second document
is strictly cheaper. And the round-trip it warns about is *per evaluation during live preview*, where
the diff is computed **once, when the author parks on a notch**.

That second point is the load-bearing one, and it is the boundary rather than the framing:

> This holds because the diff is computed at a **discrete moment**. Diffing continuously — against
> the live buffer as the author types — would put an HTTP round-trip back in the typing loop, and
> ADR-0025's objection would apply again in full.

The backend endpoint therefore takes two node states and returns provenance-tagged runs (§F). Because
the runs carry *all* the text, one response serves all three view states — Both, Now and Snapshot are
three filters over one payload, not three requests. Python's `difflib.SequenceMatcher.get_opcodes()`
already emits `equal / insert / delete / replace` spans in that shape, so no library is added on
either side.

**Known risk, to spike before treating §F as proven:** this diffs *markdown source* and then renders.
A change straddling inline markup can produce runs that do not survive rendering independently. The
mockup dodges it by construction (hand-authored runs over clean prose), so it is untested.

> **Settled by [Amendment 1](#amendment-1--runs-must-be-complete-markdown-fragments-2026-07-22).**
> The risk is real — 8 of 18 fixtures broke — and it is bounded: three constraints on the runs make
> all of them render correctly, so §F stands as decided.

### H. Two new colour tokens, warm and cool

Almost every hue is spoken for: teal is the accent, violet is the mutation axis, amber is `--warn`,
brick is `--danger` (reserved for destructive — and a diff is not an error), slate-blue is lore.
Red/green is excluded on both accessibility and semantics: this is **before and after**, not *bad and
good*.

The pair reads **warm = live, cool = archived** — the past reading cooler is an intuition most people
already have, and it puts the two on an axis rather than making them arbitrary. Each is a
`--diff-*` / `-soft` / `-edge` triple defined for both themes.

**One hue axis: warm ~20°, cool ~205°.** Chosen by eye against real prose, in both themes, from a
bench of candidates. A warm side drifting further toward red was tried and rejected on sight — at
~350° it reads as an alarm rather than a tint, too close to `--danger`. That is worth recording as a
boundary, not just a preference: the warm side belongs in the orange/clay band.

**Chroma is halved for the light theme** — roughly 15/10 in light against 26/25 in dark (RGB chroma
behind the prose). The two themes were picked independently and turned out to be *the same hues at
different chroma*, which is the finding worth keeping:

> A tint on white sits at peak luminance, where the eye's colour discrimination is best, so it
> shouts. On a dark ground discrimination falls away and the identical tint barely registers.
> **Chroma is not theme-invariant, and a palette that is merely inverted will be wrong in one of the
> two.**

The token layer already carries this lesson from a different direction: `--accent-emphasis` exists
because `--accent-strong` had to deepen in light and *brighten* in dark, and one token could not do
both. This is the same asymmetry on the chroma channel rather than the lightness one.

Two further constraints hold:

- **Equal chroma across the pair, within a theme.** If one tint is more saturated than the other it
  reads as *more important*, and the pair stops meaning *then vs. now* and starts meaning
  *significant vs. incidental*.
- **Hue must not be the only channel.** Roughly 1 in 12 men has a colour-vision deficiency, and
  warm-vs-cool is the axis most affected. Each tint therefore carries a darker **edge** rule beneath
  it, and the pair must stay distinguishable in greyscale — an underline survives what a wash does
  not. This constraint bites hardest on the light theme, whose chroma is already halved.

### I. Keys: two axes, no held modifier

A held modifier was tried and withdrawn. Repeatedly holding <kbd>Shift</kbd> trips Windows
**FilterKeys**, and five presses fire **Sticky Keys** — and this is a Windows-first app. It is not
needed anyway: **the compare view is read-only**, so the entire unmodified keyboard is free here and
nothing has to be a chord.

| keys | axis |
|---|---|
| <kbd>←</kbd> <kbd>→</kbd> | **when** — move through the snapshots; right past the newest lands on Live |
| <kbd>A</kbd> <kbd>S</kbd> <kbd>B</kbd> | **which** — Active · Snapshot · Both |
| <kbd>Esc</kbd> | back to Live |

Left hand on the letters, right hand on the arrows, so the two axes can be driven at once. Not
<kbd>↑</kbd><kbd>↓</kbd>, which fight page scroll on a long scene. **A/S/B are toggles, not held
modifiers, so OS key auto-repeat must be ignored** — otherwise holding one fires `keydown` ~30×/s and
the view strobes. (The other half of that flicker was rebuilding the notch track on a pure version
flip; a flip must not touch the strip's DOM.)

### J. The camera is an affordance, so it is never an annotation

Capture takes a camera glyph — it reads immediately, and drawing it inline is cheaper than reaching
into the icon bundle (#315 is already about trimming that).

**It must not appear on a changed field.** The design language already rules that a mark is never
both annotation and affordance, which is why `⧉` is the fork button only. And the general rule, which
is what caps the glyph pile-up across mutations, layer deltas and now snapshots:

> **A glyph marks what is true about the *value*. Colour marks what is true about the *view*.**

`⤳` mutated and `ti-versions` overridden are *permanent properties* — true whenever you look at the
card, describing where a value came from. A snapshot difference is not a property of the field at
all: it exists only while parked, and vanishes at Live. Giving it a glyph would put a
permanent-looking mark on a temporary condition. **Lenses get colour, not glyphs** — and comparison
state can therefore never add a glyph, however many axes the app grows.

### K. Relative time is platform-native; nothing is added for it

`Intl.RelativeTimeFormat` is built into the browser and produces the *5 minutes ago / yesterday*
ladder directly. The frontend today formats **no** dates at all — chat sessions carry
`created_at`/`updated_at` and nothing renders them — so there is no existing helper to reuse and none
to import.

What has to be written is only the **bucketing**: where the ladder switches from relative to named to
absolute. That is the design decision, not boilerplate, and a library would make it for us wrongly.
It belongs in a **shared helper rather than inline**, because it is the second consumer already —
ADR-0042's layer-aware footer echo wants one too, and those unrendered chat timestamps are unrendered
precisely because no formatter existed.

### L. The tooltip, and the description

Hovering a notch gives the capture time on a relative ladder — *5 minutes ago · yesterday ·
Wednesday 12th* — plus the one-line description if the snapshot has one, and whether it is pinned.

**Most snapshots will have no description**: every automatic one, and every explicit one where the
author was in flow and did not stop to type. So the empty case is the *common* case, and a
description is an enrichment on top of the date, never a replacement for it.

**Whether the description replaces or augments the date line is deliberately not decided here.** It
needs to be tried at implementation. This ADR records the constraint (the absent case must read well)
and nothing about the layout — sketching that is how ADR-0005 acquired authority it had not earned.

## Amendment 1 — runs must be complete markdown fragments (2026-07-22)

Settles the risk §G records against §F, from the spike in
[#396](https://github.com/antoncl/local-writing-app/issues/396). Full finding and the harness:
[`../spikes/0396-word-level-markdown-diff.md`](../spikes/0396-word-level-markdown-diff.md).

The risk was real. A plain word-level diff over the whole body damaged 8 of 18 realistic fixtures —
the tint element overlapping `<strong>` or `<a>`, `](lore://…)` leaking into the prose as literal
text, and a mutation marker silently degrading to a raw HTML comment when the edit fell inside it.
That last one is worth naming because neither ADR saw it coming: `sceneMarkdownToHtml` rewrites the
mutation/todo/character comments into spans with regexes *before* `marked` runs, so a run boundary
can break a **marker**, not only inline markup.

It is also bounded, and the bound is the useful part. **An edit strictly inside a construct was
already safe** — the canonical `**a bold phrase**` → `**a bolder phrase**` renders clean, as do
nested emphasis, link text, table cells and list items. The failure is never "markup is present"; it
is only ever a run boundary landing *between* a construct's delimiters, or across a block boundary.

**§F and §G stand as decided. They gain one contract on the runs:**

> **Every run is a complete markdown fragment, and is either inline-within-one-block or
> block-spanning — never both.**

Three rules produce it, all three verified against the same fixtures:

1. **Blocks are diffed first; word granularity applies only inside a block.** So no run contains a
   blank line. This is §F's own inline-vs-stacked rule, moved down into the diff, which is where it
   was always doing the work.
2. **Run boundaries snap out of inline constructs** — expanded until the run encloses the whole
   construct, an HTML comment counting as one. This is what keeps the markers whole.
3. **A block-spanning change is wrapped around the *rendered* output, not injected into the source.**
   No inline element can wrap two paragraphs. The mockup's `.blk-now` / `.blk-was` containers are
   already this; what was missing is the run carrying the flag that says so.

Rule 2 costs precision: one word changed inside `**very tired**` marks the whole emphasised phrase
on both sides. That is accepted — it is confined to the neighbourhood of markup, and half-tinting an
emphasised phrase would read worse than tinting all of it.

## Amendment 2 — the greyscale channel is shape, and an unreadable block stacks (2026-07-22)

From implementing slice 2 ([#409](https://github.com/antoncl/local-writing-app/issues/409)). Two
findings, one of which closes Open item 5.

### The pair cannot be told apart in greyscale, and colour cannot fix it

§H asks for two things that turn out to pull against each other. *Equal chroma across the pair
within a theme*, so neither tint reads as more important — and *the pair must stay distinguishable
in greyscale*. Equal chroma at equal lightness **is** equal luminance, and greyscale is exactly
luminance. Measured on the shipped tokens (Rec. 709, out of 255):

| | wash ΔL | edge ΔL |
|---|---|---|
| light | 0.1 | 0.2 |
| dark | 2.1 | 5.4 |

Both themes, not just the light one §H predicted. The mockup's own light palette was no better in
kind — its edges reached 14.3, still faint — and its dark palette is the shipped one, so **the
constraint was never met at any point**, in either theme. That is worth stating plainly: it was not
lost when the light chroma was halved for shipping, it was never there.

**So the wash cannot carry greyscale, and that is by construction rather than by a poor swatch.**
Separating the two *edges* by lightness does work, and trades the problem for the one §H was
avoiding: a darker rule on one side reads as heavier, which is unequal weight moved out of the
chroma channel and into the lightness channel.

**The edges therefore differ by shape: solid for the scene now, dotted for the snapshot.** Shape is
neither hue nor lightness, so equal chroma and equal weight both survive untouched and the
distinction survives greyscale whole. The archived side reading as the provisional one is the right
way round. No token value changes.

Drawn as a background gradient rather than a border, so it costs no layout — a 2px border on an
inline span moves the line box under the prose.

> **Open item 5 is settled.** The hex values stand; what was missing was never a value but a second
> channel. And the finding generalises past this pair: *a lens that distinguishes two states by
> colour must name the non-colour channel that carries it.*

Evidence: `tmp/0044-greyscale-bench.html` in the slice-2 branch — the mockup's diff marks in five
palettes, each rendered in light and dark beside a `filter: grayscale(1)` copy, with the luminance
arithmetic computed in the page. Temporary by intent; the numbers above are its output.

### A block the scanner cannot account for stacks

Amendment 1's constraint 2 needs to know where a run boundary may fall, and some blocks cannot be
answered for — unbalanced emphasis, an unterminated code span or HTML comment, markup the scan does
not model. The obvious failsafe, *protect the whole block*, is *not* safe: it puts the wrapper at
column 0, and a line beginning `> ` or `- ` stops being a blockquote or a list item the moment
anything precedes its marker.

**Such a block is emitted `stacked` instead** — wrapped around the rendered output, which constraint
3 already provides for. Unfamiliar input degrades to a coarser rendering rather than a corrupt one.
The same rule covers a change that would escape its structural container: a run spanning a newline
crosses into the next quoted line or list item, and one spanning `|` crosses a table cell.

## Non-goals

- **A clean-reading mode for a snapshot.** The tint decision (F) costs the "read the snapshot as
  plain prose" case. If that turns out to be wanted, it is a separate affordance, not a side effect
  of the compare mode.
- **Rendering the drift report anywhere but the strip.** With lore out of v1 scope, two of 0043's
  three drift axes concern entries the scene editor does not display, so the strip is where the
  advisory lives.
- **A snapshot browser across scenes.** The strip is per-scene, as the store is.

## Open — to settle at implementation

1. **The scale ticks may be over-explaining.** If the spacing reads on its own, `1h/1d/1w` is clutter
   on a writing desk.
2. **A narrow pane.** Rescaling with the pane is required (§E), but on a *narrow* pane the minimum
   gap starts doing real work — compressing a cluster into evenly-spaced ticks that no longer
   reflect time. At some width the honest answer may be to stop pretending the spacing is
   proportional.
3. **Discoverability of the compact strip.** It may now be quiet enough that a new author never
   learns snapshots exist.
4. **The description's presentation** (L).
5. ~~**The exact hex values** (H).~~ **Settled by [Amendment 2](#amendment-2--the-greyscale-channel-is-shape-and-an-unreadable-block-stacks-2026-07-22).**
   The greyscale re-check found that no hex value could satisfy the constraint, because §H's
   equal-chroma rule makes the pair equally luminous by construction. The values stand; the edges
   differ by **shape** instead.

## Test surface

- The track's rendered width is identical at Live and parked on a notch.
- A pure version flip (A/S/B) does not rebuild the notch DOM, and held keys produce exactly one
  state change.
- Changed regions carry their tint in `both`, `now` and `was`; Live renders unmarked.
- A change within one block renders inline; a change spanning blocks renders stacked — regardless of
  how many words either side contains.
- The eighteen fixtures of #396 render well-formed HTML in all three view states, with no markdown
  syntax reaching the reader as literal text and no marker degraded to a raw comment (Amendment 1).
- The two tints stay distinguishable with colour removed — which no hex value achieves, so this is a
  test of the edge's shape rather than of the palette (Amendment 2).
- A block whose markup the scan cannot account for renders stacked rather than wrapped, and a change
  that would span a quoted line, a list item or a table cell does the same (Amendment 2).
- Notch order matches capture order, and positions are monotonic in age under the minimum-gap
  adjustment.
- A snapshot with no description renders a tooltip with no empty affordance in it.
