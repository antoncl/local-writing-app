# ADR-0098: A lore check answers with notes, not edits

**Status:** Accepted — 2026-10-15, Anton Lauridsen, after the feature was built against it as a living draft (2026-10-14 → 2026-10-15). Text by Claude from conversations with Anton that began with the Ollama tool-use brainstorm. Issue #2488; slices #2490 (S1: notes end to end), #2491 (S2: lore as of the selection), #2492 (S3: authoring notes prompts), #2488 (S4: links from the scene's references; the unnamed-lore measurement).
**Context verified against `ecea329d` (2026-10-14), the code before the feature.**

While a living draft, each slice rewrote the decisions it changed in place; from this approval on, a change is an amendment, as for any ADR.

## Context

Line edit (#2460) proposes small, reasoned edits to a selection. It can't catch prose that contradicts the story's lore. When a scene says Kaela's eyes are green and her lore entry says grey, a line edit either ignores it or has to guess which side is right. On a real entry with a planted contradiction, both local models tested left it alone. That's correct: the prompt forbids inventing facts, and only the writer knows which fact is true.

The writer wants to see such contradictions where they occur, and decide.

### What this builds on

- **Edit lists.**
  - The JSON reply is enforced on Ollama by `ChatCall.response_schema` (`backend/app/services/ai/profiles/base.py:378`, sent as `format` in `profiles/ollama.py:238-242`). Cloud profiles ignore it, and a tolerant parse reads the reply (`read_line_edits_reply`, `backend/app/services/ai/line_edits.py:67`).
  - The reply streams, so Cancel stops the provider (`LineEditsStreamCollector`, `line_edits.py:78`; `ClosingStreamingResponse`, `backend/app/routers/ai.py:577`).
- **Placing a quote.** `placeLineEdits` (`frontend/src/lib/editor-core/lineEdits.ts:80`) places an item only when its quote occurs exactly once in the selection, after typographic normalization. It drops items that overlap an already-placed one.
- **The review surface.** The `LineEditSuggestions` plugin (`frontend/src/lib/editor-core/lineEditSuggestions.ts:234`) holds the items in plugin state, not in the document, and shows one current item with a card (`buildLineEditCard`, `frontend/src/lib/editor-core/lineEditCard.ts:37`). Parts of it are specific to edits:
  - Alt+Enter accepts;
  - accepting an item whose `replace` is empty deletes its range;
  - Accept all;
  - the old text is struck through.
- **Inline handlers.** These are registered output handlers (`_REGISTRY`, `frontend/src/lib/editor-core/outputHandlers.ts:225`). Each answers its own `surface(output)` and is offered by `offer_on` (`inlinePromptsOfferedOn`, `frontend/src/lib/editor-core/promptResolution.ts:433`). Ctrl+Shift+J runs the first selection prompt in title order.
- **Lore on one-shot runs.** ADR-0092 Amendment 1, decision 5: inline actions run one-shot and carry **declared lore only**, that is the prompt's `use()` picks and the *always* entries, never automatic lore.
- **Name detection.** Automatic lore detects names with `_build_scene_matcher` + `_scan_matcher_ids` (`backend/app/services/ai/lore_selection.py:488`, `:522`). Only entries whose context policy is *Automatic* are in that matcher (`:512`).
- **Lore position.** `lore_as_of("start")` (`backend/app/services/ai/helpers.py:649`) sets the position in the target scene that each placed entry resolves at. Unset means the end of the scene.
- **The lore block.** It gives the model each entry's `id` and effective name (`<{entry_type} id="..." name="...">`, `backend/app/services/ai/lore_block.py`, `_render_node_xml`).

### Measured: lore in the prompt versus tool lookups

Local Ollama, one 3-sentence passage with four planted contradictions against four lore entries, all four named in the passage (eye colour, which hand carries a scar, airlock count, an open flame where none is allowed). 5 trials per cell. A trial "finds" a contradiction when its notes name both the passage's word and the lore's.

| Model | Lore in the prompt, reply forced by `format` | Tool lookups, then a reply forced by `format` |
|---|---|---|
| Gemma4 (uncensored) | 20/20, 67 s | 20/20, 95 s |
| Qwen3.8-9B | 18/20, 56 s | 20/20, 163 s |
| llama3.2 (3B) | 7/20, 8 s | 2/20, 12 s |

A single tool pass whose final reply was *not* forced produced a readable answer only 1 time in 5 on Qwen3.8-9B. Forcing the final reply made every answer in both columns readable.

**At this scale:**
- Lore in the prompt found the same as tool lookups on Gemma4 and two fewer on Qwen3.8-9B.
- It took 0.34–0.70 of the tool latency.
- It works on any model, including those that report no tool support.

### Measured again: lore the passage doesn't name (#2488)

The same lore, plus two distractors, and a passage that names none of the contradicted entries: "She pushed through the crowd on the docks, her green eyes … She flexed her right hand, the old scar … The short, loud dockmaster was waiting by the ship's twin airlocks, a candle burning in his good hand." *She* is the POV character (Kaela), *the ship* is her ship (the Lantern), *the docks* are her station's (Meridian), and *the dockmaster* (Orren Dask) is reached by his title alone: nothing names him and nothing links to him. Five planted contradictions. Conditions:
- **POV only**: what `lore_named_in` sent before this measurement (nothing is named; the scene's POV is).
- **POV + links**: the POV entry and what it links to (her ship, her station).
- **Tools**: `list_lore` (names plus a one-line gist) and `lookup_lore`, then a final reply.
- **Hybrid**: the POV and its links in the prompt, and the tools for anything else.

| Model (trials) | POV only | POV + links | Tools | Hybrid |
|---|---|---|---|---|
| Haiku 5.5 (10) | 20/40 | 38/50 (title 0) | 49/50 (title 10/10), ~13× the input tokens | 49/50 (title 10/10) |
| Gemma4, Q5_K_M (5) | 10/20 | 20/25 (title 0) | 20/25: title 5/5, the candle 0/5 | 20/25 (title 0, no title lookup) |
| Qwen3.8-9B, Q4_K_M (5) | 10/20 | 16/25 (title 0) | 8/25 | 19/25 (no tool calls at all) |

(The "POV only" cells for the local models and Haiku come from the first run of this measurement, without the title contradiction.)

**What it shows:**
- Following links from the scene's references is the universal gain: every model goes from half to nearly all of what names and links can reach, at no extra latency, on any model.
- Tools add one thing — references by title alone — and only on a strong model: Haiku found the dockmaster every time, the local models with lore already in the prompt never looked him up.
- On a weak model tools are a hazard: Qwen with tools found fewer contradictions than with no extra lore at all. Hybrid avoids that collapse, but only because the local models then stop calling tools.
- An alias covers the title case for every model: "the dockmaster" as an alias of Orren Dask makes him *named*.
- A model's advertised tool support is not proof: lfm2.5's Ollama package reports tools, but its chat template renders none, so it never saw the tools (0 calls).

## Decision

1. **A new built-in, *Check against lore*, offered on scenes (`manuscript:scene`), answers with notes, not edits.**
   - A note is `{quote, problem, entry}`:
     - `quote`: the exact words in the selection;
     - `problem`: what they contradict, in one sentence;
     - `entry`: the **id** of the lore entry they contradict, as given in the lore block.
   - A note never proposes replacement text. Which side is right is the writer's call, and a note that also rewrote the prose would make that call for them.
2. **Notes are a new inline output handler, `inline_notes`.**
   - It answers the `selection` surface and is offered by `offer_on` like every inline prompt.
   - Writers can author their own: `PromptOutputEditor` offers it as "Notes". Its reply contract ships as an includable snippet, *Notes reply format*, as *Edit list reply format* does for edits.
   - The prompt shelf is *Revise prose*, where it's run from.
   - Ctrl+Shift+J never picks it: the selection default considers only prompts that revise (`inline`, `inline_edits`).
3. **The reply path is the edit list's:**
   - a backend-owned `NOTES_RESPONSE_SCHEMA`, forced on Ollama;
   - a tolerant parse;
   - the **streaming** route, so Cancel stops the provider. The non-streaming route refuses notes.
   - The backend drops a note whose `entry` is not one of the ids the run sent. The model can only contradict lore it was shown, so an unknown id is invented. Such notes count as dropped.
   - The invocation is recorded in the cost ledger when the notes arrive, not on an accept, because a check has nothing to accept.
4. **Placement:**
   - A note is placed when its `quote` occurs exactly once in the selection.
   - Notes **may overlap**: two problems with the same words are both real.
   - An unplaceable quote is dropped and counted.
5. **The review is the shared review surface, parameterized by the run's handler,** not a copy and not a mode flag on one item type. For notes:
   - **Display:** the quoted text gets a quiet underline tint, with the current note stronger; never a strike-through.
   - **Card:** the problem, the entry's name, and three actions:
     - **Open entry** opens that lore entry in a pane;
     - **Dismiss** drops the note;
     - ‹ › step between notes.
   - **Keys:**
     - Alt+Down / Alt+Up step;
     - Alt+Backspace dismisses;
     - Alt+Enter does nothing. There is no accept, and nothing ever deletes or changes text.
   - **Footer:** the count, Dismiss all, Retry, and the model/cost.
   - **Lifetime:**
     - A note whose quoted words the writer edits is dropped, as an edit is.
     - Closing the document or Dismiss all ends the review.
     - The document is never written, and notes are not persisted.
   - **Concurrency:** one pending review per editor, edits or notes. A new run is refused while one is open, as today.
   - **Notices:**
     - "No contradictions found." when the reply is empty;
     - "N notes couldn't be matched and were skipped.";
     - "None of the N notes could be placed.";
     - "Check cancelled." on Cancel.
6. **The lore a check sends is declared by the prompt.** A new helper, `lore_named_in(text)`, returns the ids of:
   - the entries named or aliased in `text`, found by the same matcher automatic lore uses, so entries set to *Manual only* or *Never include* are not detected;
   - the entries those link to through their reference fields, again excluding *Manual only* and *Never include*;
   - the scene's own reference-field targets (its point-of-view character, its location);
   - the entries those link to, excluding *Manual only* and *Never include* (#2488). A passage that only says "she", "the ship" or "the docks" still brings the POV character's ship and home — measured above, it is what closes the gap for every model.

   The prompt also includes the *Relevant lore* picker, the box Expand and Describe already show. Entries the writer picks there are sent too, so lore the passage doesn't name (a pronoun, a title, an implication) can still be checked when the writer knows it matters.

   **Why this fits ADR-0092:**
   - The template places the set with `use()`. Because the prompt names it explicitly, it is declared lore, and automatic lore stays off one-shot runs.
   - The *always* entries come along as declared lore does today. They define the world, and a contradiction with them is exactly what the check is for.
   - Declared lore is never budgeted (ADR-0086 §1). A selection naming many entries sends all of them, bounded by the selection the writer chose.

   **What the template does:**
   - If neither `lore_named_in(selection)` nor the picker gives an entry, it calls `stop("Nothing in the selection names a lore entry, and none was picked.")`, so a check with no lore to check against never reaches the model.
   - The helper's logic lives in `lore_selection.py`. `helpers.py`, which is near its size cap, only registers it, and its documentation lands in `docs/prompts/reference.md` with the vocabulary gate.
7. **Lore is checked as of the selection.** Entries resolve at the selection's start: earlier scenes' mutations and the ones anchored in this scene before the selection count, while the ones after it don't. Without this, a change of state placed later in the scene reads as a contradiction of the text before it. The check calls `lore_as_of("selection")`.
   - The request names the mutation markers (anchors and closes) that come before the selection, in document order, by id: `markers_before_selection`.
   - The position is the saved offset of the last of those markers that exists in the saved scene. An id not saved yet is skipped. With no marker, the position is the start of the scene.
   - Marker ids rather than a character offset, because the mutations index is built from the saved file: an offset taken from the editor would drift with any unsaved text before the selection, and a marker's identity does not.
   - The resolver is unchanged. An anchor counts when its offset is at or before the position and a close when the position is at or past it, so the last marker and every earlier one count while every later one does not.
8. **The review says what was checked.** The footer lists the entries the run sent: "Checked against: Kaela, The Meridian, …". The check sees only the lore it was given, so "No contradictions found." means none against *those* entries, and the list shows the writer what was left out.
9. **No tool calling.** The lore is gathered by names, links and picks (decision 6). Tool lookups stay deferred (see Deferred).

## Deferred

- **Tool lookups, for references by title alone.** Measured (above, #2488): links from the scene's references close the unnamed-lore gap for every model; tools add only the title-only reference, and only on a strong model, at about three times the latency and thirteen times the input tokens, while a weak local model with tools found fewer contradictions than with none. An alias covers the title case on any model. Reconsidered only if writers hit title-only references that aliases can't reasonably cover, and then as hybrid (links in the prompt, tools for the rest), opted into per assistant rather than switched on by a model's advertised tool support — which proved unreliable (lfm2.5).

## Rejected alternatives

- **Notes as edits** (an edit list whose `replace` corrects the prose). This forces a choice between the two sides: the prose is assumed wrong when the lore may be the stale side, or every note needs two fixes. The writer's journey is "show me, I decide".
- **Naming the entry by title.** A title is not an identity:
  - entries get renamed;
  - aliases and an entry's as-of-scene name differ from its title;
  - inherited layers can hold the same title twice;
  - a model can invent one.
  
  The lore block already gives each entry an id, and checking the id against the set that was sent turns an invented reference into a counted drop.
- **Automatic lore on this one-shot run.** ADR-0092 rejected it: on Roleplay it would detect and expand on every beat, uncached. A per-prompt exception would reopen that for any author who copies the prompt. A declared helper keeps the rule and shows in the template.
- **Offering the check on lore entries.** On an entry's own pane the helper names the entry itself, and the model is handed the *saved* entry to check the unsaved draft against. Checking an entry against other entries is a different job (lore against lore), excluded below.
- **A conversation instead of an inline action.** It would get automatic lore for free, but the result is a transcript rather than notes at the words they're about. The writer is reading prose, and the notes belong on it, the same lesson as the Line edit card: put the decision beside the item.
- **Lore as of the end of the scene (today's default).** It turns every later mutation in the same scene into a false contradiction.

## Anti-goals

- No writes to the document or to any lore entry. A note never fixes anything.
- No persisted notes, no note history, no notes on save.
- No lore against lore (entry against entry), and no scene against other scenes.
- No gating by model size.

## Consequences

- One registered handler, one built-in prompt and one built-in snippet. The review plugin gains a per-handler definition of display, card, keys and resolution. Edits keep theirs unchanged.
- One prompt-vocabulary helper (`lore_named_in`) and a `"selection"` value for `lore_as_of`, fed by the request's `markers_before_selection`. Both are documented in `docs/prompts/reference.md`, with the vocabulary gate.
- `PROMPT_OUTPUT_HANDLER_KEYS`, `OUTPUT_HANDLER_KEYS` and `spec/prompt-disposition-labels.json` gain `inline_notes`. The stale comment on `AIGenerateRequest.response_format` (it still says only the non-streaming route serves line edits) is corrected.
- A check's notes are lost when its document closes. The run is paid for and the result is temporary. Keeping notes (as TODOs, or anywhere) would be a later decision with its own ADR.
- A selection that names many entries sends all of them, every picked entry and every *always* entry, unbudgeted.
- A contradiction with lore the passage doesn't name, and that the writer didn't pick, goes unseen in the first version. The "Checked against" list makes that visible rather than silent.
- On the measured passage a 3B model found 7 of 20 where 9B models found 18–20. The check is only as good as the assistant, which is the writer's choice.
