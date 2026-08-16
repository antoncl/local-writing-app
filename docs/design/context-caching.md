# Context caching: how it actually works, what it costs, and the lore-placement contract

> **Why this document exists.** The caching design is subtle, spread across the
> template layer, the send path, and the provider adapters, and it is *easy to
> get wrong by reading the wrong layer*. Twice now a change has been made against
> the intuition "the template's `{% cache_break %}` decides what gets cached" —
> which is **false for live calls** (see §2). This document is the single place
> that records how caching truly reaches each provider, what it costs, and the
> rule for where lore is placed. Read it before touching anything that renders
> lore, assembles system blocks, or estimates cost.
>
> Verified against `master@99a0373b`. Line numbers rot; function/symbol names and
> file paths are the durable references.

## 1. The mental model (the intent)

From `docs/prompts/README.md` §Design principles:

- **Don't bomb the context window.** Lore inclusion is retrieval, not "dump
  everything." The reference graph is the index; `relevant_lore(scene)` walks it.
- **Stable prefix, dynamic suffix.** The envelope is ordered so a cache
  breakpoint sits between rarely-changing and per-call-changing material.
  Editing one lore entry doesn't invalidate the prefix above it.
- **Local-first, provider-neutral.** Every provider runs through one envelope.
  Anthropic's explicit prompt caching is exploited where supported and is a
  **no-op** elsewhere; Ollama never caches.

The whole game is that second principle: put the parts that stay identical
turn-to-turn *first*, mark a cache breakpoint, and let the provider serve the
identical prefix from cache instead of re-charging full price for it.

## 2. How caching *actually* reaches the provider (the trap)

There are **two** places that look like they control caching. Only one reaches a
live call.

### 2a. Template-level breaks — preview-only, **dead on live calls**

A template can write `{% cache_break %}` and
`relevant_lore(scene, "implicit", "stable"|"volatile")`. The `{% role %}` /
`{% cache_break %}` extensions (`services/ai/templates.py`) turn those into
`ContentBlock`s carrying `cache_break_after`, and the stable/volatile split is
mediated by an `AISession` baseline (`services/ai/sessions.py`).

**But `build_chat_payload` (`services/ai/preview.py`) flattens every rendered
message's blocks back into one string** — `text = "".join(block.text for block
in msg.blocks)` — and joins all system messages into a single `system_prompt`.
The `cache_break_after` booleans are discarded. So for the **actual** chat /
generate request, template-authored `{% cache_break %}` markers and the
`partition=` argument **do nothing**. They survive only into the **preview token
estimate** (`estimate_preview_tokens_and_cost`), where they group blocks for
display.

Corollary: the canonical "stable above the break, volatile below" pattern in
`docs/prompts/helpers.md` is *aspirational for chat* — it is not what caches a
live conversation today. Treat that pattern as documentation of intent, not of
current behavior, until the machinery is either wired through or retired
(§8).

### 2b. Send-path assembled blocks — the live mechanism

What actually caches a live chat is built **fresh on the send path**, not from
the template. `expand_and_prepare_chat_blocks` (`services/ai/chat.py`) assembles
a list of plain dicts `{text, cache_break_after, ttl}`, ordered stable→volatile:

| Slot | Content | TTL | Source |
| --- | --- | --- | --- |
| 1 | `system_prompt` (the locked, opaque rendered prompt) | `1h` | `system_prompt_cache_blocks` |
| 1b | staged mutation set (ADR-0055 §4), when the chat owns one | `1h` | `_staged_set_block` |
| 2 | detected/journal lore | `5m` | `_format_lore_block` |

Those dicts flow into `ai_providers.chat(..., system_blocks=...)`. **Only blocks
with `cache_break_after=True` get a provider `cache_control` marker**, and `ttl`
is honored only when it is exactly `"5m"` or `"1h"`. The generate (one-shot) path
wraps its system prompt as a single `1h` block the same way.

So the real caching contract for chat is: **a stable 1-hour system prefix, then a
volatile 5-minute lore tail.** That *is* "stable prefix, dynamic suffix" — just
implemented in the send path, not by the template author.

## 3. Per-provider caching and cost

Sources: OpenRouter's prompt-caching guide and the baked-in profile data
(`services/ai/profiles/_baked_in.yaml`, `profiles/*`, `providers.py`).

### 3a. Explicit vs automatic

| Provider | Style | Breakpoints | Notes |
| --- | --- | --- | --- |
| **Anthropic** | explicit | `cache_control:{type:ephemeral, ttl?}` | Always explicit. `_anthropic_system_blocks` emits the markers; `ttl` passed through when `"5m"`/`"1h"`. Max **4** breakpoints (not enforced in code; the send path emits ≤3 by construction). |
| **OpenRouter** | per-route | explicit for anthropic/google/qwen/alibaba routes; auto for openai/deepseek/x-ai/groq/moonshotai; else none | Gets the structured block list; also passes `session_id` for sticky routing so the prefix survives across turns. |
| **OpenAI** | automatic | none | Auto-caches prefixes ≥1024 tokens. `system_blocks` are **collapsed to a string** — breakpoints/TTLs stripped. Placement changes nothing on the wire; only prefix *stability* matters. |
| **Ollama** | none | none | No network cache. Blocks collapsed to a string. |

### 3b. Cost multipliers (what a cache write/read costs vs. a normal input token)

| Provider | Cache **write** | Cache **read** | TTL |
| --- | --- | --- | --- |
| Anthropic | 1.25× (5-min) / **2× (1-hour)** | **0.1×** | 5m default, 1h opt-in |
| OpenAI | 1.25× (newest) / free (earlier) | 0.25–0.5× | ≥30 min |
| Google Gemini | input + a 5-min storage fee | 0.25× | ~3–5 min |
| DeepSeek | 1× | 0.1× | — |
| Grok / Groq / Moonshot / Z.AI | free | 0.25–0.5× | — |

The key fact: **there is essentially no per-time storage fee** (Gemini aside).
You pay the write premium **once, each time the cached content is (re)written**,
then read it back cheaply until the TTL expires. Minimum cacheable prefix is
~1024 tokens (2048 for Haiku 3.5, 4096 for Opus / Gemini Pro).

### 3c. Why the stable/volatile split is worth it (worked example)

Anthropic, a block of "always" world/premise lore reused across a 12-turn
conversation inside an hour:

- **In a 1-hour stable block:** write once (2×), read 11× at 0.1× → `2 + 1.1 =
  3.1×` the base input cost for that content.
- **In a 5-minute volatile block that changes every turn:** re-written every
  turn at 1.25× → `12 × 1.25 = 15×`.

≈ **5× more expensive** to put stable content in a churning tier. The premium
only bites when the content actually *re-writes*; if the volatile block is
byte-identical and the turns are <5 min apart it's a cache read either way. So
the penalty is real specifically for **stable content under a slow turn cadence**
— which is the normal case for a writer who thinks between turns.

### 3d. How the app models cost (and two gaps)

`compute_cost` (`profiles/base.py`) charges, per call:

```
input_tokens        × cost_in
+ cached_input_tokens × cost_in × cache_read_multiplier   # 0.1 Anthropic, 0.5 OpenAI, None→1.0 OpenRouter
+ cache_write_tokens  × cost_in × 1.25                    # flat
+ output_tokens       × cost_out
```

Two known imprecisions (out of scope for the lore fix; tracked separately):

1. **1-hour writes are under-charged.** `_CACHE_WRITE_MULTIPLIER` is a flat
   `1.25` (`base.py`). It's exact for 5-minute writes but Anthropic bills 1-hour
   writes at **2×** — and the send path tags system/staged blocks `1h`. The code
   comment acknowledges this and defers "explicit-TTL refinement."
2. **The preview estimator models no caching at all.**
   `estimate_preview_tokens_and_cost` / `tokens.estimate_input_cost` price every
   input token at the full rate, with no read discount or write premium. The
   preview panel shows the un-cached worst case; only the post-call `compute_cost`
   (from real usage) reflects caching.

## 4. The lore-placement contract (the rule)

This is the durable rule that the fix in §6 implements and that any future
lore-rendering change must uphold.

> **The backend is the single place that selects, deduplicates, *and places*
> lore. A prompt template only *declares* that it uses lore; it never emits the
> lore text itself.**

Concretely, for a lore-enabled chat, on every send:

1. **One deduped set** (ADR-0057 §3): `{ explicit(context_items) ∪ auto(journal)
   ∪ always } − { never, manual_only }`, keyed by id so each node appears once.
2. **Partitioned against the chat's session baseline, then placed once per tier.**
   "Stable" and "volatile" are a **dynamic, per-turn** distinction — *not* a
   static "always vs auto" label. Using each entry's `revision` (content hash)
   versus what this chat last sent (the `AISession` baseline, §6):
   - **Stable → 1-hour block:** entries that were in context last turn **and are
     unchanged** (revision matches the baseline). Sorted by id, so the block is
     byte-identical turn-to-turn and serves as a cache **read** (0.1× on
     Anthropic) — with one caveat: stability keys on an entry's own base
     `revision`, but the rendered bytes are its *effective state as-of the scene*.
     A **cross-node** mutation (a marker added to the anchor scene mid-chat that
     shifts entry E's effective value) shifts E's bytes without bumping E's
     revision, so the stable block re-writes once that turn, then re-settles. That
     is the §6 stable-tier staleness class, not a correctness bug (the model
     always sees current state); a base-state (scene-less brainstorm) chat has no
     such edge and is strictly byte-stable.
   - **Volatile → 5-minute block:** entries that are **new this turn, or whose
     content changed** since last turn.
   - So an `always` entry, the POV character, an explicit pick all **start**
     volatile (new on turn 1) and **migrate to stable** once seen-and-unchanged;
     any of them drops back to volatile the turn its entry is edited. This is the
     "*new or changed since the prior call*" rule the partition machinery exists
     for.
3. **Rendered once, as-of the chat's scene** (`_format_lore_block(..., scene=…)`)
   so field values are resolved consistently — no two copies with divergent
   `effective_state`.
4. **Commit:** this turn's set becomes next turn's baseline.

The template's role shrinks to a **gate declaration**: it calls a gate helper so
the `lore_enabled` flag is captured at the lock render (ADR-0057 §2), but the
call **emits nothing** — the backend does all placement. See §6 for the idiom.

## 5. The bug this replaces

Before the fix, a **roleplay** chat carried its lore *twice*, and neither copy
was well-cached:

- `roleplay.md` renders `{{ relevant_lore(scene) }}` **inside a `{% role "user"
  %}` block**. The frontend flattens that block into the **first user message**,
  which is persisted and **re-sent verbatim every turn**. On Anthropic the cache
  breakpoints sit on the system blocks, *before* the messages, so this lore is
  **re-processed at full input price every turn** — the worst tier.
- Then the send path adds the **5-minute journal block** (§2b) from the running
  conversation. Any entry that is both in the scene-summary render *and*
  re-mentioned later appears **twice** to the model — and with **divergent
  state**, because the locked copy resolves `effective_state` at the scene while
  the journal block renders base state.

`revise-entry.md` (brainstorm) was *not* broken the same way: its `always` lore
renders into the **system** prompt (the 1-hour stable prefix), which is the right
tier, and `always` entries are never auto-matched into the journal, so there is
no double. The fix unifies both prompts onto the §4 contract, which leaves
brainstorm's tiering essentially where it already was and moves roleplay's lore
from the uncached user message into the correctly-tiered system blocks.

## 6. The fix (what changes)

- **Templates stop emitting lore.** `roleplay.md` and `revise-entry.md` keep a
  gate-only call (so `lore_enabled` is still captured at the lock render) but no
  longer paste lore text into the prompt. Idiom: **a small, clearly-named gate
  helper** (e.g. `use_lore()`) is preferred over the obscure `{% set _ =
  relevant_lore() %}` side-effect trick or a silently-empty `{{ relevant_lore()
  }}`; the name documents intent ("this prompt uses lore; the app injects it").
- **The send path starts using the session baseline that already exists but is
  dead on this path** (§2a). In `expand_and_prepare_chat_blocks`:
  1. `default_registry.get_or_create(<chat key>)` — an in-memory `AISession` per
     chat. **No persisted state, no `ChatSession` field, no migration.**
  2. Compute the one deduped set (reusing `_always_included_lore_ids`, the
     journal, `context_items`, the `never` / `manual_only` exclusion — one
     selector, not a second matcher).
  3. Partition it against the baseline (`session.is_stable(id, revision)`):
     unchanged → a **1-hour** stable lore block (added beside the system prefix);
     new-or-changed → the **5-minute** volatile block. Render both through
     `_format_lore_block` as-of the chat's scene.
  4. `session.commit()` — this turn's set becomes next turn's baseline.
- **Cold start:** a fresh backend process has an empty baseline, so a chat's first
  turn after a restart is all-volatile and re-settles on the next turn. Acceptable
  — the provider cache is gone on restart anyway, so a lost baseline is *consistent*
  with it; the cost is one extra write cycle, not correctness or real money.
- **Breakpoint budget.** Blocks are now `system(1h)` + `staged(1h)?` +
  `stable_lore(1h)` + `volatile_lore(5m)` — at most **4**, which is exactly
  Anthropic's breakpoint limit. The stable lore is a *separate* block, not
  appended to the locked system prompt, so a settling entry never invalidates the
  system prompt's own cache. The budget is not enforced in code; a future 5th
  block would need a guard.
- **Result:** each entry appears once, in the tier its freshness earns, at the
  right state; the double-inclusion is gone; a character named early stops being
  re-billed every turn once it settles into the cached stable tier.

## 7. Correction to ADR-0057 §5

ADR-0057 §5 says the one dedupped result is "placed once, in the **volatile**
tier." That is **wrong against the cost model** (§3c): it pushes stable content
into the 5-minute tier and re-bills its write premium whenever the tier changes.
The corrected rule is **"placed once *per stability tier*"** (§4), where the tier
is decided **per turn by each entry's revision** — unchanged-since-last-turn → a
1-hour stable block, new-or-changed → a 5-minute volatile block — via the session
baseline, **not** a static policy label. Still one selector and one dedupped set
with each node appearing once; only the placement is tiered by freshness.
ADR-0057's *core* (one gated selector, dedup by id, no reconciled second channel)
is unchanged and correct; only §5's single-tier placement is superseded here.

## 8. Anti-goals (do not)

- **Do not** collapse lore into a single volatile block "because the ADR said
  so" — §7.
- **Do not** split stable/volatile by a *static* label (`always` vs `auto`, or
  "explicit picks are stable"). The split is **dynamic** — unchanged-since-last-
  turn vs new-or-changed — via the revision baseline (§4). A static split
  re-writes the growing set every turn and never lets an entry settle.
- **Do not** emit lore text from a template — the backend places it (§4).
- **Do not** run a second lore matcher on the send path — feed the one selector
  (ADR-0057 §1).
- **Do not** reorder a stable block's contents between turns — sort by id, keep
  it byte-identical, or the cache read is lost (§1).
- **Do not** add persisted baseline state — the in-memory session is deliberate;
  a cold start costs one re-settle turn, nothing more (§6).
- **Do not** assume a template's `{% cache_break %}` affects a live call — it
  doesn't (§2a).
- **Do not** trust the preview cost panel as a cache-aware number — it isn't
  (§3d).

## 9. Known adjacent issues (tracked separately, not in the lore fix)

- Cost model under-charges 1-hour cache writes (`_CACHE_WRITE_MULTIPLIER`, §3d).
- The preview estimator models no caching (§3d).
- The template-level `{% cache_break %}` / `relevant_lore(partition=…)` markers
  are dead for live calls (§2a). The fix (§6) uses the session-baseline *logic*
  server-side, not the template markers, so those markers stay preview-only — a
  candidate to retire from `docs/prompts/helpers.md` guidance so authors aren't
  misled. Its own cleanup.
- Other template content that lands in flattened user messages (`scenes_before`,
  scene dynamics) is uncached the same way roleplay's lore was — a broader
  instance of the same class, beyond lore.
- **Per-chat sessions are never evicted.** The send path does
  `default_registry.get_or_create("chatlore:<chat_id>")` and never `drop`s it, so
  a long-lived backend accumulates one small `AISession` (two `{id: revision}`
  dicts) per chat ever sent to. Bounded per process for a single-user local app
  and cleared on restart; add a `drop` on chat delete if it ever matters. Matches
  the pre-existing render-session pattern (`sessions.py`: "No expiry yet").
- **As-of-scene resolution now builds the mutations index per send** for a
  scene-anchored chat (`build_mutations_index`, once per send, threaded into both
  partition calls). This is new recurring cost that scales with manuscript size —
  the price of resolving lore as-of the scene at send time rather than only at
  the lock render. Mitigation if it gets slow: memoize/persist the index (the
  index code already flags this).
- **Preview consequence:** because the templates no longer emit lore, the preview
  panel for a roleplay/brainstorm prompt shows **no** lore text — the writer
  can't see which lore will be sent from the preview. The lore is real (placed at
  send); only the preview is now lore-free. A cache-aware preview (see the
  estimator gap above) could surface the send-path blocks instead.

## References

- ADR-0057 — the one gated lore selector (`docs/design/adr/0057-…md`); §5
  superseded by §7 here.
- ADR-0055 — as-of-scene reads + the staged-set 1h block.
- ADR-0006 — `_format_lore_block`, the resolver chokepoint.
- `docs/prompts/README.md` — the "stable prefix, dynamic suffix" principle.
- `docs/prompts/helpers.md` — `relevant_lore` / partition reference (note §2a:
  the partition pattern is preview-only for chat today).
- OpenRouter prompt-caching guide — per-provider write/read multipliers, TTLs.
