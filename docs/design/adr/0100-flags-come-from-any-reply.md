# ADR-0100: Flags come from any reply, not from an output mode

**Status:** Accepted — 2026-10-16, Anton Lauridsen, after the feature was built against it as a living draft (2026-10-16). Text by Claude from a conversation with Anton about a *Scene / doctor* reply that held both notes and an edit with nowhere to put them; revised against a cold implementing thread. Epic #2517; slices #2519 (S1: one review, both kinds), #2520 (S2: Place flags), #2522 + #2525 (S3: the *Revising* layout), #2531 (S4: line edits look like diffs), and #2533 (older text first, which S4 surfaced).
**Context verified against `36b7894c` (2026-10-16), the code before the feature.**

While a living draft, each slice rewrote the decisions it changed in place; from this approval on, a change is an amendment, as for any ADR. The real-model run of S2's journey on *The Water Line* had not been done at approval; it is Anton's to do.

## Context

A *flag* is an item the AI places on the prose for the writer to decide on — a line edit or a note (ADR-0099 §2, AGENTS.md). Today a flag can only come from one place: the **entire** reply of a one-shot prompt run on a selection.

- **Line edits** (#2460, handler `inline_edits`): the reply is ONLY JSON, `{"edits": [{find, replace, reason}]}` (`backend/app/builtin_library/prompts/edit-list-format.md`), read by `parse_line_edits` (`backend/app/services/ai/line_edits.py:44`), which treats a reply without an `edits` key as unreadable. Accept writes `replace` as text into the passage's own paragraph (`resolve`, `frontend/src/lib/editor-core/reviewKinds/edits.ts`), so a replacement can't add a paragraph.
- **Notes** (ADR-0098, handler `inline_notes`): ONLY JSON, `{"notes": [{quote, problem, entry}]}` (`notes-reply-format.md`). `_read_notes` (`backend/app/services/ai/line_notes.py:52`) skips a note with an empty `entry`, and `read_line_notes_reply` (`:79`) drops one naming an entry the run didn't send. The card always shows the entry and an *Open entry* button (`buildLineNoteCard`, `lineNoteCard.ts`), and Keep writes `problem (Entry)` (`noteKeepNote`, `keepFlag.ts`).
- Both are placed by `placeLineEdits` / `placeLineNotes` (`frontend/src/lib/editor-core/lineEdits.ts:109`, `:141`), which take a `from`/`to` range and use `locateIn` (`:85`): a quote must occur **exactly once** in the range's text blocks, after `normalize`'s 1:1 typographic map, never across blocks; one that doesn't is dropped and counted.
- **The review** is one ProseMirror plugin holding **one kind at a time**: `ReviewState.review: ReviewKind | null` (`reviewKinds/core.ts`); an `install` replaces the plugin's list. Around it, the scene pane's `AiSuggestionController` (`aiSuggestion.svelte.ts`) owns everything else about a run: the watchers that close a review when its kind's items are gone, Keep (`#keepFlag`, ADR-0099 §3), cost, and the footer bars, which show an edits bar or a notes bar (`EditorFooter.svelte`), each with a Retry that re-runs the pane's last prompt on a selection.
- **A conversation's reply can't carry flags at all.** `AIChatRequest` (`backend/app/models/ai.py:483`) has no `response_format` (only `AIGenerateRequest`, `:624`, does), and only the scene pane's controller and its helpers place flags.
- **Quote links** (#2498) are the conversation's read-only cousin: a quoted run in a reply that occurs in the subject scene links to it (`findQuote`, `frontend/src/lib/chat/quoteLinks.ts:54`), over the scene's plain text — the open pane's live draft, else the saved scene (`QuoteSourceController`, `quoteSource.svelte.ts`). A click opens the scene beside the chat (`revealQuoteBeside`, `frontend/src/lib/stores/quoteReveal.ts:66`). A chat that writes its scene's body gets no links (`chatWritesProse`, #2513).
- **The precedent for turning a conversation into structure** is the commit: `run_entry_patch_extraction` (`backend/app/services/ai/extraction.py:482`) continues the chat with one extraction turn, under `lore_mode="used"` (only the conversation's explicit picks carry `id=`), with a response schema and one retry on a garbled reply, recording its cost against the chat. Follow-ups name entries in prose, resolved against lore titles and aliases (`resolve_follow_ups`, `backend/app/services/ai/follow_ups.py:20`).

The case that prompted this: *The Water Line — Scene / doctor*, a project prompt run as a conversation. Its diagnosis quotes passages and says what is wrong with each — notes — and its Route B sketch is two paragraphs of new text "placed after *I am already on the aisle to the loading door*" — an edit. Neither can reach the prose; the writer copies and flips between reply and scene, which is what this app exists to avoid.

**A precondition, not a design driver:** LWA requires decent models (Anton, 2026-10-16; recorded here, as no document states a floor yet). Turning a reply into well-formed flags is within what such models do; this ADR does not design around models that can't.

## Decision

1. **A flag belongs to a reply, not to a prompt.** A finished assistant reply in a conversation about a scene can be turned into flags, whatever the prompt's output handler and wherever the prompt list shelves it — the doctor, a craft check, a revise conversation, any project prompt — with no change to the prompt.

2. **Placing flags is the writer's action on a reply.** A finished assistant reply gets **Place flags** when the conversation's subject is a scene and the conversation doesn't write the scene's body (the #2513 rule: its replies *are* the prose). The writer picks the reply; it need not be the last one. Nothing is placed automatically.

3. **One extraction turn makes the flags,** on the backend, as a commit's does.
   - **The transcript ends at the chosen reply.** Turns after it are not sent, so "what the reply said" is unambiguous; a later turn that retracted a suggestion doesn't count.
   - **It carries the scene's current text** — the plain text of the open pane's live draft, else of the saved scene, as quote links read it — and says to quote **only** from that text. The conversation's own system prompt may hold an older version of the scene; the attached text is the one on the page now.
   - **It asks** for the chosen reply's suggestions about that text, and only what the reply actually said, as `{"edits": [{find, replace, reason}], "notes": [{quote, problem, entry}]}`: a change the reply proposed becomes an edit; a remark about a passage becomes a note. New text placed after a passage is an edit whose `find` is the passage and whose `replace` is the passage followed by the new text; `replace` may contain paragraph breaks (decision 6).
   - **Shape.** A response schema with both arrays required, `edits` first, so Ollama's ordered grammar emits them in that order. On this path a missing `edits` or `notes` key reads as an empty list. A garbled reply is retried once, then reported, as a commit's is.
   - **Readers.** Edits are read by `parse_line_edits`'s item rules. Notes by `_read_notes`, which gains `entry_required` (true for `inline_notes` runs, false here).
   - **A note's `entry` is optional here, and may be a name.** It is resolved first as an id the turn showed (an explicit pick), then against lore titles and aliases, case-insensitively — one name-to-entry lookup, factored out of `follow_ups.py` and shared with follow-ups. A note with no entry, or one that resolves to none or to several, is placed **without** an entry: it is a remark, not a lore contradiction. ADR-0098's rule — a lore-check note must cite an entry the run sent — stays for `inline_notes` runs, where the entry is the point.
   - **Not streamed, no Cancel** in this slice, as the commit isn't. Traced as `ai_flag_extraction`, beside `ai_commit_extraction`.

4. **Placed in the scene's pane, across the whole scene.** The flags go to the scene pane's `AiSuggestionController`, which places them against the **live** document when they arrive, with the existing placers over the whole body (`0` to the document's end) — no new placer. The scene opens beside the conversation when it isn't open; that opening is factored out of `revealQuoteBeside` and shared by both. Flags that can't be placed are counted in one notice ("2 of 9 flags couldn't be found in the scene").

5. **One review holds both kinds.** The kind moves from the review to the item: each item carries its kind, which supplies its decoration, card, key and validity check.
   - Items are kept in position order (an install sorts them, since a mixed list arrives one kind after the other) and step across both kinds; the cards' ‹ › step through all of them.
   - Flags from a conversation get one combined bar ("Flag i of n", *Accept all edits* while any edit remains, *Reject all*); a selection run's review keeps its own bar as today.
   - **Accept all** applies the edits only; **Reject all** rejects the edits and dismisses the notes. Keep (ADR-0099 §3) works on both.
   - **Retry** is hidden for flags placed from a conversation: it re-runs a selection prompt, which isn't what made them.
   - The review closes when no item of **either** kind remains.
   - An edit and a note may cover the same words; accepting the edit drops the note, since its quote no longer holds — as typing over any flag does today.
   - Placing flags while a review is open closes that review first — its items, watchers and bar — and opens the new one, as a new selection run replaces the old.

6. **An edit's replacement may hold paragraphs.** A `replace` containing a blank line is applied as paragraphs: Accept splits the passage's paragraph at the edit and inserts the new paragraphs, and the proposed-text widget shows the breaks. A `replace` of only blank lines is a cut. This holds for every edit, from a selection run too; the selection runs' reply format is unchanged.

7. **A note without an entry** shows no entry line and no *Open entry*; Keep is its first action, and its TODO text is the `problem` alone. The notes bar's *Checked against* is hidden for flags from a conversation.

8. **Cost** is recorded on the **conversation**, by the backend, as a commit's is, and returned as the chat's new total. It is not added to the scene's `cost`.

9. **The selection prompts are unchanged.** `inline_edits` and `inline_notes` stay one-shot handlers with their JSON-only reply formats — the case of a reply that is nothing but flags, on a selection. No new output handler, no new disposition: the prompt list doesn't change.

10. **A built-in *Revising* layout.** Working through flags is a scene beside its conversation, so the workspace ships a built-in layout preset for it, beside *writing*, *schema* and *research* (`PRESETS`, `frontend/src/lib/stores/workspaceLayout.serialize.ts`), as Anton arranges his own: Draft and Lore on the left; the editor and a wide right group holding TODO (where kept flags land), Search and Chats, as equal halves. A fresh preset's right group holds no document, so the first quote link or Place flags splits the scene out beside the chat; once moved to the right group it stays.

11. **A line edit looks like a diff** (Anton, 2026-10-16). The diff reviews (proposal review, snapshot compare, the conflict and propagation views) share one look: the text on the page is **warm** (`r-now`: a warm wash with a solid edge) and the other version is **cool** (`r-was`: a cool wash with a dotted edge), marked word by word, with no strike-through. A line edit used its own language instead (struck-through, muted old text and an accent-underlined replacement over the whole passage). Now it uses theirs:
   - The edit's words are compared with the diff engine (`diffRuns`, `frontend/src/lib/utils/snapshotDiff.ts`), the replacement as the other version and the passage as the text on the page. Words only in the passage are marked warm in place; words only in the replacement appear inline, cool, where they would go; shared words stay plain. Changing one word in a long sentence marks that word.
   - The look is the diff reviews' own: `.r-now` / `.r-was` move to the global stylesheet as the one source of the diff look, rather than a copy for line edits.
   - What makes a flag a flag stays: the reason card, per-edit Accept / Keep / Reject with their keys, the current item (the whole passage under review gets a soft tint; an outline would box each marked word separately), and Accept still writes the whole replacement. Notes are unchanged — they propose no text.
   - Not part of this: a Current / Proposed / Both view of the scene under review (a new view, Post-1.0), or the diff reviews' disagreements with each other (#2530).

## Rejected alternatives

- **Flags written inside the conversational reply** (markup the model emits as it talks). Every prompt would have to teach the format, the transcript would carry it, and a prompt not written for it would get nothing — the opposite of decision 1.
- **Extracting flags after every reply.** A second call on every turn, and the AI deciding what reaches the prose.
- **Extracting from the transcript alone, without the scene's text.** Quotes recalled from an older draft, or paraphrased, don't place.
- **The whole transcript, with the chosen reply named.** The model would weigh later turns, and "what this reply said" would blur.
- **Notes' `entry` by id only.** Most remarks aren't about a lore entry, and the turn has ids only for explicit picks; requiring one would drop nearly every note.
- **Sketches as notes, keeping edits within one paragraph.** The Route B sketch — the case this ADR exists for — would arrive as a remark to copy by hand.
- **Two reviews at once, one per kind.** Two current items and two sets of keys on one document.
- **Quote links as flags.** A quote link asks for no decision; it stays a link.

## Anti-goals

- No edit applied without the writer's Accept; no flag persisted except by Keep (ADR-0099).
- No change to the selection prompts' handlers or reply formats.
- No new output handler or disposition.
- No tool calls.
- This is **not** a consolidation of the app's quote locators: `findQuote`, the reveal's search match and the review's re-check stay as they are.

## Open

- The action's label and where it sits on a reply.

## Consequences

- A stored review item carries its kind; the kind's per-item parts are dispatched per item, and stepping crosses both kinds (S1, built). The combined bar, and the run that closes a mixed review only when both kinds are gone (S2, built).
- Accept and the edit widget handle a `replace` with paragraph breaks (S1, built).
- One backend endpoint for the extraction turn; `_read_notes` gains `entry_required`; a name-to-entry lookup is shared with follow-ups; a new trace kind (S2).
- **Place flags** on assistant replies in scene conversations; its wiring lives in its own module (`ChatBodyView.svelte` is at 1450 of 1500 lines), with the transcript taking the action per message; the scene pane's controller gains an entry point that installs flags from outside the pane; opening the scene beside the chat is shared with quote reveal (S2).
- A built-in *Revising* layout preset (S3).
- Line edits render as word-level diffs in the diff reviews' look; `.r-now` / `.r-was` become global (S4).
- Planned slices, each its own PR:
  - **S1 — one review, both kinds; edits that add paragraphs.** *Done when:* a test installs edits and notes together and steps, accepts, keeps, dismisses and Accept-alls across them, and the review closes only when both are gone; an edit whose `replace` has two paragraphs inserts two paragraphs; every selection run behaves as before. *Not:* any conversation change.
  - **S2 — Place flags in scene conversations.** *Done when:* the route test runs the extraction turn against a mocked model (both kinds, entry resolution, retry, the transcript cut and the cue); component tests cover the button, the chat-side controller and the mixed review in a real editor; and in the browser, on a scratch project with the extraction answered by a canned reply, Place flags opens the scene on its Body with one edit and two notes in one review, Accept inserts the new paragraph, and Keep turns each note into a TODO. (The app has no chat end-to-end harness; its e2e suite is a smoke test.) With a real model, *Scene / doctor* on *The Water Line* (Anton's, after approval). *Not:* lore entry conversations, automatic placement, streaming, or a change to any prompt.
  - **S3 — the *Revising* layout.** *Done when:* the layout menu offers *Revising* beside the other built-ins, and applying it shows the outline, the editor with room for a scene and its conversation side by side, and TODOs. *Not:* any change to the user's saved presets.
  - **S4 — line edits look like diffs.** *Done when:* an edit that changes one word in a sentence marks only that word warm and shows only the new word, cool, beside it; a pure cut shows its words warm with nothing inserted; an insertion of new paragraphs shows them cool; Accept, Keep, Reject, the keys and the current item behave as before; and the diff reviews look exactly as they did. *Not:* notes, the diff reviews themselves, or a Current / Proposed / Both view.
