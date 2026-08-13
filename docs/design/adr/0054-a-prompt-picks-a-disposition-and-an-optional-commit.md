# ADR-0054: A prompt picks an output disposition, plus an optional commit

- Status: **Accepted** — 2026-08-13 (Anton). Designed with him over the output-kind unification thread.
- Issue: #881 (umbrella) · Pre-1.0 (no release milestone)
- Follows: ADR-0046 (AI lore editing is a reviewable patch — introduced `entry_patch`,
  the thing this ADR reclassifies), ADR-0051 (a node owns its conversations — §4 already
  frames commit as "an optional commit capability" of a conversation kind), the prompt-as-kind
  model (four concrete bases: continuation / revise / general / snippet)
- Relates: ADR-0029 §D (computed vs stored fields), the `AUTHORABLE_COMPUTED_FUNCTIONS` /
  `BUILTIN_COMPUTED_FUNCTIONS` split (the single-source-of-truth pattern this mirrors)
- **Verified against `91bcd90` (2026-08-12).**

## Context

A prompt declares, through `context_strategy.output`, **where its output goes**. The original
model was one clean axis — a chat (an AI generation) delivers its output somewhere, and the
*prompt* decides where:

| Disposition | Activated by | Where the output lands |
|---|---|---|
| `append_to_body` | `/` menu in the scene editor | streamed into the scene body at the cursor (the built-in `roleplay` is a flavour) |
| `replace_selection` | selection toolbar in the scene editor | replaces the selected text |
| `chat_panel` | — | a visible chat panel (the only disposition that surfaces the conversation) |
| ‹none› | — | no output — `snippet`, the `{% include %}` branch, runs no AI of its own |

`append_to_body` and `replace_selection` are chats whose output goes *inline* without ever
showing the conversation; `chat_panel` is the one that surfaces it. That is the whole of the
original vocabulary, and it is coherent.

**Then `entry_patch` (ADR-0046) broke the axis.** A brainstorm is not a fifth disposition — it is
a **composite**: it *is* a chat panel, **and then** it offers a **Commit** button that redirects the
conversation's result to a target node as a reviewable patch. It also has two commit variants —
the `review` axis, `visual_diff` vs `replace`. All of that was jammed into the single `output.kind`
slot as if it were a peer of `append_to_body`, when it is really **`chat_panel` + a commit**.

That conflation is why the vocabulary now feels messy, and the mess is measurable:

- **No single source, no validation.** The backend stores `output` as a free `dict[str, Any]`
  with zero validation (`models/schema.py:163`). The only closed value-set is the frontend
  `PromptSurface` union (`promptResolution.ts:17`).
- **The value-set is re-enumerated in places that disagree.** The authoring dropdown lists three
  and omits `entry_patch` (`SchemaTypeEditor.svelte:667`) — so **a user cannot author a brainstorm
  prompt at all**; a second inline union narrows to two (`promptResolution.ts:145`); the Openable
  chat filter hardcodes `entry_patch` as a blacklist of one (`builtinViews.ts:39`).
- **Dormant sub-axes with no home.** `review` (`visual_diff`/`replace`) and the S4 `extract`
  contract override apply *only* to the brainstorm, round-trip through the editor, and have **no
  authoring UI** — a user can't set them.
- **Two things share a name.** `roleplay` today is the `append_to_body` prose flavour; the
  still-conceptual "chat *with* a character" (ADR-0051 §4) is a different disposition entirely.

## Decision

`output` is **two orthogonal things**, and the schema will say so.

### 1. Output disposition — one axis, prompt-chosen

`output.kind` means strictly **where a chat's output lands**, and the set is closed:

`append_to_body` · `replace_selection` · `chat_panel` · ‹none›

These are the four the original model always had. All are **user-authorable** — a user may pick any
of them when sub-typing a prompt. `snippet` sits outside the axis (no output).

### 2. Commit — an optional capability on `chat_panel`

A `chat_panel` prompt may declare an **optional `commit`**: the conversation gains a **Commit**
button that redirects its result to a target node as a reviewable patch. **Only `chat_panel` can
carry a commit** — `append_to_body` and `replace_selection` *target the body directly*, so their
output has already landed; there is nothing to extract and review. `commit` is an object so it can
carry — and grow — its own properties:

```yaml
output:
  kind: chat_panel          # the disposition
  commit:                   # optional; only meaningful under chat_panel
    review: visual_diff      # how the committed result is reviewed (visual_diff | replace)
    fields: [summary]        # optional allow-list of what the extraction may set;
                             #   omit = the default (body + every proposable field)
    # target: <future>       # see "Deliberately out of scope"
```

`commit.fields` **declares what the commit extracts**, and it lives **on the prompt** — a prompt
knows what it is trying to produce. Omitting it is today's default: the extraction may set the body
plus any proposable field the conversation changed. Naming a list restricts the *generated* contract
to exactly those targets. **`body` is treated as just another field** in that list (it is, in most
ways, a metadata field) — so "fields-only" is simply its absence, with no separate body toggle: the
scene-summary prompt becomes `fields: [summary]`, which is **prose-safe by construction** — the body
is never in the contract, so a summary regenerate can never rewrite the manuscript. The contract is
still generated from the schema via `field_catalog`; `commit.fields` only filters which descriptors
it enumerates. This **replaces** ADR-0051 S4's `output.extract` (an arbitrary-Jinja override of the
whole contract) — see the rejected alternatives.

**`entry_patch` retires.** The three built-in brainstorm prompts change from
`output.kind: entry_patch` to `output.kind: chat_panel` + a `commit` block. Nothing about the
runtime loop changes — it is already "a chat, then extract-and-review"; only the schema shape and
the classification change. Dispatch stops asking `kind === "entry_patch"` and asks *"does this
prompt declare a commit?"*.

### 3. The disposition vocabulary is defined once

The **closed list of dispositions** (`append_to_body` · `replace_selection` · `chat_panel` ·
‹none›) is defined in **one place** — the backend — mirroring the `AUTHORABLE_COMPUTED_FUNCTIONS` /
`BUILTIN_COMPUTED_FUNCTIONS` precedent (`default_schema.py:41` — consolidated precisely "because
there were three and they already disagreed"). The backend **validates** `output.kind` (and the
shape of `commit`) against it on save, closing the free-dict gap; every consumer *derives* from that
one definition rather than re-listing values (the authoring dropdown, the `PromptSurface` union, the
dispatch, and the Chats "Openable" filter).

This is separate from the **per-prompt choices**, which live on each prompt: *which* disposition it
uses, and — for a committing chat — *which fields* the commit extracts (`commit.fields`). The
backend owns the vocabulary; the prompt owns its selections from it.

### 4. `roleplay` stays; the new thing is `impersonate`

Both are **prompts**, not dispositions — the confusion is only in the name. They differ by
disposition:

- **`roleplay`** keeps its meaning: an `append_to_body` prompt (writing dialogue into the
  manuscript).
- **`impersonate`** is the reserved name for the new `chat_panel` prompt where you *chat with* a
  character and the AI impersonates them. A distinct name so the two never collide.

`impersonate` is named here for a concrete reason, not built here: because it is a `chat_panel`
conversation whose **subject is a card** (the character), it appears in that card's **Conversations**
list *for free* — `chat_panel` and the subject-backlink surface (ADR-0051) already exist, so "chat
with this character, and see the thread on the card" needs no new machinery. Reserving the name now
keeps that path clear; the prompt itself and its character-brief wiring are a later slice.

### 5. The authoring UI grows to match

Because every disposition is authorable, the "Prompt defaults" editor exposes the **full**
disposition set, and — when `chat_panel` is chosen — the **optional commit block**: `review`, and a
**field-picker** for `commit.fields` (which fields this commit extracts). This is what lets a user
build their own brainstorm prompt with their own instructions, which today is impossible — and the
field-picker is a legible control, where `output.extract` was hand-written Jinja no editor could
surface.

## Why / rejected alternatives

**Keep `entry_patch` as a fifth `output.kind` value and just registry-ify the flat list.** The
smaller change: unify the vocabulary, add `entry_patch` to the dropdown, done. **Rejected** — it
formalises the confusion. `entry_patch` is genuinely `chat_panel` + commit; encoding it as a peer
disposition means every consumer keeps special-casing one value, and a second commitable
conversation kind (below) would need a *sixth* value rather than a `commit` on `chat_panel`.

**A fifth prompt base for brainstorm.** **Rejected** (ADR-0046's own conclusion): the four-base
taxonomy is deliberate and closed; brainstorm is a specialisation of `revise`, and commit is a
capability, not a base.

**Give `commit` its own top-level field, not nested under `output`.** **Rejected** — commit only
means anything for `chat_panel` output, so it belongs *under* `output` where the disposition lives;
a sibling field invites the invalid combination "commit with an inline disposition."

**Full `commit.target` now.** **Rejected as over-reach** (see out-of-scope) — the model leaves room
for it; building it is a separate, larger piece.

**Keep `output.extract` (arbitrary-Jinja contract override) as the commit's shaping seam.**
**Rejected.** `extract` (ADR-0051 S4) let a prompt replace the *entire* fresh-extraction contract
with hand-written Jinja — a full templating escape hatch, used by exactly one built-in
(`scene_summary`) for one narrow need: *fields-only, exclude the body*. That need is a declarative
`commit.fields: [summary]`, which is more legible (an editor can render a field-picker; it can't
render arbitrary Jinja), removes the awkward escaped-string-in-the-schema (#859), and keeps the
contract *generated* from `field_catalog` rather than partly hand-authored. The trade is the loss of
a *fully bespoke* contract (custom instructions or a novel JSON shape) — which nothing uses; if a
real need for one ever appears, that is the trigger to reconsider, not now.

## Anti-goals

- **Not a fifth disposition, not a fifth base.** The disposition axis is the original four; commit
  is a capability layered on `chat_panel`, never a new `kind` value.
- **Not the full `commit.target` feature.** This ADR makes `commit` an object so a target can be
  added later; it does not build target-selection.
- **Not a runtime rewrite of the brainstorm loop.** The chat→extract→review machinery
  (ADR-0046/0051 S4) is unchanged; only the schema shape and the routing predicate change.
- **No pre-1.0 migration.** The built-in brainstorm prompts are re-authored to the new shape and
  test projects are recreated — no migration script, no defensive reads.
- **`snippet` stays outside the axis.** It declares no output; the registry does not list it.

## User journey

A writer opens **Detail Types**, creates a prompt sub-type, and in **Prompt defaults** picks an
**Output**: *Append to body*, *Replace selection*, or *Chat*. If they pick **Chat**, an optional
**Commit** section appears — they tick it, choose how the result is reviewed (*visual diff* or
*replace*), and optionally pick which fields it extracts. They've just authored their own brainstorm
prompt — something the app currently only ships as built-ins. Elsewhere, the Chats pane's
"Openable" view keeps hiding brainstorm conversations, but now because it asks the registry *"does
this chat's prompt declare a commit?"*, not because it hardcodes a magic string.

## Consequences

- **`context_strategy.output` gains a shape** (a small Pydantic model, not a free dict), validated
  against the registry on save; `output.kind` becomes a closed, backend-known set.
- **The three built-in brainstorm prompts** (`prompt:revise:entry`, `:plot_card`, `:scene_summary`)
  move from `output.kind: entry_patch` to `output.kind: chat_panel` + `commit`.
- **Dispatch flips its question** from `kind === "entry_patch"` (`chatCommit.svelte.ts:81`,
  `ConversationsPanel`, `NodeEditor:483`, `Lore.svelte:79`) to "has a `commit`". `PromptSurface`
  and `defaultPromptForSurface` derive from the registry.
- **The Openable chat filter** (`builtinViews.ts`, ADR-0051 S6) keys off "has commit" instead of
  the `entry_patch` literal.
- **`output.extract` is removed.** The one built-in that used it (`scene_summary`) becomes
  `commit.fields: [summary]`; `render_extraction_contract` drops its `override_template` branch and
  instead filters `DEFAULT_EXTRACTION_TEMPLATE` by `commit.fields`. `field_catalog` and the default
  template stay; the arbitrary-Jinja escape hatch and the escaped-string-in-schema (#859) go.
- **The authoring UI** (`SchemaTypeEditor` "Prompt defaults") exposes all dispositions + the
  optional commit block (`review`, a `commit.fields` field-picker).
- **`roleplay` unchanged; `impersonate` reserved** as the `chat_panel` character-chat disposition.

## Slice plan — one lane, disjoint, vertical (reorderable)

- **S1 — the vocabulary + backend validation.** The output-disposition vocabulary as the single
  source, and save-time validation of `output.kind` against it. `output` stays a free dict for now;
  its Pydantic shape (with `commit`) arrives with the reshape in S2, since it is the `commit`
  addition that makes the shape worth pinning. No user-visible change; `entry_patch` kept valid.
  *(Shipped.)*
- **S2 — reshape: retire `entry_patch` + `output.extract`, give `output` a shape.** Model `output`
  as a Pydantic type (`kind` + optional `commit{review, fields}`); re-author the three built-in
  brainstorm prompts to `chat_panel` + `commit` (`scene_summary` → `commit.fields: [summary]`);
  filter the extraction contract by `commit.fields` and drop the `override_template` branch; flip
  every dispatch predicate to "has commit"; the Openable filter with it. Behaviour identical; the
  value and the seam are gone.
- **S3 — authoring UI.** Expose the full disposition set + the optional commit block (`review`, the
  `commit.fields` field-picker) in "Prompt defaults" — the capability to author a brainstorm prompt.
- **S4 — the `impersonate` prompt** — a `chat_panel` Library prompt with a character-locked brief;
  surfaces in the character card's Conversations for free (§4). Deferred; the name is reserved now.

## Deliberately out of scope (deferred, with a named trigger)

- **`commit.target` — a prompt naming the kind/type/subtype it commits to.** Today the commit
  target is inferred from the *subject* the chat was launched against (kind-neutral validation,
  ADR-0048 §5). A prompt could instead declare its target ("always commit to a new
  `lore:character`"), independent of launch context. `commit` is modelled as an object so this is a
  non-breaking addition. **Trigger:** the first prompt that needs to commit somewhere other than its
  launch subject — not built speculatively.
- **A second commitable conversation kind.** ADR-0051 §4 foresees one — a chat that extracts
  *"facts learned about this character"* rather than an entry patch. This ADR's `commit` object is
  where that second commit shape would attach; it is not built here.
- **A fully bespoke extraction contract** (custom instructions or a novel JSON shape, beyond
  choosing fields). This is what `output.extract` allowed and nothing used; the declarative
  `commit.fields` replaces its one real use. **Trigger:** a concrete prompt that needs a contract the
  generated one can't express — at which point a scoped escape hatch is reconsidered, not the old
  arbitrary-Jinja one restored by default.
- **Authoring `commit.target` / multiple commit shapes in the UI.** Follows the items above.
