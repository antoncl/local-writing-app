# ADR-0076: The chat chrome is quiet instrumentation around the conversation

- Status: **Draft** — proposed 2026-08-28. (#1558)
- Concern: the chat pane's chrome — everything `ChatBodyView` renders *around* the transcript: the composer strips, telemetry readouts, action row, and the prompt/assistant chips. Not the transcript, not the commit path, not the chat data model.
- Follows: ADR-0030 / [`docs/design/design-language.md`](../design-language.md) (normative — "a quiet writing desk": chrome never heavier than content; the closed glyph lexicon §4; the surface taxonomy §4; the caps-label recipe), ADR-0074 (the context picker's drill-in idiom, adopted here for the chips), ADR-0054/0046 (the commit action row is composed here but its behavior is untouched), ADR-0057 (the first-send lore gate rides the preview this ADR consolidates), ADR-0070 (the interiority eye — whose reservation decision 9 honors).
- Relates: #840 (prompt chip drill-down — becomes slice 5), #1477 (preview honesty — absorbed by slice 2), #10 (project-level cost tracking — the session line here is chat-local and does not pre-empt it), `InputsDialog.svelte`'s estimate-as-metadata-line, which is the idiom this ADR extends to chat.
- Review mockup: "Chat, Composed" — [`docs/design/mockups/0076-chat-composed.html`](../mockups/0076-chat-composed.html) (interactive; open in a browser. Not normative — the decisions below are).
- **Verified against `2f23533c` (2026-08-28).**

**The conversation is the content; everything between it and the composer is instrumentation, and instrumentation renders as quiet metadata — one line, no cards. One door answers "what will the AI see," per-turn facts live on the turn, destructive and irreversible acts confirm, a running send can be stopped, and the chips speak the app's one popover idiom.**

## Context — the pane is an instrument panel with a conversation trapped inside it

ChatBodyView is the one body view that never received its visual pass — its own header still lists "Body-spec visual pass (10-region layout)" as deferred (`ChatBodyView.svelte:14`). Each strip below earned its place in some past slice (#99, #1037, #1086…); they were never *composed*. Meanwhile the prompt system was reworked around it — the ADR-0074 picker, `InputsDialog`'s deliberate "no card, reads as metadata" estimate line, and `▶ Run` (#1433), which lands the writer **in chat**: the reworked flow currently ends on the un-reworked surface.

Verified deficiencies, in one sitting of dogfooding:

1. **Up to six sibling strips stack between the transcript and the composer** (`ChatBodyView.svelte:960-992`): the inputs strip, the journal-scope strip, the NEXT TURN EST. card, the CACHE TTL card (both bordered inset cards, `ChatEstimateStrip.svelte:57-63`), the provider·model·latency line (`:982`), and transient notices — plus a session-cost footer at the very bottom (`:1096-1100`). The composer, the most-used control on the surface, sits under the pile.
2. **Three doors answer "what will the AI see":** the 👁 preview popover (`ChatComposerBar.svelte:286-296`), the "Show inputs" collapse (`ChatInputsStrip.svelte:51-61`), and the estimate card's cache-block chips (`ChatEstimateStrip.svelte:32-38`) — which duplicate the block labels the preview popover already renders (`ChatComposerBar.svelte:319-326`). No hierarchy among the three, and the preview can show lore the send won't include (#1477).
3. **Per-turn facts render off the turn.** provider·model·latency describes the *last completed turn* but renders as a floating line above the composer, while the transcript already stamps each assistant turn with tokens/cache/cost (`ChatTranscript.svelte:81-89`).
4. **"Clear" is a landmine.** The plainest button in the action row, in line with Send (`ChatBodyView.svelte:1020`); it wipes the history and **persists immediately** — no confirm, no undo (`clearChat`, `:735-745`) — and, since the lock derives from history length (`isLocked`, `:867`), it silently *unlocks* the prompt, assistant, and inputs as a side effect.
5. **A running send cannot be stopped.** `streamAssistantReply` (`:529-587`) exposes no cancel; once Send fires, the only feedback is disabled buttons and "Sending…".
6. **The two cost readouts can disagree.** The transcript reads per-message `cost_usd`; the footer reads the session record's `cost_usd_total` (`:1096-1098`), which is updated by riding `cost_delta_usd` on the next persist (`:442`) — observed live: a €0.0071 message above a "Session cost: €0.00" footer.
7. **The chips are a second popover dialect.** Prompt and assistant chips open hand-rolled dropdown menus with their own search inputs and option rows (`ChatComposerBar.svelte:193-274`), beside the app's drill-in popover substrate (ADR-0074 / `NodePickerPopover`). #840 already asks for the prompt chip to adopt the drill-down.
8. **Pre-pass styling survives:** `font-weight: 800` — retired by the design language (§2, "800 is retired") — in the caps-labels of both `ChatEstimateStrip.svelte:68` and `ChatInputsStrip.svelte:106`.
9. **The chrome glyphs are emoji outside the closed lexicon** (design-language §4: affordances draw from the lexicon; it grows by PR, never ad hoc): ✨ on the prompt chip (`ChatComposerBar.svelte:185`), 🤖 on the assistant chip (`:231`), 🔒 as the lock mark (`:188`, `:234`), and 👁 on the preview control (`:296`) — where the emoji eye collides with the lexicon's *reserved* eye: the stroked-SVG interiority eye (ADR-0070) is explicitly "kept clear" of other meanings.

The lock itself is *correct* (the bound prompt and assistant repeat on every turn; a mid-conversation swap would make the transcript incoherent) and it already explains itself (chip tooltip, `ChatComposerBar.svelte:180`). What it lacks is a doorway: the explanation names the constraint but offers no path to what the writer actually wants — the same setup, fresh.

## Decision

1. **One metadata line, no cards.** The NEXT TURN EST. card, the CACHE TTL card, and the session-cost footer collapse into a single borderless metadata line directly above the composer, in `InputsDialog`'s idiom (`--fs-xs`, `--text-3`, no border, no inset): forward-looking estimate first (`~5.0k tok · €0.0037 · cache 57m`), session total last (`session €0.21`). The cache-block chips (`system 12`, `volatile lore 5.0k`) leave the line — they are the preview's block labels and live behind Preview (decision 2). Expired-TTL keeps its danger treatment on the cache term. The line renders nothing it doesn't know (no prompt bound → no estimate → the term is absent, mirroring today's `{#if estimate}`).

2. **Preview is the one door to "what will the AI see."** The preview popover shows, labeled: the system block(s), the attached context tiers with their token counts (absorbing the cache-block chips), and — once the chat is locked — the locked input values, read-only. Consequently the post-lock inputs strip and its "Show inputs" toggle are retired, and the journal-scope strip ("In context:") folds into the preview as well (the transcript already stamps per-turn `journal_added` chips; the strip duplicated them). **Pre-lock, the inputs strip stays** — it is the form the writer fills before the first send, not telemetry. The preview must be honest: what it shows is what the send assembles (#1477 is fixed in this slice, not worked around).

3. **Per-turn facts move onto the turn.** provider · model · latency joins the assistant turn's existing usage/cost meta line in the transcript. The floating `chatLastMeta` line above the composer is retired.

4. **Clear confirms, and names its consequences.** Clear remains available (wiping a chat node for reuse is a real operation) but becomes a confirmed action: the dialog states the message count, that the deletion persists immediately, and that the prompt, assistant, and inputs unlock. Danger styling, words not glyphs (design language: destructive stays words). In the action row it separates from Send — Clear left-anchored, flexible space, commit/Send right-anchored — so the two are never adjacent.

5. **Send becomes Stop while streaming.** Stopping aborts the stream and **keeps the partial assistant text**, stamped as stopped early (the truncation-banner idiom); usage/cost stamp with whatever the stream delivered before the abort, else the turn shows no usage line. The existing rewind path (#1037) is untouched and stays reserved for errors and empty replies — a deliberate user stop is not an error.

6. **One cost truth.** The session total shown in the metadata line is the persisted `cost_usd_total` plus any not-yet-persisted `pendingTurnCost` — the displayed number can never lag a cost the transcript already shows. (Chat-local display only; project-level cost tracking remains #10's.)

7. **The chips adopt the drill-in popover substrate (#840).** The prompt chip and assistant chip re-host their menus onto the shared popover idiom (search field + NodeRow-substrate rows; the assistant menu's "Suggested for this prompt" partition becomes group headers). Both are single-select pickers, so each opens straight into its one panel — the ADR-0074 single-axis short-circuit, no root menu, no back header. This is a widget-substrate adoption: what is listed and what picking does are unchanged.

8. **The lock gains a doorway.** Clicking a locked chip opens a small popover: the constraint in one line ("Locked after the first message — this prompt shapes every turn") and one action, **"New chat with this setup"**, which creates a fresh chat node seeded with the same prompt, assistant, and input drafts, and opens it. The lock's *semantics* are untouched — this changes what a locked chip offers, not what locking means.

9. **The chrome speaks the lexicon; the emoji retire.** The preview control takes a **word** ("Preview"), per the lexicon's own rule: no single agreed glyph exists for it, the eye is reserved for interiority (ADR-0070), and a worded `sm` button costs one small word in a strip that isn't crowded. The lock mark becomes a Tabler annotation (`ti-lock`, from the curated set — a state mark, so it belongs to the annotation vocabulary) and sits **trailing, in the caret's slot**: the same slot reads caret when the chip opens a picker and lock when it opens the doorway (decision 8) — one slot, two states, no layout shift. The ✨/🤖 chip role-markers likewise become leading Tabler annotations naming each chip's role (prompt / assistant) — the chips' *labels* keep following the adaptive-stateful-selector rule they already follow (the bound thing's name when assigned). The Clear confirm is a **dialog** (surface-taxonomy walk step 5: confirm destruction), worded, `danger` as a modifier.

Alongside, the visual pass this ADR constitutes: retired `font-weight: 800` → 600, the house caps-label recipe (`--fs-xs`/`--w-semibold`/0.07em/uppercase/`--text-3`), and the strips that survive (pre-lock inputs strip) restyled to the token layer.

## Why / rejected alternatives

- **Hide the telemetry entirely** (a "writers don't care about tokens" pane). Rejected — this app's writer does care (local-first, pay-per-call AI; the estimate strip exists because of it). The telemetry isn't wrong, it's *loud*. Quiet metadata keeps the information at a glance without the cards.
- **A details/inspector rail for telemetry.** Rejected — a whole surface for four data points, and it moves the estimate away from the Send button it informs. The metadata line keeps cause (Send) and consequence (cost) adjacent.
- **Merge forward-looking and backward-looking telemetry into one line.** Rejected — "what will this cost" (estimate) and "what did that cost" (last turn) answer different questions at different moments. The split is by tense: forward-looking above the composer, backward-looking on the turn it describes (decision 3).
- **Replace Clear with "New chat" outright.** Rejected — they serve different intents: New chat preserves the transcript and starts fresh (the common want, decision 8); Clear destroys the transcript to reuse the node (rare, legitimate, now confirmed). Removing Clear would push writers to delete-and-recreate nodes to get the same effect.
- **Stop rewinds the exchange** (symmetric with the error path). Rejected — a writer stops a reply because it's long enough or going wrong; the partial text is what they chose to keep. Rewind-on-stop would destroy it. Errors rewind; stops keep.
- **Unlock the chips mid-conversation** (the "obvious" fix for the lock's friction). Rejected — the lock holds a real invariant (the system prompt and persona repeat every turn; the transcript must stay coherent with them). The friction is the missing doorway, not the lock.
- **A tabbed preview popover** (Preview | Inputs | Journal). Rejected — three tabs to answer one question re-creates the three-door problem inside the popover. One scrollable, labeled document: system, context tiers, inputs, journal.

## Anti-goals

- **The transcript is not redesigned.** Bubbles, the thinking accordion, truncation banners, per-turn journal chips stay as they are — decision 3 *adds* provenance to the existing turn meta line, nothing else moves.
- **No behavior change to the commit path** (Propose new entry / Commit to entry / Stage as pending change) — the action row is re-composed around those buttons; ADR-0046/0054/0055 semantics are untouched.
- **The lock's semantics are untouched** — locked means locked; decision 8 changes its affordance only.
- **No new telemetry** — this ADR re-homes what exists; it adds no new readouts.
- **Not the model/assistant *editor*** — the assistant chip picks; editing stays in the Assistants pane.
- **No project-level cost aggregation** — that is #10; the session line stays chat-local.
- **No retry/regenerate feature** — Stop is not a regenerate affordance; that would be its own design.

## User journey (definition of done)

A writer hits `▶ Run` on a runnable prompt. Chat opens: chips, transcript space, the inputs form, one quiet line — `~5.0k tok · €0.0037 · cache 1h · session €0.00` — and the composer. They press Preview and read exactly what will be sent: system block, two context tiers with counts, their filled inputs. They send; Send becomes Stop. The reply runs long — they press Stop; the partial reply stays, marked stopped early, and the metadata line's session total already includes its cost. The turn's meta line reads `1.2k → 480 tok · 38% cached · €0.0071 · anthropic · haiku-4.5 · 9.6s`. The chips now show 🔒; clicking one offers "New chat with this setup" — they take it next morning and are composing again in one click, inputs pre-filled. Weeks later they clean up: Clear asks "Delete 14 messages? This persists immediately and unlocks the prompt and inputs." They confirm; the node is fresh. At no point did a card, a second cost number, or an unstoppable stream interrupt the writing.

## Consequences and slices

One storage change in this ADR, additive (S1 amendment): decision 3 persists per-turn provenance as three optional `ChatSessionMessage` fields (`provider`/`model`/`latency_ms`) so it survives reload alongside the usage/cost it renders with — additive-optional, no migration (the ADR-0074 precedent; older messages simply lack them). Every other decision is presentation and control flow; `ChatSession` itself, drafts, and cost deltas are untouched.

- **S1 — the quiet line** (decisions 1, 3, 6, + the 800→600/token restyle). *Not:* no popover work, no chips work, no change to what the estimate fetch computes.
- **S2 — one door** (decision 2 + the preview control's word treatment from decision 9; fixes #1477). *Not:* the pre-lock inputs form does not move into the popover; no tabs.
- **S3 — safe hands** (decisions 4, 5: Clear confirm-dialog + Stop). *Not:* no undo system, no regenerate, no rewind-path changes.
- **S4 — the doorway** (decision 8). *Not:* no unlock, no mid-chat prompt swapping; "same setup" copies prompt/assistant/input drafts only — not history.
- **S5 — one popover idiom** (decision 7 + the chips' Tabler role/lock marks from decision 9; closes #840). *Not:* no tri-state, no multi-select, no change to which prompts/assistants are listed or to pick semantics.

S1–S3 are independent of each other; S4 and S5 both touch `ChatComposerBar` and sequence after each other (either order). Each slice lands as its own PR against its own filed issue, per the house workflow.
