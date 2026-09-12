# ADR-0086: The inferred lore selection fits a per-turn token budget; declared intent is never dropped, and the send reports what it left out

- Status: **Proposed** — 2026-09-12 (authored by Claude, for Anton's direction call). A cold-implementer simulation was run against the first draft; its findings are folded in below.
- **Issue:** #1876 (bound the implicit lore selection per turn — the failure #1874 caught only at commit).
- **Relates to:** ADR-0057 (a conversation selects its lore once behind one gate), ADR-0060 (the two volatility tiers), ADR-0075 (implicit context detection, the journal), ADR-0067 Amendment 2 (the commit turn carries only the chat's own picks), ADR-0076 (the Context door; the per-turn meta line), ADR-0084 (the plan flows up to the preview).

> **Verified against `0da1447f` (2026-09-12).** Citations name the symbol first; the line is a convenience and is what rots.

## Problem

A chat turn's lore selection has no size. `_implicit_lore_ids` (`backend/app/services/ai/lore_selection.py:118`) unions the scene's structural refs, every `always`-policy entry, every journal entry the session has ever detected, and a structural one-hop from all of those; nothing between that union and the wire trims, counts, or orders it. ADR-0057 says so on purpose: a set "keyed by id so a node reached by several routes at once appears once … that is the only dedup this design contains" (`0057:69-72`). ADR-0075 names the single bound that exists — "depth strictly 1, to bound the fan-out" (`0075:54-56`) — and makes the journal "append-only (monotonic: once an entity enters scope it stays for the session)" (`0075:198-203`). So a conversation's lore only ever grows, and one hop from a growing set grows faster.

The measured case (#1874, the "Sable Venn" commit). A project with 61 lore entries and **no** `always`, `manual_only` or `never` policy at all. A four-turn create brainstorm whose journal held 40 entries: 2 from the author's own messages, 7 from the rendered prompt, **31 from depth-1 expansion**. Rendered, the lore block was 157k characters, about 36k tokens, in front of a 3.5k-token transcript. On the commit turn the model answered the system prompt against the lore and never read the draft it was asked to transcribe; with the lore block removed and nothing else changed it transcribed the draft verbatim. ADR-0067 Amendment 2 fixed the commit turn by sending only the chat's explicit picks there. Every ordinary turn of that chat still carries the same block, and the same degradation happens on any brainstorm turn on a cheap model — silently, as a worse answer, because a prose reply has no diff to fail against.

Three more facts shape the fix:

- The app knows a model's window (`ModelDescriptor.context_window`, `backend/app/services/ai/profiles/base.py:126`) and never compares anything to it; the only consumer is a tie-break in capability-tier auto-rank (`base.py:575-590`). But the window is not the constraint that bit: the failing call was ~41k tokens on a model with a far larger window. The constraint is attention, not capacity.
- Every provider profile counts tokens with the same estimator, `default_token_count` (`profiles/base.py:270`; cl100k via tiktoken, else characters/4). There is no per-provider tokenizer to thread anywhere. The preview counts its blocks through `count_tokens` (`backend/app/services/ai/tokens.py:23`) via `_count` (`backend/app/services/ai/preview.py:966`), per tier, and the Context door shows "n entries · x tok" per tier (`frontend/src/components/editor/body/chat/ContextDoor.svelte:121`). Nothing counts per entry.
- The chat's estimate is a **turn-0 preview**. The meta line's `~Xk tok` comes from `api.aiPreview` with the prompt, subject, inputs and assistant (`frontend/src/components/editor/body/ChatBodyView.svelte:959`); `AIPreviewRequest` carries no chat id, journal or messages (`backend/app/models/ai.py:248`), and `_preview_lore_tiers` builds an empty-composer journal (`preview.py:697-733`, whose docstring says the chat's accrued journal is not mirrored). So the estimate cannot know what turn 4's send will select; only the send knows. Any design that promises "the door shows what the send will send" for a mid-session turn is unbuildable on today's preview.

## Intent

**Bound what the app infers; never bound what the author declared; report what was left out on the turn that left it out.** The selection stays one gate, one dedup, two tiers. It gains one thing: the inferred part fits a budget, in a stated order, and each send says what it dropped.

## Anti-goals (what this must not do)

- **Not per-entry truncation, not summarisation.** An entry is sent whole or not at all. A trimmed entry is a lie the model can't detect; a summarised one is a second rendering to maintain.
- **Not a change to `context_policy` semantics.** `always` stays a wholesale union (ADR-0057 anti-goal, `0057:86-89`); `manual_only` and `never` keep their meanings. The budget never overrides a policy — it operates only on entries no policy or pick placed.
- **Not a change to the journal or to detection.** ADR-0075's journal keeps recording every detection, append-only, with its `added_at_turn` as today (a re-mention does not refresh it — the journal has no last-seen, and adding one is not this decision). The budget shapes the *send*, never the record of what was noticed.
- **Not a change to tiering, placement, or wire order.** The kept set is tiered exactly as today (ADR-0060 §5) and emitted in the id-sorted order `_tier_lore_ids` relies on for byte-identical stable blocks (`lore_selection.py:186-187`). The fit order (§1) is for the fit only; it never reaches the wire.
- **Not applied to the commit turn.** ADR-0067 Amendment 2's read-only turn sends only the chat's picks (`lore_mode="used"`); there is nothing inferred to budget.
- **Not a model-window guard.** Overflowing `context_window` is a different failure (a provider error, not a quiet degradation) and is left to a later decision; the number here is not derived from the window (see Alternatives).
- **Not a new prompt-vocabulary knob and not a per-request override.** No `use_lore(budget=…)`, no field on `AIChatRequest`; the budget is a property of the assistant, resolved the one way `max_tokens` already is.
- **Not a chat-aware preview.** Making the turn-0 estimate read the chat's journal so the meta line could warn *before* a mid-session send is a real want and a separate change to ADR-0076's door; this ADR reports on the send instead (§5) and leaves that follow-up named, not sketched.
- **Not a resolution of ADR-0075's structural-hop tension.** ADR-0075 says structural expansion is "a separate, opt-in mechanism" (`0075:63-66`) while `_implicit_lore_ids` runs it on every implicit selection (`lore_selection.py:154-161`). This ADR fits that hop last so the budget drops it first, and names the tension; it does not settle it.

## Decision

### 1 — Two sets: declared and inferred

Every id the selector produces is **declared** — the author put it there — or **inferred** — the app followed something to it. (The words are chosen against the codebase: `mode="explicit"` already means scene refs ∪ `use()` picks *without* `always` (`lore_selection.py:54`), and "rank"/"tier" already mean capability ranking and volatility tiers.)

| declared (never dropped) | inferred (budgeted, in fit order) |
|---|---|
| the chat's `use()` picks (`ChatSession.used_node_ids`) | journal entries with source `user_message` |
| the scene's structural refs (`_collect_lore_refs_from_metadata` on the scene) | journal entries with source `rendered_prompt` |
| every `always`-policy entry (`_always_included_lore_ids`) | journal entries with source `scene_prose` |
| | journal entries with source `depth1_expansion` |
| | the structural one-hop (`_implicit_lore_ids:154-161`), source `structural_hop` |

**Precedence:** an id reachable both ways is declared. The inferred list is built *minus* the declared set. (This case is real: detection excludes only `used_node_ids` and context-item picks from the journal, `backend/app/services/ai/chat.py:166-169`, so a scene-ref'd or `always` entry that is also mentioned is journaled.) The `never` chokepoint applies once, to both sets, where it applies today (`lore_selection.py:87-89`). Structural-hop children of an inferred seed are candidates in their own right, fitted last; a seed's fate does not decide its children's.

**Fit order** within the inferred set is the distance from the author's own words: what the author typed this session, then what the author's prompt named, then what the anchored scene's prose names, then what the app found one hop from those, then what the app followed through graph edges. Within one source, the entry journaled latest first (`added_at_turn` descending — the turn it was *first* noticed; the journal records no re-mentions), then by id. Structural-hop ids carry no turn and order by id. The key is `(source, -added_at_turn, id)`: total, deterministic, no title involved.

The journal-less selector branch (`journal is None`, `lore_selection.py:129-138, 164-165`) has no production caller in implicit mode — the send and the preview both pass a journal — and is untouched except that its scene-prose scan and textual hop take the `scene_prose` and `depth1_expansion` sources, so tests that exercise it see the same order.

Context-item lore picks (`ChatSession.context_items`) are excluded from detection today (`chat.py:166-169`) and are not unioned by the selector; the frontend sends none. They are outside this decision.

### 2 — One budget, on the assistant, measured with the one estimator

A new assistant field, **`ai_lore_budget_tokens`**, type `number`, no schema default, defined beside `ai_max_tokens` in the assistant schema (`backend/app/services/project/default_schema.py:1233`; field list `:412-426`). It is resolved exactly as `max_tokens` is — in `resolve_call_params` (`backend/app/services/ai/call_resolver.py:164-167`), through the same assistant the request names, including the same fallbacks — into `ResolvedCall.lore_budget_tokens`, with a resolver constant **`DEFAULT_LORE_BUDGET_TOKENS = 16_000`** for a blank, missing, non-numeric or negative value. `0` is a legal value and means "no inferred lore" (only declared entries are sent) — the author who wants exactly their picks and policies gets that by writing zero. There is no "unbounded" sentinel; a large number is the way to say it. The field's description text states the default, so the author reads the number where they change it.

The budget bounds the **inferred set only**. It is measured as the sum of each inferred entry's rendered XML counted by `default_token_count` — the estimator every profile already uses — so no provider, model or settings need reach the selector. **The budget's per-entry sum is the authoritative figure**; the door's per-tier totals count the wrapped `<lore>` block and may differ from it by the wrapper and separators (a few percent). The two are labelled differently and are not expected to be equal.

The assistant is the right home because the assistant is where the model is chosen, and the tolerable lore load is a property of the model: a cheap model gets a smaller budget, set once, on the thing that names the model. Sixteen thousand is a starting point, not a derivation: roughly four to five times the transcript that lost in #1874 and under half the block that beat it; it keeps a mid-sized world in play on a capable model and is easy to lower for a small one.

### 3 — The fit: whole entries, first-fit in fit order

Walk the inferred set in fit order; keep an entry if its rendered size fits in what remains of the budget (`≤`); otherwise leave it out and continue. An entry is whole or absent. An oversized entry does not block the smaller ones ordered below it — the report (§5) lists it with its size, so first-fit's one surprise (a lower-ordered entry in, a higher-ordered one out) is legible.

The declared set is not walked and not counted. Declared plus up to a budget's worth of inferred is what a turn sends; a declared set of 30k and a budget of 16k is legal and sends up to 46k. When the declared set alone exceeds the budget, the fit still runs on the inferred set unchanged; the report says so (§5), because the control that could shrink the declared set — `always` policies, picks — is the author's, not the budget's.

### 4 — Where it runs: after selection, before tiering, in send and preview alike

A new `_select_lore(project, scene, journal, used_ids) -> LoreSelection` in `lore_selection.py` returns the two sets with each inferred id's source and turn; `_relevant_lore_ids(mode="implicit")` becomes a wrapper returning the sorted union, so its callers (`chat.py:255`, `preview.py:731`) keep their `list[str]` shape and the `never` rule is applied once, in the struct builder.

A new pure module, `backend/app/services/ai/lore_budget.py`: `fit_lore_budget(selection, rendered: dict[id, xml], budget_tokens) -> LoreFit` — kept ids (sorted by id, for the wire), the left-out list (id, title, source, tokens), and the sums it measured. No project access; tested as a function.

`_lore_cache_blocks` (`chat.py:211`) today does ids → tier → format per tier. It becomes: `_select_lore` → render every candidate once (`_render_lore_entries`, `backend/app/services/ai/lore_block.py:42`, already per-entry `(id, xml)` pairs) → `fit_lore_budget` → `_tier_lore_ids` on the kept ids → wrap each tier from the pairs already rendered. The budget reaches it as one keyword on `expand_and_prepare_chat_blocks` (`lore_budget_tokens: int`), supplied by the two callers that hold `ResolvedCall` (`run_chat_turn`, `chat.py:415`; the stream route, `backend/app/routers/ai.py:536`); the commit turn passes nothing and is unaffected (`lore_mode="used"` never reaches `_lore_cache_blocks`). `PreparedChatTurn` carries the `LoreFit`.

The preview applies the same fit to what it knows — its turn-0 selection — so the estimate is bounded by the same rule: the router resolves the budget once (it already resolves the assistant for `estimate_preview_tokens_and_cost`, `routers/ai.py:337`; no assistant → the default) and hands `lore_budget_tokens` into `build_preview`, where `_preview_lore_tiers` (`preview.py:684`) runs render → fit → tier on its pairs. The same rule at two times is not two truths; the send's report (§5) is the one that describes the turn that was actually sent.

The fit renders every candidate to decide — for a 60-entry world that is the whole block, each turn. The rendering already happens today for the kept set; the new cost is counting. Whether that needs memoising is measured in S1, not decided here (a rendered entry depends on the scene, cursor position and mutation overlay, `lore_block.py:80-86`, so any key is wider than `(id, revision)`).

A kept set that changes between turns (an entry drops because a newer one outranked it) changes the stable block that turn and costs one cache write, as any membership change does today. No hysteresis: the fit order is the rule, and a rule the author can predict beats a cheaper one they can't.

### 5 — The send reports; the transcript and the door show it

The turn that dropped something is the one that knows. So the report rides the send, the way `journal_added` already does (`AIChatResponse.journal_added`, `models/ai.py:470`; the stream's `done` line, `backend/app/services/ai/streaming.py`):

- **`AIChatResponse.lore_fit`** and **`done.lore_fit`**: `{budget_tokens, used_tokens, declared_tokens, kept: int, left_out: [{id, title, source, tokens}]}`. Absent on a chat-less call.
- **Persisted on the assistant message** as an additive optional field (`ChatSessionMessage.lore_fit`), the ADR-0076 decision 3 shape: it survives reload beside the usage and provenance it renders with; older messages simply lack it.
- **The per-turn meta line** (ADR-0076 decision 3) gains one quiet segment when anything was left out — *lore 15.8k/16k · 19 left out* — in the line's ordinary register. An over-budget world is a routine fact about the send, not a broken pick; it does **not** ride `ChatEstimate.warnings`, whose danger register (`ChatMetaLine.svelte:70-79`) is for a pick that failed (#1544). The one case that is a warning — the declared set alone larger than the budget — renders as *declared lore 30.2k, over the 16k budget* in the same segment, and is a warning only in wording.
- **The Context door** gains a **Left out** section for the *last sent turn*, read from that message's `lore_fit`: each entry with its source and size, drillable to its XML the way a tier's entry is (the door already fetches per-entry XML for the tiers, `preview.py:684-744`; the left-out ids are rendered the same way on request). From there the author's two moves are the two controls that exist: pick the entry (the prompt's Lore input, or `context_policy: always` on the entry) or raise the budget on the assistant.

The turn-0 preview's own fit (§4) surfaces the same way as its tiers do today — its left-out list is a sibling of `PreviewCacheBlock` (`models/ai.py:292`) on the preview response, `entry_ids`/`entry_xml`/per-entry `tokens` and `source` — so a fresh chat's door is honest before the first send too. Sources are the fit's own closed set: the journal's `JournalSource` values plus `structural_hop`; the journal's own type is not widened.

### 6 — No migration is owed

Two additive optional fields with defaults: `ai_lore_budget_tokens` on the assistant schema (the `ai_max_tokens` shape) and `lore_fit` on `ChatSessionMessage` (the ADR-0076 decision 3 shape). Nothing changes in a chat's identity, the journal, the ledger, or any file an older reader would reject.

## User journey (the definition of done)

The author opens the Sanne chat on a DeepSeek Flash assistant and sends the second message. The reply answers the whore-informant premise, not the world. Under it, the meta line reads *deepseek-v4-flash · 21.4k tok · €0.004 · lore 15.8k/16k · 19 left out*. They open Context: the stable and volatile tiers list Erik, Aetheria, Hespera, the Lampwoman and the rest the author's messages and the prompt named; **Left out** lists nineteen entries the app had followed one hop into — Keros's tolls, the Thief's Techne, the Honey Jar — each with its source and size. They leave it. Later they commit; the proposal is Sanne Vos. They open the assistant, see *Lore budget (tokens): 16000*, and leave that too.

## Alternatives considered

- **A count cap** ("at most 20 entries"). Rejected: entries vary from a paragraph to a chapter; a count bounds nothing that matters.
- **Derive the budget from `context_window`** (a fraction). Rejected: the failing call was ~41k on a 128k+ window; the constraint was attention, not capacity. A fraction would have permitted the block that broke. A plain number the author owns is the hammer.
- **A budget on the prompt (`use_lore(budget=…)`).** Rejected: a prompt is model-agnostic; the tolerable load is not. It would also add prompt vocabulary and a slot on `RenderedTemplate`/`ChatSession` for a value that varies by assistant, not by prompt.
- **A total budget that the declared set fills first.** Rejected: it makes `always` and picks compete with each other for room, and a large declared set would silence every inferred entry with no way to say so but a warning. The budget bounds only what the app infers; the author's declarations are reported, never rationed.
- **Let the budget drop `always` entries last.** Rejected: `always` is a declaration ADR-0057 guarantees; a budget that can override it makes the policy advisory.
- **Cut at first overflow** instead of first-fit. Rejected: one large entry would block every smaller one below it. First-fit's one surprise is made legible by the Left-out list.
- **Make the preview chat-aware** so the meta line warns before a mid-session send. Deferred, not rejected: it is a change to the door's contract (ADR-0076) and to what the estimate request carries; the send-side report gives the author the same information one turn later, and the turn-0 preview keeps its own fit. Named as a follow-up; its shape is deliberately not sketched here.
- **Hysteresis** (keep last turn's kept set unless forced). Rejected: cheaper cache behaviour, unpredictable membership.
- **Truncate or summarise entries to fit.** Rejected: see anti-goals.
- **Refresh `added_at_turn` on re-mention** so "latest first" means last mentioned. Not taken here: it changes the journal's semantics (ADR-0075) for a tie-break; the order is stated honestly as first-noticed and can be revisited with evidence.

## Consequences

- An ordinary turn's inferred lore is bounded by a number the author owns; the declared set is not, and the author is told when it alone is larger than the budget.
- The selector's implicit union gains provenance behind an unchanged `list[str]` face; the tiering, the wire order, and the `never` chokepoint are untouched.
- Counting enters the send path: one `default_token_count` per inferred candidate per turn, on already-rendered XML. Measured in S1.
- The send response and the persisted message grow one optional object; the preview response grows one sibling block. The door reads both the way it reads a tier.
- ADR-0057's "only dedup" sentence gains a sibling: the inferred set is also *bounded*. ADR-0057 and ADR-0075 are amended by reference, not rewritten.
- The preview's estimate for a chat whose inferred set the send would trim is a turn-0 approximation, as it already was for the journal; the send's report is the truth for that turn.

## Rollout (slices)

- **S1 — the budget and the report.** `_select_lore` with provenance; `lore_budget.py`; `ai_lore_budget_tokens` on the assistant and in `resolve_call_params` (default 16 000); the fit in `_lore_cache_blocks` and in `_preview_lore_tiers`; `lore_fit` on `AIChatResponse`, the stream `done` line, and `ChatSessionMessage`; the meta-line segment. Tests: fit order; declared never dropped; declared-over-budget leaves the inferred fit unchanged and is reported; first-fit skips an oversized entry and keeps a smaller lower-ordered one; the wire order stays id-sorted and a settled stable block is unchanged when the kept set is unchanged; the send's `lore_fit` matches what the wire carried; the preview applies the same fit to its turn-0 selection; `0` sends only declared entries; blank/invalid resolve to the default. *Not:* no door work; no change to detection or the journal; no truncation; no `warnings` entry.
- **S2 — the Left-out section.** The door reads the last sent turn's `lore_fit` (and the preview's left-out block for a fresh chat), lists each entry with source and size, drills to XML. *Not:* no new picker; no "add to context" action beyond the two controls that exist; no chat-aware preview.

## Acceptance

- A chat whose inferred selection exceeds the budget sends at most the budget's worth of inferred lore, in fit order, whole entries only; its declared set is sent in full regardless.
- Every send that left something out says so on that turn's meta line; the door lists what, with source and size.
- The commit turn is unchanged. The journal is unchanged. A chat whose inferred selection fits sends exactly what it sends today, byte for byte, in the same order.

## To verify / build at implementation

- The cost of counting every inferred candidate on the send path for a 60-entry project; decide memoisation from the measurement, with the full render key in mind.
- Whether `scene_prose` should outrank `rendered_prompt` for a scene-anchored chat (the scene is the subject); the order above follows ADR-0075's journal precedence and can be revisited with evidence.
- The exact meta-line wording and its placement among the existing segments, against the ADR-0076 mockup.
