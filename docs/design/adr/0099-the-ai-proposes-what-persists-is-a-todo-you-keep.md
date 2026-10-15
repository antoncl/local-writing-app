# ADR-0099: The AI proposes; what persists is a TODO you keep

**Status:** Living draft (2026-10-15) — #2502
**Context verified against `4da34dea` (2026-10-15), the code before the feature.** Slices built: #2504 (S3: follow-ups), #2506 (S2: `todos(x)`), #2508 (S1: Keep).

### How this ADR is kept

As ADR-0098: a living draft while the feature is built, approved once it settles. Each slice's PR rewrites the decisions it changes in place and adds itself to the slice list above; the Context stays pinned to the commit the design started from.

**Settled:** the rule (decision 1); flags are never persisted on their own; follow-ups never edit another entry; TODOs are the only persistence, in the stores that exist.

**Open:** the card's key for Keep as TODO; the exact Revise entry wording that reads TODOs.

## Context

Two kinds of AI output in this app are transient by design:

- **Flags.** Line edits (#2460) and lore-check notes (ADR-0098) are placed on the prose for the writer to decide on, and are gone when the document closes. ADR-0098 left the rest open: "Keeping notes (as TODOs, or anywhere) would be a later decision with its own ADR." A flag the writer agrees with but can't settle now is lost.
- **Conclusions about other entries.** A *Revise entry* conversation commits a patch to ONE entry (ADR-0046 §5: "The target is always the **entry**"), reading only the fields the prompt registered. When the conversation reasonably concludes that *another* entry should change — Kaela's entry now places the docks on the outer rim, so Meridian Station's should say so — that conclusion stays a sentence in the transcript. ADR-0046 lists cross-entry editing among its non-goals, as later work; this ADR answers the part of it that is "remember to change that entry", with a TODO rather than a second patch.

And nothing in the prompt vocabulary reads TODOs, so a kept intention can't be brought back to a prompt.

### What this builds on

- **File TODOs on any node.** `TodoItem` has `scope: "project" | "scene" | "node"` and a `node_id` (`backend/app/models/annotations.py:36-46`); a `node`-scoped item sits on any node, lore entries included (ADR-0090 §3). Its optional `source: TodoSource` (`:24`) records where an app-written item came from, with a `reason` typed as `ChangeCandidateRoute` (`:15-21`) — the same alias `ChangeCandidateReason.route` uses. The single create route is `POST /api/todos` (`backend/app/routers/entries.py:278`); the batch writer `_create_todo_items` (`backend/app/services/project/todos.py:31`) is reachable only from Python. The frontend `createTodo(text, sceneId?, anchorId?)` (`frontend/src/lib/api/todos.ts:8`) only sends `project` or `scene` scope.
- **TODOs with a home and a source are ADR-0090 review items.** The entry's rail lists every open `node`-scoped TODO (`frontend/src/components/editor/ReviewItemsPanel.svelte:58-60`), whose Propose defaults to *Follow a change*, and adopting a patch from that Propose marks the item done (`frontend/src/lib/stores/entryProposal.svelte.ts:569-575`; ADR-0090 §4).
- **TODOs on entries that aren't open.** Change propagation writes node-scoped TODOs without touching the dependent files (`propagate_change`, `backend/app/services/project/change_propagation.py:40`).
- **Embedded TODOs, indexed for scenes only.** A marker pair around the words, `<!-- embedded-todo:id=…;status=…;note=… -->…<!-- /embedded-todo -->` (`backend/app/services/project/embedded_todos.py:36`), indexed by scanning `scenes/` (`:42`). In the editor it is the `todoAnchor` mark (`frontend/src/lib/editor-core/proseMarks.ts:295`, no `excludes`, so a second anchor over the same text replaces the first). `TodoAnchors.markSelection()` (`frontend/src/lib/editor-core/todoAnchors.ts:31`) marks the current selection; `enforceUnique()` (`:48`) keeps an anchor id on the first text node it meets and strips it from the rest, so a hand-marked TODO across formatting or two paragraphs already breaks today.
- **The flag cards and their resolution.** `buildLineEditCard` (Accept / Reject / ‹ ›) and `buildLineNoteCard` (Open entry / Dismiss / ‹ ›) (`frontend/src/lib/editor-core/lineEditCard.ts`, `lineNoteCard.ts`). `EDITS` is a constant kind; `notesKind(links)` is a factory taking the run's callbacks (`frontend/src/lib/editor-core/reviewKinds/`). A flag resolves with `{type: "resolve", ids, accepted: boolean}` (`reviewKinds/core.ts:48-52`). A line-edit run records its cost only when at least one edit was accepted (`frontend/src/lib/editor-core/aiSuggestion.svelte.ts:801-805`); a notes run records it when the notes arrive.
- **The commit extraction.** `run_entry_patch_extraction` (`backend/app/services/ai/extraction.py:458`) continues the chat with a "commit now" turn (`render_extraction_envelope`, `:108`) under `lore_mode="used"` — only the conversation's explicit picks carry `id=` in that turn — and a response schema (`patch_response_schema`, `backend/app/services/ai/patch_schema.py:72`: `fields` only, `additionalProperties: False`, keys in declared order on Ollama). The parser accepts only an object with `body` or `fields` (`backend/app/services/ai/entry_patch.py:143, 219-226`). The result is an `AIEntryPatch` (`backend/app/models/ai.py:1077`). The frontend publishes it to one of three destinations (`frontend/src/lib/stores/chatCommit.svelte.ts`): **revise** into the entry's review (`:337-348`, `EntryProposalController`, whose `commit()` at `entryProposal.svelte.ts:510` is the one "Done" write, a no-op when nothing is adopted), **stage** a mutation set (`:395-407`), or **create** a draft card (`:486-531`).
- **Prompt helpers** live in `backend/app/services/ai/helpers.py`, at 1480 of its 1500-line cap; larger ones keep their logic in their own module and register in a few lines (`_register_scene_mutations`, `:669`).

## Decision

1. **The rule: the AI proposes; what persists is a TODO the writer keeps.** No AI output is saved on its own. Anything that outlives the moment does so as a TODO the writer explicitly chose, in the TODO stores that exist. The AI never marks a TODO done; a TODO is done when the writer ticks it or adopts a patch that answers it (ADR-0090 §4).

2. **Vocabulary: a *flag*** is an item the AI places on the prose for the writer to decide on — a line edit or a note. The code keeps calling them review items on the review surface; *flag* is the word the writer sees and the docs use (AGENTS.md). Not to be confused with ADR-0090's review items, which are TODOs.

3. **Keep as TODO, on every flag card.** A new action, **Keep**, on both cards. It turns the current flag into a TODO and resolves the flag as **kept** — a third outcome beside accepted and rejected (`resolve` carries `outcome: "accepted" | "rejected" | "kept"`). The flag's words are never changed.
   - **What the TODO says.** The existing format for a TODO quoting words, `note — “quote”` (as `finalize_keep.py:40-42` writes it). The note is a line edit's `reason — proposed: “replace”` (`proposed: cut` when `replace` is empty), or a lore-check note's `problem (Entry name)`.
   - **Where it lives:**
     - In a **scene** (a body the embedded-TODO index scans), when the flag lies in **one paragraph** and **no existing TODO** touches its range: an **embedded TODO** over the flagged words — a new `markRange(from, to, note)` on `TodoAnchors` that marks the plugin's mapped range without moving the selection. `enforceUnique` learns that adjacent text nodes in one paragraph carrying the same anchor id are one TODO (fixing hand-marked TODOs across formatting too).
     - In a scene, when the flag spans paragraphs or overlaps an existing TODO: a **`scene`-scoped file TODO** quoting the words. No embedded TODO is created and none is replaced.
     - In **any other node's body** (a lore entry, where line edits also run): a **`node`-scoped file TODO** on that node, quoting the words. It is a writer-made TODO (no `source`), and like any `node` TODO it appears in the entry's review items.
   - **Writing it.** A file TODO goes through the batch TODO call follow-ups added (`createTodos`, which refreshes the TODO store); a failed write leaves the flag where it is and says why. An embedded TODO is a mark on the editor's document and is saved with the scene. The `todoAnchor` mark is the outermost mark (`priority`), so a TODO over formatted words serializes as one marker pair.
   - **Cost.** A line-edit run records its cost when the writer took anything from it: an edit accepted **or kept**.
   - `EDITS` becomes a factory taking the run's callbacks, like `notesKind(links)`; both cards' action sets gain `keep`.

4. **Follow-ups from a revise commit.** A commit to the **revise** destination may also return **follow-ups**: changes the conversation established for OTHER lore entries.
   - **Asked for, only there.** The extraction turn asks for `follow_ups: [{entry, change, why}]` only when the commit is a revise, and only for changes the conversation established. Stage and create commits don't ask. Any prompt whose output is `extract_to_node` and commits to an existing entry takes part (Revise entry, the plot and arc revisers, Follow a change, Summarize scene); no per-prompt switch.
   - **Entries by name.** The extraction turn carries ids only for the conversation's explicit picks, so `entry` is the entry's **name**, as the conversation used it. The backend resolves it against lore titles and aliases, case-insensitively; a name that matches no entry, matches more than one, or is the entry being committed is dropped. Dropped follow-ups are counted on `AIEntryPatch.follow_ups_dropped` and in the `ai_commit_extraction` trace.
   - **One field, one value.** A reply that sets a field twice is garbled (one retry, then an error), never resolved to the last value: it is how a model that also wrote the other entry's text into `fields` shows (#2504, found on Qwen3.8-9B), and the instruction says another entry's text never goes in `fields`.
   - **Shape and parsing.** The response schema declares `follow_ups` after `fields` (`fields` stays required, possibly empty), so Ollama's ordered grammar emits it second, and the envelope's example shows that order. The parser accepts an object whose only content is follow-ups (`{"fields": [], "follow_ups": [...]}`); a commit with follow-ups and no field changes is a valid result, not "proposed no changes". Follow-ups are not writes to the committed entry, so ADR-0067 §4's field contract doesn't govern them.
   - **Review.** The entry's commit review lists them below the patch: the entry's name, the change, the why, each with a tick box, **unticked**.
   - **Done.** Writes the patch as today (when anything was adopted), then creates the ticked follow-ups in one call to a new batch endpoint, `POST /api/todos/batch` (over `_create_todo_items`). If that call fails, the review stays open with its ticks and an error; the patch, already written, is not rolled back. Done with ticked follow-ups and no adopted change writes only the TODOs. Discard drops the follow-ups with the patch.
   - **What they are.** Each is a `node`-scoped TODO on the named entry with `source = {node_id: <the committed entry>, reason: "follow_up"}`. `TodoSource.reason` gets its own type, `TodoSourceReason = ChangeCandidateRoute | "follow_up"` (backend and frontend), so `follow_up` never becomes a change-candidate route; the review-item detail line gains its phrase ("follow-up from *Kaela Voss*").
   - **Acting on one.** A follow-up is an ADR-0090 review item on its entry. Its Propose opens **Revise entry** (not *Follow a change*) with the follow-up's change as the opening request; adopting the resulting patch marks it done, as for every review item.

5. **`todos(x)`: prompts read TODOs.** A prompt helper returning the open TODOs on a node.
   - `x` may be an entry (EntryRef), a node id, or a scene; `None` or an unknown node gives `[]`.
   - Each item is `{text, quote, from}`: `quote` the words a TODO is anchored to (an embedded TODO, or a file TODO with an anchor) or `""`; `from` the title of its source node (a follow-up's origin) or `""`.
   - Which: for any node, its `node`-scoped file TODOs; for a scene, also its `scene`-scoped file TODOs and its embedded TODOs.
   - **As saved.** Embedded TODOs are read from the saved scene, and the TODOs are read when the template renders — for a conversation, when it starts. A TODO added or ticked mid-conversation shows next time.
   - It prints nothing; the template decides what to show. The logic lives in its own module; `helpers.py` registers it in a few lines (if that crosses the 1500-line cap, another registration moves out with it), and it is documented in `docs/prompts/reference.md` with the vocabulary gate.
   - **Revise entry reads them.** The built-in's system prompt lists the entry's open TODOs, when there are any, as things the writer means to address. (A project's own clone of Revise entry keeps its old text; Library prompts are cloned, not forked.)

## Rejected alternatives

- **One commit that changes several entries.** It breaks ADR-0046's one-entry patch and puts edits to entries the writer isn't looking at into one review. A follow-up is applied by revising its own entry, with its own review.
- **Persisting flags in a store of their own.** A second list of pending items beside TODOs, with its own pane and lifetime. TODOs already are that list.
- **Follow-ups as notes on the other entry.** Notes are flags and flags are transient; a follow-up must survive until the writer gets to it.
- **Follow-ups naming entries by id.** The extraction turn shows ids only for explicit picks, so most follow-ups — about entries the conversation reached by name — would be dropped. Widening that turn's lore to carry every id would make each commit much larger.
- **TODOs put into context automatically.** The writer chose reading: a prompt decides whether and how TODOs matter, and the template shows it.
- **Tags as workflow** ("needs revision"). A tag says what a node is about; it can't say what to change or be ticked off. Filtering TODOs by the tags of the node they sit on is a possible later view, not this ADR.
- **Follow-ups ticked by default.** The AI would decide what persists.
- **Keep overwriting an existing TODO's anchor.** It would silently delete the writer's own TODO.

## Anti-goals

- No edits to any entry other than the one being committed.
- No TODO the writer didn't choose; no TODO marked done without the writer's tick or adoption.
- No new storage: file TODOs and embedded TODOs as they are, plus one `reason` value.
- No tool calls.

## Consequences

- Flag cards gain **Keep**; the review plugin gains the `kept` outcome; `EDITS` becomes a factory; `TodoAnchors` gains `markRange`, and `enforceUnique` treats one paragraph's adjacent same-id nodes as one TODO.
- A batch TODO endpoint is added (follow-ups), and Keep uses it for file TODOs.
- The extraction envelope (revise only), the patch schema, the parser, `AIEntryPatch` (`follow_ups`, `follow_ups_dropped`) and the entry review learn follow-ups; `TodoSourceReason` is split from `ChangeCandidateRoute`; a follow-up's Propose opens Revise entry.
- One prompt helper (`todos`); the built-in Revise entry reads it.
- AGENTS.md gains *flag*.
- Planned slices, each its own PR: **S1** Keep as TODO; **S2** `todos(x)` and Revise entry reads it; **S3** follow-ups.
