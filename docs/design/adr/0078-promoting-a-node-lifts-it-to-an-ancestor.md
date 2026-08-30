# ADR-0078: Promoting a node lifts it to an ancestor and leaves the origin-only parts behind

- Status: **Accepted** — 2026-08-30, Anton. Shaped with Anton over the review that produced
  §4–§7 and the mutation-set / dynamic-include refinements, then put through a
  cold-implementer pass (the failure-pattern countermeasure) whose findings are folded in,
  with acceptance tests defined per slice (§Acceptance).
- Verified against `be10d00e` (2026-08-30, `nightly-307-gbe10d00e`).
- Feature: #1494 · Inverts the clone-down gesture (ADR-0049) and `fork_lore_entry`
  (#313 / ADR-0039) · Builds on ADR-0039 (the one layer walk; layer overrides #314) and
  ADR-0045 (scope is a property of the unit of work) · Relates ADR-0011/0055 (mutation sets
  as a node kind; a staged set is position-free), ADR-0074 (context-pick selectors),
  ADR-0075 (implicit context detection), ADR-0029 (the field model).
- Supersedes nothing. It implements the **"promote upward"** direction recorded as
  deferred in the project-hierarchies lineage (ADR-0039): "this Book 12 minor character
  is becoming recurring — move to series level."

## Problem

Inheritance is one-directional. Ancestor content flows **down** into a descendant as
read-only, and the only affordance for making it yours is to **clone/fork it down**
(ADR-0049; `fork_lore_entry`). There is no way to go the other way: author a node in a
descendant, realise it belongs higher, and **lift it into an ancestor** so the ancestor
owns it and every descendant inherits it.

Every mutation today is scoped to a single project. `move_structure_node`,
`move_research_node`, `move_metadata_field` all bind to one `_require_project()` and take
a `target_parent_id` / `target_layer_id` *within that project's own resolution*. No
service moves a node **file** from one project's folder into another's.

The driver is concrete dogfooding: a short story authored as a **sibling** of an existing
book, under a shared parent project, wants to reuse shared canon. A character (Alice)
introduced in Book 2 should become a series-level character; a set of prompts and style
guides should live at the project root that both siblings inherit. Promotion is what lets
canon authored in one descendant become shared canon for its siblings.

## Decision

**Promoting a node moves the file it owns up into a declared ancestor project, keeping the
node's id. Its content travels by default; the parts that would assert something false at
the destination — a reference to an origin-local node, a tag the destination does not know —
stay behind as a layer override on the origin. A node's hard dependencies must be
satisfiable at the destination, cascaded up with it. The whole move is shown as a plan the
author confirms before anything is written.**

The ancestor is reached the way `move_metadata_field` (`schema.py:687`) already reaches one
— as a **layer in the origin's own chain**, addressed by `target_layer_id` and resolved
through `layer_by_id` (`layers.py:318`). Promotion introduces **no** second open project
and no two-project transaction; it stays inside ADR-0045's single resolution scope, which is
the origin.

### 1 — The id is preserved; the origin inherits the node back

The moved file keeps its front-matter `id`. Every inbound reference resolves by id through
the layered candidate stack, so keeping the id means backlinks survive untouched — the
resolution winner simply becomes the ancestor's copy. This is `fork_lore_entry`'s downward
reasoning (`lore.py:381`) read in reverse; note it also means promotion does **not** call
`_purge_references_to` (the delete path does), because nothing is severed.

From the origin's chair the node changes from **owned** (authored here) to **inherited**
(owned by the ancestor, visible here through the chain), like any other ancestor node.
Minting a new id was rejected — see Alternatives.

### 2 — You promote what you own, to a declared ancestor project

- **Owned-here only.** An already-inherited node cannot be promoted (409). This **inverts**
  the guard `fork_lore_entry` carries — fork refuses when the node *already lives here*
  (`lore.py:397`); promote refuses when it *does not* (the node is inherited, not owned) —
  so the coder flips the predicate, not copies it.
- **The target is a *declared* ancestor project.** The candidate set is the origin's layer
  chain (`layers.py`, `collect_layers`) filtered to layers that are **projects** (not the
  Library or machine folders) **and** declared in the origin's `inherits:`. The origin must
  actually inherit from the target, or promoting there would make the node **disappear from
  the origin** (moved out, not inherited back). With no declared ancestor project, the
  affordance is absent.

### 3 — Travel by default; the resolver already hides what does not belong

Content travels up on the file. It does **not** need per-field promotion machinery to look
right at the destination, because the read path already projects a node against the scope it
is read in: `read_lore_entry` runs `_strip_unknown_metadata_fields` and
`_strip_dangling_references` on every resolve (`lore.py:135`). So:

- A **scalar** whose field is defined only in the origin travels on the file and is
  **auto-hidden** at the destination (unknown field → stripped from the resolved view),
  non-lossily. It reappears wherever its field is defined — the origin, and any descendant
  that defines it — and it is **ready to light up** if its field *definition* is later
  promoted (§8). This is why an out-of-scope scalar is *not* pushed into an override: an
  override would strand it from that later definition move.
- A reference whose target is out of scope is stripped from the resolved *view* on read —
  **but only the view.** The persisted **edge is not** (§4).

The established model already works this way (ADR-0045's faction example: move the picker to
series and the field "disappears", move it back and it "returns" — the value never moved,
only its visibility). Promotion inherits that behaviour rather than re-inventing it.

### 4 — Leave behind only what would leak origin-local structure upward

Two kinds of value would, if they travelled, leak into a layer that must not carry them.
These do **not** travel; they are stripped from the promoted file and rewritten as a sparse
override on the origin, keyed by the node's (preserved) id, through the #314 path
(`_diff_metadata_to_override_rows` → `_write_override_file`, `overrides.py:314`/`:202`).

- **A static reference (`entity_ref` / `entity_ref_list`) whose target lives below the
  destination.** The *field* belongs on the node, but the *entity it points at* cannot
  travel (it is origin-local), so the reference becomes an origin override — Anton's rule.
  Worked case: Alice owns `location → "The Rusty Anchor"`, a Book-2 place. Promote Alice to
  Series; `location` becomes a `book2/overrides/alice` delta. Book 2 sees Alice (now
  inherited) and the Rusty Anchor (owned) and the edge resolves there — and only there,
  which is right, because the relationship is Book-2-specific.
  **This is an integrity necessity, not merely tidiness.** The read-time
  `_strip_dangling_references` hides the ref in the *view*, but edge extraction does not
  apply it: `_edges_from_field` builds a `ReferenceEdge` for any non-empty string target
  with no scope check (`references.py:1214`). So a ref that *travelled* would leave a
  **dangling edge in the ancestor's (and every sibling's) node index**, pointing at an
  out-of-scope node. Leaving it behind is what keeps those indexes clean, and authors the
  edge in the one scope where both ends are visible.
- **A tag the destination does not know.** Tags are freeform but *layered* — a tag becomes
  "known" at a layer by being **used** there (`read_known_tags(up_to_layer_id=…)`,
  `services/project/tags.py:93`). A tag is a valid field, so unlike a scalar or a dangling
  ref it is **not** stripped on read — it would register in the destination's known-tags
  vocabulary, polluting the shared tag space with a book-local tag. So a tag already known
  at the destination travels; a tag not known there stays behind as an origin override.

**When a field is *both* origin-only-defined (§3) and holds an origin-local ref (§4), §4
wins** — the reference stays behind. The edge-integrity argument above is independent of
where the field's *definition* lives, so an origin-local ref is never allowed to travel.

**The unifying rule:** travel by default; leave behind as an origin override only what would
**leak origin-local structure upward** — a dangling index edge, or a tag into the shared
vocabulary. Everything else travels and is filtered live by §3's read-time strips.

### 5 — Dynamic references travel and re-resolve; the plan lists them

A static reference stores a target and can dangle. A **dynamic** reference stores a
*predicate* — a name matched against in-scope lore (implicit detection, ADR-0075,
`services/ai/lore_selection.py`) or a `context_pick` selector resolved against in-scope
nodes (ADR-0074, `services/ai/selector_eval.py`). A predicate does not dangle; evaluated
from the destination it resolves to a **different, possibly smaller set** — which is what a
dynamic reference is *for*. So dynamic references **travel untouched and re-resolve**, and
the promotion plan (§9) **enumerates them by name** so the author sees exactly which
predicates will resolve against the new scope. They are warned, never rewritten: a query is
not ours to edit.

This axis is **kind-dependent**, and for the first node kinds it is nearly empty. Lore
metadata carries no selector — `entity_ref` / `entity_ref_list` are its only reference
field types; `context_pick` / `scene_ref` are **prompt-input** types (`models/base.py:55`),
carried by prompts and chats, not by a character. So promoting **lore has no dynamic-
reference branch** — only §4's static partition, plus body prose that fails soft. The
dynamic branch is real for prompts and chats (their `context_pick` inputs) and is the whole
substance of a **view** (Scope).

### 6 — A prompt's includes are the one hard dependency, and must cascade

A prompt's `{% include %}`d snippets are the **only hard dependency** promotion faces —
neither soft (§5) nor partitionable (§4), and embedded where they cannot be separated from
the node. Prompts render from a string under `StrictUndefined` (`templates.py:21`, `:153`),
so an unresolved include **raises** rather than resolving empty, and the include lives in the
template body, which cannot be split. So promoting a prompt requires its include-closure to
be satisfiable at the destination: **the plan computes the closure and cascades it — promotes
the included snippets together — refusing only when a member is itself unpromotable** (e.g. it
resolves to a book-local node that cannot go up). Cascade matches the real gesture: you lift a
*set* of reusable prompts as a unit, not one stranded above its includes.

(Mutation sets are **not** a hard dependency of the node they touch — see §7. Nothing about
them raises, so they are surfaced, not cascaded.)

**Closure discovery is static, and its blind spot must be surfaced.** A prompt's includes
become node-index edges only for **literal** names — `literal_include_names`
(`effective_inputs.py:199`) yields nothing for a computed `{% include input.x %}`. So the
cascade can follow literal includes but **cannot see a dynamically-named one**; a prompt
that has one would raise at the destination under `StrictUndefined`, the exact failure this
section exists to prevent. The plan therefore **flags a prompt with dynamic includes as
un-closable** rather than silently reporting its closure satisfied — the author is told the
guarantee does not hold for that prompt.

### 7 — A staged mutation set is a promotable kind, surfaced but not cascaded

A staged mutation set is **position-free** — a chat owns it as "its staged, position-free
change" (`models/ai.py:584`), pointed at by the chat's `staged_set` entity_ref
(`chats.py:84`) — so, unlike a scene, it has no manuscript anchor and is portable like lore.
Its shape (`models/entries.py:732`) is a list of `(field, op, value)` `MutationSetRow`s that
**store no entity** ("the set is a template bound to an entity on use"); the only entity link
is the *optional* `target_entity` pin (`entries.py:750`: `""` = a reusable template, set = a
pinned one-off).

**A mutation set is not a hard dependency of the node it touches.** Contrast a prompt include
(§6): promote a character and a staged set pinned to her **keeps working from the origin** —
the pin survives by keep-id (§1), and nothing raises if the set stays put. So promoting a
*node* does **not** cascade its mutation sets. Instead the plan **surfaces them as a soft
note** — "Alice has N staged mutation sets pinned to her; they keep working from Book 2 —
promote them separately to share them at Series" (discovered via her backlinks,
`edges_by_dst`) — and the actual move is its **own gesture**.

That gesture is this slice (Scope, slice 4): promoting the *set itself*.

- A **reusable template** (`target_entity == ""`) is the clean, common case "staged" points
  at: no entity pin, so its only dependencies are the row `value`s that are entity ids or
  tags, and the fields the rows target — subject to the destination-visibility test.
- A mutation set promotes **atomically**: its rows are not partitioned (a set is a bundle,
  not a metadata bag). An origin-local **pin** is *its* hard dependency and follows §6
  (cascade the pinned entity, or refuse); a **row whose `field` is defined only in the
  origin** goes inert at the destination until that field *definition* is promoted (§8), like
  a §3 scalar.
- A **pinned one-off that has been `placed`** (`entries.py:756`) is anchored in a scene and
  is book-local (§Scope) — promotion is a **staged, un-placed** affordance.

**Why surfaced-not-inlined** (deliberate asymmetry with §8's inline field-definition offer):
a field-definition lift is a lightweight schema-layer shuffle worth bundling into the
dialogue; a mutation-set promotion is a whole second node-promotion with its own partition,
pin dependency, and preview — cleaner as its own confirmed gesture than as a plan nested
inside the character's.

### 8 — Promoting a field *definition* is a separate, composable gesture, offered in the dialogue

Making an origin-only field (§3) visible at the destination means moving its **definition**
up. That capability exists on the backend — `move_metadata_field` (`schema.py:687`) resolves
`target_layer_id` through the chain (`:689`) and writes the ancestor's `metadata.schema.yaml`
(`:716`) — but it has **no UI caller** (`api.ts:681` is invoked by nothing), so today a user
cannot perform it. Wiring it up is its own gesture (Scope, slice 1). Once it exists, the
promote dialogue **offers it inline**: for each field that would go invisible, an "also lift
this definition to `<destination>`" control that calls the same `move_metadata_field`. Three
decisions this pins:

- Node promotion and field-definition promotion are **distinct gestures that compose in one
  dialogue**, not one merged operation.
- A field definition is **per entry-type, not per node**. "Lift `faction` to Series" lifts it
  for **every character**, not for Alice alone — there is no per-node field definition in the
  model. The control must say so; it cannot present as Alice-only.
- The inline call must pass the **promoted node's `entry_type`**, not the request default of
  `manuscript:scene` (`models/schema.py:487`), or it moves the wrong type's field.

### 9 — The move is previewed as a promotion plan the author confirms

A promotion has several effects and removes a file from the origin, so it is **never
silent**. The backend computes a **promotion plan** — the §4 partition, the §6 dependency
closure, the §5 re-resolution list, the destination — as a dry run that writes nothing. The
dialogue renders it in named buckets, each item spelled out:

- **Travels up** (owned by the destination after this),
- **Stays in the origin** (as a local override — the origin-local refs and unknown tags,
  each named),
- **Also promoted** (the cascaded include-closure of §6, listed; a prompt with an
  un-followable dynamic include is flagged here as un-closable → the promotion refuses),
- **Resolves differently** (the §5 dynamic references, listed; with the §8 offer where a
  field would go invisible),
- **Related — promote separately** (the §7 soft note: staged mutation sets pinned to the
  node, which keep working from the origin and are not moved by this gesture).

Confirming executes the **same plan**. One partition function, two entry points (preview /
commit), so what the author approved is what runs.

### 10 — Index maintenance and cross-session staleness

Commit writes into the ancestor's folder, deletes the origin's copy, and writes the origin
override, then invalidates so the origin's index re-resolves the node as inherited. Because
the write lands in a folder on the origin's own chain and the origin gains an override, the
origin's write path takes its cold-rebuild branch and re-resolves the promoted node as an
inherited (ancestor) candidate with the override folded — so the origin sees the result
without a manual reopen. Another session with the ancestor (or a sibling) open sees the
change only at its next unit boundary — a reopen — per ADR-0045's rule that staleness is
detected at unit boundaries, not prevented mid-flight. This is accepted, not worked around.

## Scope

**In scope, sliced:**

1. **Field-definition promotion UI.** Wire the existing `move_metadata_field` into the schema
   editor as "move this field to another layer." Standalone (it closes a real gap — the
   capability is unreachable today) and a prerequisite for §8's inline offer, so the promote
   dialogue never shows a dead-end "lift it later" with no way to lift.
2. **Lore node promotion** — §1–§4, §9, §10: keep-id lift, the §4 partition (origin-local
   refs and unknown tags behind, everything else travels), the plan + confirm dialogue, index
   invalidation. The slice that exercises the static partition (Alice).
3. **Prompt / style-guide promotion** — adds §5's dynamic branch (`context_pick` inputs,
   prose) and §6's include cascade (with the dynamic-include blind spot flagged). May be
   pulled ahead of slice 2 if the dogfooding need (prompts and style guides to the root)
   comes first; its §4 partition is thin.
4. **Staged mutation-set promotion** — §7: §6 closure on the optional pin and entity-valued
   rows, atomic (no row-level stay-behind), staged-and-un-placed only.

**Out of scope — recorded as deferred, with the reason, and deliberately without a sketch of
how they slot back in:**

- **Views and chats.** A view's substance *is* a selector and a chat curates `context_pick`
  sets; promoting them is governed by §5's re-resolution, whose semantics for a node that is
  nothing but a predicate need their own pass.
- **Scenes, research notes, and placed mutation sets.** They are book-local — scenes and
  research have no defined position in an ancestor's tree, and a placed mutation set is
  anchored in the manuscript (`fork_lore_entry` names the same asymmetry: "scenes and
  research notes are book-local", `lore.py:389`). Giving any of them an ancestor position is
  a separate design.

## Alternatives considered

- **Mint a new id on promotion** (as `fork_prompt_entry` does downward). Rejected: every
  inbound reference to the old id in the origin would have to be re-pointed or purged
  (`_purge_references_to`). Keep-id makes the move reference-transparent.
- **Push every origin-specific value into an override, scalars included.** Rejected: §3's
  read-time strip already hides an out-of-scope scalar non-lossily, and an override would
  strand the value from a later field-definition promotion (§8). The override-behind is
  narrowed to what would *leak upward* (§4).
- **Let a hard dependency dangle and rely on the read-time strip.** Rejected for §6: a
  prompt include raises under `StrictUndefined` — it must be satisfied, not hidden. (Its
  counterpart when a *set* is the thing promoted is the set's own pin, §7.)
- **Cascade a node's mutation sets with it.** Rejected (§7): a mutation set does not raise if
  left behind — it keeps working from the origin by keep-id — so it is a soft, separately
  promoted related node, not a forced cascade like a prompt include.
- **A second open project / a two-project transaction primitive.** Rejected as unnecessary:
  the ancestor is reachable as a layer within the origin's chain (the `move_metadata_field`
  precedent), so promotion stays within ADR-0045's single scope.

## Consequences

- New endpoints (promotion preview + commit), a promotion-plan model, a confirm dialogue,
  the cascade computation, and the field-move UI of slice 1.
- Promotion **widens visibility to every descendant** of the target ancestor — that is what
  "promote to a shared level" means, and it is the intended outcome for the sibling short
  story. A descendant that later does not want to see a shared node is the existing Library
  "hide" concern (ADR-0049), orthogonal to this.
- The origin gains a layer override it did not have; the ancestor gains an owned node. Both
  are ordinary artifacts of the existing model, needing no new storage concept.

## Acceptance

Each slice lands with acceptance tests written **first (red), green on completion**, at the
**backend service level against a fixture chain** (root → series → book), asserting observable
invariants — not endpoint or method signatures, which would thrash as the implementation
firms up. A test earns its place only if a plausible wrong implementation fails it (the repo's
mutation-testing bar); the **★** tests exist specifically to trip the cold-implementer traps.

**Slice 2 — lore promotion (the exemplar set):**

1. Promote an owned entry to the series layer → its file is now under `series/lore/`, its
   front-matter `id` is unchanged, and the book copy is gone.
2. Promote **refuses 409** an already-inherited entry, and **refuses** a target that is not a
   declared ancestor project.
3. **★ Origin-local ref stays behind and leaves no edge upward.** Alice's `location →
   RustyAnchor` (a book place): absent from the promoted file; present as a `book/overrides/
   alice` delta; resolves when Alice is read from the book; absent when read from series; and
   **the series node index holds no edge Alice→RustyAnchor** (catches the rank-direction flip
   and any travel-the-dangling-edge regression).
4. **Unknown tag stays behind:** a tag not known at series becomes an origin override, and
   **series known-tags does not gain it**.
5. **Scalar with a book-only field** travels on the file, is hidden when Alice is read at
   series, and is present when she is read at the book.
6. **★ Keep-id backlinks survive:** a node that referenced Alice still resolves to her.
7. **★ Ordering:** the stay-behind override is written after Alice is inherited, so the book
   resolves the override value (mutation-checked — a wrong order silently drops it).
8. **Preview is a pure dry-run:** returns the correct buckets (travels / stays / related) and
   writes nothing to disk.

**Slice 1 — field-definition promotion:** moving a field to an ancestor layer rewrites both
layer schemas; the open project re-resolves the field at its new home (the write-funnel-bypass
check, finding 6 below); a built-in field offers no move.

**Slice 3 — prompt promotion:** a literal-include closure is cascaded and lands owned at the
destination; **★ a prompt with a dynamic `{% include input.x %}` is refused with the
un-closable reason**, not silently promoted; a `context_pick` input travels and is listed
under "resolves differently".

**Slice 4 — staged mutation-set promotion:** a reusable template (no pin) promotes atomically;
a set pinned to a book-local entity is refused (or cascades the pin); promoting a *character*
does **not** move her pinned sets but lists them under "related — promote separately".

## To verify / build at implementation (flagged by the cold-implementer pass)

- **The "visible from the destination layer?" test is net-new.** The `up_to_layer_id`
  as-of-layer truncation exists for schema (`schema.py`) and tags (`tags.py:93`) but **not**
  for the node index — `entry_at_layer` matches an *exact* layer, not "at or above". Build it
  over `index.candidates[target_id]` + `IndexLayer.rank` (pick the max-rank candidate with
  `rank ≤ destination.rank`); **watch the rank direction** (outermost/Library is the low end,
  the open project the high end) — an inversion silently mis-partitions.
- **`move_metadata_field` writes the ancestor schema via `_write_yaml` directly**
  (`schema.py:716`), not through the index write-funnel. Confirm the open project re-resolves
  after a cross-layer field move (add a test); another open session stays stale until reopen
  (§10, accepted).
- **The override *create* inverts `fork_lore_entry`'s override *drop* (`lore.py:438`), and
  the ordering is load-bearing:** write the stay-behind override **after** the node is
  inherited at the origin — `read_lore_entry` only folds an override once the winner is not
  the local layer. Validate through the same #314 path (`services/project/overrides.py`).
</content>
