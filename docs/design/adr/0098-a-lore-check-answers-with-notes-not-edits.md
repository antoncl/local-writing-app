# ADR-0098: A lore check answers with notes, not edits

**Status:** Proposed (2026-10-14) — #2488
**Verified against `ecea329d` (2026-10-14).**

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

The measurement says nothing about lore that the passage doesn't name.

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
   - the scene's own reference-field targets (its point-of-view character, its location).

   **Why this fits ADR-0092:**
   - The template places the set with `use()`. Because the prompt names it explicitly, it is declared lore, and automatic lore stays off one-shot runs.
   - The *always* entries come along as declared lore does today. They define the world, and a contradiction with them is exactly what the check is for.
   - Declared lore is never budgeted (ADR-0086 §1). A selection naming many entries sends all of them, bounded by the selection the writer chose.

   **What the template does:**
   - If `lore_named_in(selection)` is empty, it calls `stop("Nothing in the selection names a lore entry.")`, so a check with no lore to check against never reaches the model.
   - The helper's logic lives in `lore_selection.py`. `helpers.py`, which is near its size cap, only registers it, and its documentation lands in `docs/prompts/reference.md` with the vocabulary gate.
7. **Lore is checked as of the selection.** Entries resolve at the selection's start: earlier scenes' mutations and the ones anchored in this scene before the selection count, while the ones after it don't. Without this, a change of state placed later in the scene reads as a contradiction of the text before it. `lore_as_of` already carries a position in the scene for its `"start"` value, and the check needs that position to be the selection's.
8. **No tool calling in this ADR.**

## Rejected alternatives

- **Notes as edits** (an edit list whose `replace` corrects the prose). This forces a choice between the two sides: the prose is assumed wrong when the lore may be the stale side, or every note needs two fixes. The writer's journey is "show me, I decide".
- **Naming the entry by title.** A title is not an identity:
  - entries get renamed;
  - aliases and an entry's as-of-scene name differ from its title;
  - inherited layers can hold the same title twice;
  - a model can invent one.
  
  The lore block already gives each entry an id, and checking the id against the set that was sent turns an invented reference into a counted drop.
- **Automatic lore on this one-shot run.** ADR-0092 rejected it: on Roleplay it would detect and expand on every beat, uncached. A per-prompt exception would reopen that for any author who copies the prompt. A declared helper keeps the rule and shows in the template.
- **Tool lookups as the mechanism.** At this scale they found the same or two more contradictions, at 1.4–2.9× the latency, and only on models that support tools. They are reconsidered only against a measured case where the lore the passage needs is *not* named in it.
- **Offering the check on lore entries.** On an entry's own pane the helper names the entry itself, and the model is handed the *saved* entry to check the unsaved draft against. Checking an entry against other entries is a different job (lore against lore), excluded below.
- **A conversation instead of an inline action.** It would get automatic lore for free, but the result is a transcript rather than notes at the words they're about. The writer is reading prose, and the notes belong on it, the same lesson as the Line edit card: put the decision beside the item.
- **Lore as of the end of the scene (today's default).** It turns every later mutation in the same scene into a false contradiction.

## Anti-goals

- No writes to the document or to any lore entry. A note never fixes anything.
- No persisted notes, no note history, no notes on save.
- No lore against lore (entry against entry), and no scene against other scenes.
- No tool calling.
- No gating by model size.

## Consequences

- One registered handler, one built-in prompt and one built-in snippet. The review plugin gains a per-handler definition of display, card, keys and resolution. Edits keep theirs unchanged.
- One prompt-vocabulary helper (`lore_named_in`) and a selection position for `lore_as_of`. Both are documented in `docs/prompts/reference.md`, with the vocabulary gate.
- `PROMPT_OUTPUT_HANDLER_KEYS`, `OUTPUT_HANDLER_KEYS` and `spec/prompt-disposition-labels.json` gain `inline_notes`. The stale comment on `AIGenerateRequest.response_format` (it still says only the non-streaming route serves line edits) is corrected.
- A check's notes are lost when its document closes. The run is paid for and the result is temporary. Keeping notes (as TODOs, or anywhere) would be a later decision with its own ADR.
- A selection that names many entries sends all of them and every *always* entry, unbudgeted.
- On the measured passage a 3B model found 7 of 20 where 9B models found 18–20. The check is only as good as the assistant, which is the writer's choice.
