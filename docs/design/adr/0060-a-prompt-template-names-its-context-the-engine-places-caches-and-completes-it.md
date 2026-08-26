# ADR-0060: A prompt template names its context; the engine places, caches, and completes it

- Status: **Accepted** — 2026-08-17 (approved by Anton; authored by Claude). Origin:
  dogfooding — writing custom prompts against `docs/prompts/`, whose language references have drifted from
  the code, surfaced that the *language itself* is half a declaration surface (lore is backend-placed,
  ADR-0057) and half an assembly surface (the author still hand-emits text, hand-marks cache breaks, and
  reaches into field internals) — and the two halves contradict each other at the cache boundary.
- Follows: ADR-0006 (lore is resolver-mediated at `_format_lore_block`), ADR-0012 (scene-ref resolution
  precedence — the single as-of anchor), ADR-0026 (type-aware Jinja helpers — `is_a` on a shared
  ancestry primitive; this ADR generalises "typed" to the whole surface), ADR-0054 (a prompt picks a
  disposition), ADR-0055 (as-of-scene reads; the staged-set 1h block), ADR-0057 (a conversation selects
  its lore once behind one gate), ADR-0058 (a provider is a class registered once).
- Governed by: the layered context envelope's cache-coherence tradeoff and its authoritative statement in
  `docs/design/context-caching.md` (the stable-prefix/volatile-suffix contract, §2/§4/§7); the 1.0
  template-surface freeze (`reference_roadmap` — additions stay allowed after 1.0, existing shapes don't
  change, so a breaking simplification is a pre-1.0-only move).
- Vehicle: implementation sliced per §Suggested slicing (issues filed post-merge).
- Citations pinned to `master@cb9d2828`. Line numbers rot; **function/symbol names and file paths are the
  durable references.**

## Amendment 1 (2026-08-19) — includes are role-less; the check must know the live helper set

Two prompt-language gaps surfaced while working the prompt-output model (ADR-0065 Amendment 1 / ADR-0067):

- **An include carries no `{% role %}`; the includer assigns the role.** Today an include that holds its own `{% role %}` block errors when it lands inside the includer's `{% role %}` (nested roles). The workable rule: an **include is a role-less fragment** (raw text), and it is the **includer** that wraps `{% include %}` in the proper `{% role "system" %}` / `{% role "user" %}`. This removes the nested-role error for shared boilerplate (a house-style voice, a settings block). (The include mechanism itself is ADR-0061; this is the role constraint on it. In the UI it is surfaced as "include," not "snippet" — see the ADR-0062 amendment. Note: the output field contract is **not** an include — it is authored inline via the `field_contract` accumulator, ADR-0067.)
- **The check must derive its known helpers from the live registry, not a stale list.** The prompt template check (the render/diagnostics that flag template errors) rejects legitimate ADR-0060 helpers — e.g. any use of `use()` flags as an error — because its notion of "known globals" drifted from what `register_helpers` (`services/ai/helpers.py`) actually installs. The fix is structural: the check's known-helper/known-global set must be **derived from the same registry the runtime uses** (so it can never drift again), and it must recognise the additions ADR-0067 makes — the `field_contract` accumulator and the newly-enabled `{% do %}` construct. A helper the engine provides, or a tag it enables, must never be an error in the check that guards the same engine.

## Amendment 2 (2026-08-26) — the default role envelope is not per-type; loose prose homes to a fixed `system`

§4 gave each prompt **base type** a `default_role` envelope resolved up the `parent:` chain. Post-ADR-0065 that is both moot and a smell: there is exactly one non-abstract prompt base (`general`), and it declares `default_role: "system"` — identical to `_resolve_default_role`'s own fallback, so the field does no work. To make loose prose home anywhere else you would have to mint a new sub-type — the proliferation ADR-0065 removes. (§4's base-type list — `continuation`/`revise`/`general`/`snippet` — is itself stale; only `{base, general, snippet}` remain.)

**The rule replacing §4's envelope:** the engine homes un-roled prose to a fixed **`system`**; `{% role %}` stays as the per-body override for the uncommon multi-role prompt — the full range of expression, with nothing on the type.

Mechanically: the per-type `_resolve_default_role` chain-walk and the `default_role` schema field (`PromptEntryTypeExtras.default_role`) are removed; the send path passes the constant `system` to `render_template`. Loose prose is therefore always homed — the legacy warn-and-drop (`default_role=None`) is no longer reachable from the send path. Byte-identical output for every shipped prompt (only `general` declared it, `= system`). Removal of `PromptEntryTypeExtras` in full is recorded in ADR-0065 Amendment 2.

Anti-goal: `default_role` does **not** move to the instance — a prompt wanting a non-system home writes `{% role %}`; the default stays a fixed convention, not a knob.

## Context

A prompt template is a Jinja2 body (`body_language: jinja2`) rendered by a `SandboxedEnvironment`
(`services/ai/templates.py`) against a fixed namespace and a set of helper globals
(`register_helpers`, `services/ai/helpers.py`). It is the surface a writer authors against to shape what
an AI sees. Five properties of that surface, each **verified against the code**, are now in tension:

1. **Caching moved into the backend; the language did not follow.** ADR-0057 / #1048 made lore
   *backend-placed*: a template only *declares* use via a gate-only `use_lore()`, and the send path
   selects, dedupes, tiers, and caches. `docs/design/context-caching.md` §4 makes this the durable rule.
   But the rest of the language is still assembly-era: an author pastes text (`{{ entry(x).body }}`,
   `full_text()`, `scenes_before()`), hand-marks cache breaks (`{% cache_break %}`), and reads fields
   through `base`/`effective` helpers.

2. **`{% cache_break %}` is dead on live calls.** `build_chat_payload` (`services/ai/preview.py`)
   flattens every message's blocks into one string (`"".join(block.text …)`), discarding the
   `cache_break_after` flags; real breakpoints are synthesised backend-side
   (`system_prompt_cache_blocks` / `_lore_cache_blocks`, `services/ai/chat.py`). `{% cache_break %}` and
   `relevant_lore(partition=…)` survive only into the **preview** token estimate
   (`estimate_preview_tokens_and_cost`). `context-caching.md` §2a/§9 flags both as candidates to retire.

3. **Emitting lore from a template double-includes it (latent).** `relevant_lore()` both returns lore
   text *and* flips the `lore_invoked` slot (`_relevant_lore_helper`, `helpers.py`), which becomes the
   chat's `lore_enabled` flag (`preview.py` → `chats.py` → `chat.py`) — the same flag that makes the send
   path inject its *own* backend copy. There is no dedup between the inline copy echoed into the system
   prompt (`system_prompt_cache_blocks`) and the backend blocks (`_lore_cache_blocks`). So any custom
   prompt using the emitting form ships lore **twice**. It is latent only because both built-ins use the
   gate-only `use_lore()` (`builtin_library/prompts/roleplay.md`, `revise-entry.md`); the emitter's own
   comment in `helpers.py` admits the trap.

4. **The caching model leaks Anthropic's shape.** Anthropic-specific: the **4-breakpoint** cap, the
   `cache_control` marker, the `"5m"/"1h"` ttl vocabulary. Universal: **most-stable-content-first
   ordering** — the only thing OpenAI's automatic prefix caching can use, what Anthropic exploits with
   breakpoints, a no-op for Ollama (`profiles/*`, `context-caching.md` §3a).

5. **Vocabulary describes internals, not stories, and one traversal cannot be done at all.**
   - `input.<name>` for a `context_pick` reaches the template as a **raw `JSON.stringify` string** of the
     picked items (`PromptInputField.svelte`, passed through untouched at `preview.py`), so
     `{% for item in input.x %}` iterates *string characters* and `entry(input.x)` returns only the first
     pick. There is no `fromjson` filter and no list-returning ref helper. The documented iteration
     example (`docs/context-picker.md`) does not work; a test comment concedes it is "a follow-up."
   - `node.<field>` **already works on entries** via a metadata fallback (`EntryRef.__getattr__`,
     `entry_ref.py` — its comment: so authors write `honor.home_planet.title`, not
     `honor.metadata.home_planet.title`), but **not on `project`/`novel`** (`ProjectInfo.metadata` is a
     plain dict, no fallback), so the writer is forced into `project.metadata.<field>` there. The
     capability is real but inconsistent and undocumented.
   - Four overlapping ways to read a field value — `base`, `effective`, `entry`, `entry_as_of` — where a
     writer thinks only *"the value now"* vs *"the value at this scene"*; a `novel` bare-alias of
     `project`; `plain_json` next to Jinja's `tojson`; and text outside `{% role %}` silently discarded
     (`_check_trailing_text`, warning only).

The single as-of anchor already exists and is not per-pick: a scene marked ★ in a picker, or a
`scene_ref` input, or the caller's target, or a bound chat's subject — resolved in one ordered chain
(`_find_marked_target_scene_id` → `effective_scene_id`, `preview.py`; ADR-0012) — becomes *the* `scene`
binding for the whole render.

## Intent

**A prompt author names *what* context they want and *which message* it belongs in, in the vocabulary of
their story. The engine owns *where it caches* and *how each provider sees it*, and the surface is typed
so an editor can complete it.**

Three concerns, currently fused into overloaded tags and side-effecting helpers, are separated and given
their proper owner:

| Concern | Question | Owner |
| --- | --- | --- |
| **Selection** | *What content goes in?* | the **author** — full graph / corpus / picker traversal |
| **Volatility / placement** | *Which cache tier, on which provider?* | the **engine** — dynamic per-revision, provider-neutral |
| **Role** | *Which message?* | mostly **implicit** from the prompt's base type; explicit only to override |

## Anti-goals (what this must not do)

- **No static stability label in any form** — not `{% cache "static" %}`, not `partition="stable"`.
  Stability is *dynamic*, decided per turn by each entry's `revision` (ADR-0057 §7 correction;
  `context-caching.md` anti-goal #2). A static label re-writes the growing set every turn and never lets
  an entry settle — the exact bug #1048 removed. (The optional `use(node, "stable"|"volatile")` hint (§2)
  is *not* this: it seeds the initial placement bet, but the revision diff still governs correctness each
  turn — an advisory prior, not a static override.)
- **No author-placed cache breakpoints, ttls, or block counts.** The *mechanism* — where breakpoints
  land, which ttl, how many blocks — is Anthropic-adapter concern and never reaches the language. The one
  thing the author *may* express is a semantic per-node **volatility hint** (`use(node, "stable" |
  "volatile")`, §2/§5): a two-valued prediction that steers placement, is bounded by revision-correctness
  (never rides stale bytes), and adds no breakpoints — a prediction about content, not control of the
  cache machinery.
- **No template emits lore or corpus text inline.** It double-includes (Context §3) or lands in an
  uncached flattened user message (`context-caching.md` §9). Selection replaces emission.
- **No second lore matcher for author-selected nodes.** Author selections feed the *one* selector
  ADR-0057 already owns; they are inputs to the dedupped set, never a rival channel.
- **No silent discard of authored text.** Every span has a home role.
- **Do not re-litigate the send-path cache assembly.** This ADR changes what the *author* can say and how
  selections *reach* the assembly; the assembly itself (ADR-0057 §7 / `context-caching.md` §4) is
  upheld, not reopened.
- **No new user-facing knob** where a declaration will do — selection is expressed by *calling* a helper
  (the ADR-0057 gate principle), not by a checkbox.

## User journey

**A — walking a picked list (the traversal that cannot be done today).** The writer authors a "continuity
check" prompt with a `context_pick` input `reference_scenes` (multiple). In the body they loop the picks
and pull each into context. `inputs.reference_scenes` is a **list**, each item usable directly; each
`use(pick)` adds the scene to the backend's tiered, cached set. *(Today: `input.reference_scenes` is a
JSON string; the loop iterates characters; only the first pick is reachable.)*

**B — pulling a graph neighbour, cached correctly.** A roleplay prompt references `scene.pov.home_planet`.
The author writes `{{ use(scene.pov.home_planet) }}` — no `.metadata.`, no pasted body. The planet lands
in the tiered lore set at the right freshness, once, as-of the scene. *(Today: `{{ entry(x).body }}` in a
user block ships it uncached every turn — the roleplay bug's class.)*

**C — reading a field as-of the story's moment.** In a scene-anchored prompt the author writes
`{{ entry("honor").allegiance }}` and gets Honor's allegiance *as of this scene*. In a scene-less
brainstorm the same expression gives the book-start value — `entry == original` — with no ceremony and no
error. *(Today: they must choose between `entry`/`entry_as_of`/`base`/`effective` and recall which
carries the scene.)*

**D — a prose-first prompt with no role scaffolding.** The writer types a plain instruction paragraph and
nothing else. It is sent, in the base type's default message. *(Today: with no `{% role %}` block it is
silently discarded.)*

**E — a custom prompt on a non-Anthropic provider.** The author writes the same selections; on OpenAI the
engine simply orders stable-first and lets automatic prefix caching work; on Anthropic it places ≤4
breakpoints; on Ollama it collapses to a string. The author wrote nothing provider-specific.

**F — the author knows the churn the revision stream can't predict.** In a roleplay prompt the POV
character is a fixed backdrop for the whole chat, so the author writes `use(pov_id, "stable")` and it
serves from the cheap 1-hour tier from turn one, skipping the settle. In a separate character-development
brainstorm the author is actively rewriting the love interest's goals every turn, so `use(love_id,
"volatile")` pins it to the 5-minute tier and keeps it out of the stable block it would otherwise thrash.
Same node, opposite hint, decided by the prompt's job. If either guess is wrong the revision diff still
sends current bytes — the hint only moved the cache bet. *(Today: no such lever; the reactive heuristic
mis-tiers both for a turn.)*

## Decision

### 1. Three concerns, three owners

The language is refactored so that **selection is author-driven, placement/volatility is engine-owned and
provider-neutral, and role is implicit from the prompt's base type.** Everything below is a facet of that
one separation, not an independent decision.

### 2. Selection: the `use()` family; inline emitters retire

A prompt selects context by adding nodes to the backend's managed set through helpers that **emit nothing
inline**:

- `use_lore()` — kept: "include the auto-detected lore set" (the ADR-0057 gate, unchanged).
- **new `use(node)`** — "also include *this* node in context." Accepts any `EntryRef` (lore, scene, plot
  card — everything is a Node), so one helper covers a hand-picked entry, a walked graph neighbour, or a
  scene, and works inside a loop over a picked list. A selected node keeps its `revision`, so by default
  the backend tiers it **dynamically** (stable if unchanged since last turn, volatile if new-or-changed,
  ADR-0057 §7) — selecting it never freezes its tier.
- **new `use(node, "stable" | "volatile")`** — an **optional volatility hint**: the author's
  forward-looking bet about whether *this node changes while this prompt runs* — which the backward-looking
  revision diff cannot know in advance, and which is a property of the *prompt's job*, not the node (the
  same character is a fixed backdrop in a roleplay chat and the churning subject in a character brainstorm).
  `use(pov_id, "stable")` starts the POV character in the cheap 1-hour tier and skips the turn-1 settle;
  `use(love_interest_id, "volatile")` pins an actively-edited entry to the 5-minute tier so it never
  thrashes the stable block by being promoted then re-edited. The hint is **advisory and bounded by
  correctness** (§5): it steers *placement only* — a `"stable"`-hinted node that actually changes still
  re-writes its block that turn, so the model never sees stale bytes. No hint → today's dynamic tiering.
  Because there are only two tiers, the hint sorts a node between existing blocks and adds **no**
  breakpoints (the 4-cap is untouched); `"stable"`/`"volatile"` is a semantic prediction, not
  `1h`/`5m`/breakpoint vocabulary (`author_vs_runtime_authority`: trust the designer).

Retired, because they emit into flattened/uncached or double-counted positions (Context §3):
`relevant_lore()`-as-emitter (the gate `use_lore()` remains), and raw full-body corpus emission
(`full_text()`, or pasting a scene/lore body) — those are *selected* via `use(...)` so they land in the
cached, tiered path. Derived recap helpers that emit a bounded, per-scene-stable block
(`story_so_far`, `plot_context`) are **not** retired — see the emit/select line in §7. The
list-returning coercion of a `context_pick` input into `list[EntryRef]` happens **at the bind layer**
(`preview.py`, where `context["inputs"]` is built), so the template author never learns it was JSON on
the wire and needs no `fromjson`.

### 3. Field access: `node.<field>` everywhere; state is bound at construction

- **`node.<field>` is the norm on every node-like object** — entries *and* `project` — with
  `.metadata` kept as the explicit escape (whole-map iteration, or a field shadowed by an intrinsic).
  Intrinsics (`id`, `title`, `body`, `entry_type`) win collisions — the rule `EntryRef` already applies.
  This generalises the existing `EntryRef.__getattr__` fallback and extends it to `ProjectInfo`.
- **State is bound when you obtain the node, read uniformly by attribute.** The four field-readers
  collapse to one constructor with an optional anchor:
  - `entry(x)` — resolved **as of the prompt's `scene`** when there is one (the single ADR-0012 anchor),
    **book-start** when there is not. The common case ("this character as they are here") is the
    zero-argument default.
  - `entry(x, at=some_scene)` — as of an explicit, possibly different, scene (replaces `entry_as_of`;
    also how a picked node is read as-of a specific pick).
  - `original(x)` — the one clearly-named exception for book-start, ignoring all mutations.
  - `effective`'s within-scene `position=` becomes an optional arg on this path, not a lost capability.
- **A picked node carries no as-of state of its own.** It is another way to *name* a node; `entry(pick)`
  resolves it against the same single anchor as any other reference. There is no per-pick as-of.
- **`fields(x)` returns the *full* field roster, advisorily flagged — the template decides what the AI
  sees.** Renamed from `field_catalog`, it lists every field of the type (an entry or an entry_type FQN),
  each descriptor carrying `type`, `options`, `description`, and an **advisory `proposable`** — whether it
  makes sense to ask the AI to compute a value (structurally `false` for computed and reference fields;
  author-overridable, §Deferred). Nothing is hidden and nothing is enforced: the **template designer**
  chooses what to show — `{% for f in fields(x) if f.proposable %}…` is a *choice*, not a gate. This
  retires the hard-coded `is_proposable_field()` pre-filter — its exclusions become descriptor facts a
  template can read and override (`author_vs_runtime_authority`: trust the designer).

### 4. Role: implicit from the base type; explicit only to override

- Each prompt **base type** (ADR-0054 dispositions: `continuation`, `revise`, `general`, `snippet`)
  supplies a **default role envelope**. Un-roled prose lands in that default instead of being discarded —
  `_check_trailing_text`'s silent drop becomes a non-event because loose text always has a home.
- `{% role %}` remains as an **override** for the uncommon multi-turn / mixed-role prompt. The mental
  model shrinks from "wrap everything or lose it" to "reach for `{% role %}` only for more than one
  message."

### 5. Volatility is a provider-neutral ordering; the author's only lever is an advisory hint

The shared layer produces a **volatility-ordered content sequence** (most-stable first). Each provider
adapter (ADR-0058, `profiles/*`) maps it to its own primitive:

| Provider | Mapping |
| --- | --- |
| Anthropic | ≤4 `cache_control` breakpoints at tier boundaries, with ttl |
| OpenAI | no markers — relies on the stable-first ordering staying byte-identical |
| OpenRouter | per-route (explicit markers or automatic) |
| Ollama | collapse to a string |

The **4-breakpoint cap and ttl vocabulary stay inside the Anthropic adapter** and never reach the
language or the shared block model. This is the concrete decoupling: the author says nothing about
caching; the shared layer says only *order by volatility*, which every provider can use or ignore.

**The one author lever — the volatility hint (§2).** The author never touches the *mechanism* (breakpoints,
ttl, block count, ordering). They may pass a two-valued semantic prediction — `use(node, "stable" |
"volatile")` — that biases which of the two existing lore tiers a node starts and stays in. It is an
advisory **prior**, not a static override: the revision diff still governs correctness every turn, so a
`"stable"`-hinted node that changes re-writes that turn (the model never sees stale bytes). This is
therefore *not* the static label Anti-goal #1 forbids — it seeds the dynamic mechanism, it does not
replace it — and it is provider-neutral: each adapter maps `"stable"`/`"volatile"` onto the ordering it
already uses (Anthropic: which tier/block; OpenAI: position in the stable-first prefix; Ollama: ignored).

Consequently: `{% cache_break %}` and `relevant_lore(partition=…)` **retire** (dead on live calls, and a
static author placement cannot beat dynamic per-revision tiering and collides with the 4-cap). The
`{% cache "static" %}` block variant is **declined** — a static stability label is Anti-goal #1.
Author-authored *prose* that should cache already rides the 1-hour system prefix automatically and needs
no tag.

### 6. The preview becomes cache-aware

Because templates no longer emit lore/corpus, the current preview — which renders the flattened template
output — shows an author *none* of the context that will actually be sent (`context-caching.md` §9). The
preview is changed to surface the **send-path blocks**: the selected, dedupped set, tier-tagged
(stable/volatile), as the model will receive it. The author cannot *control* placement but must be able
to *see* it. (This closes the §3d/§9 "preview models no caching" gap for the block *composition*; a
fully cost-accurate cache-aware estimate remains its own tracked item.)

### 7. Naming: the full pass

Surviving helpers, variables, and tags are named in the author's vocabulary. Renames are pre-1.0, hard,
with a body sweep of the built-ins — **no aliases**:

| Now | Becomes | Why |
| --- | --- | --- |
| `novel` | *(removed)* | a bare alias of `project` |
| book-start reader `base(x)` | `original(x)` | "base" is engine jargon; a writer means the entry's *original* definition, read as `original(x)` against `entry(x)` = current |
| `entry_type_label(x)` | `type_name(x)` | the code's compound noun; a writer wants the type's human name |
| `plain_json` / `tojson` | `json(x)` | one filter, insertion-order-preserving, no surprise-escaping; retire both current spellings |
| `scenes_before(scene)` | `story_so_far(scene)` | it returns the summary recap of scenes **`1 → n-1`** (reading order, verified); the name states it |
| `character_thread(scene, ch)` | `character_turns(scene, ch)` | it reconstructs the scene as *alternating turns*, not one "beat" or "thread" |
| `input` | `inputs` | plural reads right — "the inputs, named" (`inputs.character`) |
| `field_catalog(x)` | `fields(x)` | now the **full** field roster (not a proposable-only subset), each field advisorily flagged — Decision §3 |

**Kept — already good domain names:** `scene`, `project`, `selection`, `text_before`, `text_after`,
`date`, `pov`, `is_a`, `use`, `use_lore`, `entry`, `full_outline`, `full_text`, `last_words`,
`{% role %}`, `{% include "x" %}` (the snippet-include tag — the standard Jinja spelling, kept; see §Why).
**Kept but niche:** `plot_context(as_of)` (a derived, spoiler-gated recap — governed by the emit/select
line below).

**Emit vs select — the line that decides which helpers stay emitters.** A helper that emits a *derived,
bounded, per-scene-deterministic* block — `story_so_far`'s summary recap, `plot_context`'s spoiler-gated
recap — **stays an emitter**: it is not lore, it double-counts against nothing, and it is byte-stable for
a given scene so it caches in the system prefix. A helper that would paste a *raw node body* (`full_text`,
a scene body, a lore entry) is the retired pattern (Decision §2, Anti-goals): those are **selected** via
`use(node)` and backend-placed, never emitted.

### 8. The surface is typed for completion (designed-for; UI delivered elsewhere)

Completion is delivered in the editor (a separate workstream), but the language must *guarantee* it is
completable — otherwise the editor has no stable target. This ADR therefore requires:

- **Every variable and helper has a declared return type/shape.** `entry(x)`/`original(x)` return a node
  whose `entry_type` is inferred from the argument; `pov()` returns `lore:character`; `full_outline()`
  returns a known outline-node shape; `use()`/`use_lore()` return nothing. The collapsed, uniform helper
  set (fewer helpers, one field idiom) keeps this table small and stable.
- **Fields resolve through the schema.** A node's `entry_type` → its declared fields; an `entity_ref`
  field → its target `entry_type` (the `picker_config`/`NodePickerConfig` constraint the schema already
  carries, ADR-0023) → chained field completion. Attribute access (`node.field`, Decision §3) is what
  makes this natural — string-keyed metadata never could.
- **Dynamic arguments infer type from declarations.** `entry(input.character)` / `use(pick)` complete
  from the input's declared `kinds`/`entry_types`; literal `entry("honor")` from the node index; an
  untyped `entity_ref` or unconstrained argument **degrades gracefully** to the intrinsics
  (`title`/`body`/`id`/`entry_type`), never a wrong guess.

This extends ADR-0026 ("type-aware helpers") from a single `is_a` predicate to the whole surface as a
completion contract.

### 9. The one rule

> A prompt names *what* context it wants (by walking the graph, the corpus, or a picked list) and *which
> message* it belongs in (usually implicitly). The engine decides *where it caches* and *how each
> provider sees it*. Field access is uniform attribute access as-of the prompt's one scene; caching is a
> provider-neutral volatility ordering the author never touches; and the whole surface is typed so an
> editor can complete it.

## Why / rejected alternatives

- **Revive `{% cache_break %}` as `{% cache "static" %}` blocks (the author places tiers).** Rejected:
  it re-earns the bug ADR-0057 §7 removed — a *static* stability label pushes settling content into a
  churning tier and re-bills its write premium (~5× on Anthropic for a slow turn cadence,
  `context-caching.md` §3c) — and it collides with Anthropic's 4-breakpoint budget. Dynamic per-revision
  tiering is strictly better and is the engine's job.
- **Let the `use(node, …)` volatility hint *override* the revision diff (freeze `"stable"` content).**
  Rejected: that would send the model **stale bytes** when a `"stable"`-hinted entry changes mid-chat —
  the one thing ADR-0057 / `context-caching.md` §4 guarantee against. The hint is a *placement prior*
  only; correctness stays revision-governed (§5). Kept the hint, refused the override — the distinction is
  what makes an author volatility lever safe.
- **Keep inline emission (`relevant_lore()`, `full_text()` pasting text) and just document the cache
  pitfalls.** Rejected: emission double-includes lore (Context §3, verified) and lands corpus in an
  uncached user message. Documentation cannot make an author-emitted user-message block cache; only
  moving selection to the backend-placed path can.
- **Add a `fromjson` filter so authors can parse the picker string themselves.** Rejected: it exposes a
  wire-format accident (JSON-over-string) as language surface and leaves every author writing the same
  parse-then-`entry()` boilerplate. Coercing to `list[EntryRef]` at the bind layer removes the problem
  instead of naming it.
- **Keep `base`/`effective`/`entry`/`entry_as_of` (explicit is safer).** Rejected: four names for two
  ideas is the obscurity complaint itself; the `entry(x, at=…)` + `original(x)` pair covers every case
  with the common one (as-of the scene) as the default, which is what a writer means by "the value."
- **Default `entry(x)` to book-start, require `at=scene` everywhere.** Rejected: it adds ceremony to the
  overwhelmingly common case (a scene-anchored prompt wants current state) — the same verbosity the
  `node.metadata.<field>` gripe is about. The mild implicit dependency on `scene` is acceptable because
  `scene` is the prompt's declared anchor, not a hidden global; and it degrades cleanly to `original`
  when absent.
- **Deliver completion in this ADR.** Rejected as scope: the completion *UI* belongs in the editor
  workstream. This ADR owns only the *guarantee* (§8) that the language is completable, so the editor
  builds against a settled contract rather than a moving one.
- **Rename `{% include %}` → `{% snippet %}` to name the `prompt:snippet` type.** Rejected: its only
  real motivation was a mental-model clash with a helper once tentatively named `include()`; choosing
  `use()` for selection dissolves the clash. What remains is weak self-documentation, bought at the cost
  of a built-in body sweep and departing from the Jinja spelling authors already know. Keep
  `{% include %}`.

## Consequences

- **New:** `use(node)` selection helper feeding the ADR-0057 set, with an optional
  `use(node, "stable"|"volatile")` volatility hint (advisory, revision-bounded); bind-layer coercion of
  `context_pick` inputs to `list[EntryRef]`; `node.<field>` on `ProjectInfo`; `entry(x, at=…)`;
  `fields(x)`'s full roster with an advisory `proposable` flag; a declared type/shape table for every
  variable and helper (§8); base-type default role envelopes; a cache-aware preview of the send-path
  blocks.
- **Removed / retired:** `relevant_lore()`-as-emitter (gate `use_lore()` stays); raw full-body corpus
  emission as text; `{% cache_break %}` and `relevant_lore(partition=…)`; `entry_as_of`, `effective`,
  the field-form `base(entity, field)` (folded into `entry(x, at=…)` + `original(x)`); the hard-coded
  `is_proposable_field()` catalog pre-filter (now an advisory descriptor flag); the silent-discard of
  un-roled text.
- **Renamed (pre-1.0, hard, no alias — §7):** `novel`→removed; `base`→`original`;
  `entry_type_label`→`type_name`; `scenes_before`→`story_so_far`; `character_thread`→`character_turns`;
  `input`→`inputs`; `field_catalog`→`fields`; `plain_json`/`tojson`→`json`. (`{% include %}` stays —
  §Why.)
- **Reused, not rebuilt:** the ADR-0057 selector / dedup / tiering; `_format_lore_block` (ADR-0006); the
  single as-of anchor chain (ADR-0012); the `EntryRef` metadata fallback and collision rule; the
  provider profiles / adapter seam (ADR-0058); the schema `entry_type`-ancestry and `picker_config`
  primitives (ADR-0023/0026).
- **Breaking to the author surface, pre-1.0 (no migration).** Custom prompts using retired names change;
  the built-ins are swept in-tree. The surface is *smaller and uniform* after — which is the point.
- **Unchanged:** the send-path cache assembly and its dynamic tiering (ADR-0057 §7 /
  `context-caching.md` §4); per-entry `context_policy`; the disposition/commit model (ADR-0054);
  scene-authoritative and as-of read semantics (ADR-0055).
- **Enables:** `docs/prompts/` can be rewritten against a language that matches the code, and the editor
  workstream can build completion against the §8 contract.

## Deferred / adjacent (named, not blockers)

- **A fully cost-accurate cache-aware preview.** §6 surfaces the block *composition* and tiers; pricing
  each tier with real read/write multipliers (the `_CACHE_WRITE_MULTIPLIER` 1h under-charge and the
  no-caching estimator, `context-caching.md` §3d) is its own item.
- **The completion service/UI** — the editor workstream; this ADR only guarantees completability (§8).
- **Corpus beyond lore in the tiered path.** `use(scene)` routes corpus through the cached set; any
  remaining author-emitted dynamics that still land in flattened messages (`context-caching.md` §9) are
  swept case-by-case as they surface, not exhaustively here.
- **Retiring `{% cache_break %}` from the preview estimator too.** It stays preview-only until the
  cache-aware preview (§6) replaces the estimate it feeds; removing it is that item's cleanup.
- **An author opt-out for `proposable`.** An author-settable "don't ask the AI to compute this" field
  property (feeding `fields(x)`'s advisory flag) is a field-model addition (ADR-0029 territory), not
  specified here; until it lands, `proposable` derives structurally (computed / reference → `false`).
- **An engine-side thrash detector.** Content that never settles (its revision bumps every turn) costs a
  `1.25×` cache-write with no read benefit — worse than uncached (`context-caching.md` §3c). The
  `"volatile"` hint lets an author avoid that manually; the engine could also *observe* the churn from the
  revision stream and stop paying to cache a perpetually-changing entry. An engine optimisation, not
  author surface — its own item.

## Suggested slicing (indicative, not decided here)

1. **`use(node)` + bind-layer `context_pick` → `list[EntryRef]`** — delivers Journey A/B, the one
   traversal that cannot be done today; retires the emitting `relevant_lore()` in favour of `use_lore()`.
2. **Field model** — `node.<field>` on `ProjectInfo`; `entry(x, at=…)` + `original(x)`; retire
   `entry_as_of`/`effective`/field-form `base`; `field_catalog`→`fields(x)` full roster with advisory
   `proposable`, retiring the `is_proposable_field()` pre-filter. Delivers Journey C.
3. **Roles** — base-type default envelopes; un-roled text gets a home; `{% role %}` demoted to override.
   Delivers Journey D.
4. **Provider-neutral volatility ordering + the `use(node, hint)` lever** — move the 4-cap/ttl vocabulary
   entirely into the Anthropic adapter; retire `{% cache_break %}` / `partition=`; honor the optional
   `use(node, "stable"|"volatile")` hint as a revision-bounded placement prior. Delivers Journey E/F.
5. **Cache-aware preview** — surface the send-path blocks, tier-tagged (§6).
6. **Vocabulary + typing** — the §7 naming pass (`novel` removed; `base`→`original`,
   `entry_type_label`→`type_name`, `scenes_before`→`story_so_far`, `character_thread`→`character_turns`,
   `input`→`inputs`, one `json` filter); publish the declared type/shape table (§8); then rewrite
   `docs/prompts/` against reality.
