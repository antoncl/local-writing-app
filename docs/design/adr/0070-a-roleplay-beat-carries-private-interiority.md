# ADR-0070: A roleplay beat carries private interiority; a final stage projects the clean scene

- Status: **Accepted** — 2026-08-22 (Anton). Design complete; all open questions resolved (the reveal affordance settled by mockup). Only behavioural prompt-tuning is deferred to live testing. Implementation proceeds as vertical slices; nothing built yet. **Amendment 1 (accepted 2026-11-03)** brackets a beat with two markers and moves its interiority to the close marker (#2665).
- Issue: #844 (spun out of the roleplay intent-vs-impl review)
- Follows: ADR-0051 (a node owns its conversations — roleplay stays a scene-hosted prompt, **not** a node), ADR-0046 (an AI proposal is author-reviewable — author authority over AI writes), the character mark + comment-marker round-trip (`proseMarks.ts` / `markdown.ts`), and the Dynamics scene-direction field.
- **Non-goal of this ADR:** it decides the *model and its invariants*, not the generation/handler mechanism — those are listed as open questions and deferred to a first slice.

## Context

The intent-vs-impl review (#844) found the per-character **context reconstruction** already correct: `character_turns` faithfully rebuilds each character's alternating thread. What's missing is **per-character direction and interiority** — a way for a character to pursue an objective in a scene, and to hold subtext the reader never sees.

Three constraints shape the answer:

1. **Method-agnostic.** GMO is one dramaturgical method; objectives, want/need, a one-line intent, a secret are others. The app supplies a *place* for interiority, never imposes a *method*. (Like Dynamics: a free-text slot with a taught convention, not a schema.)
2. **The three-audience beat.** A beat is read by three parties with conflicting needs: the character themselves (wants their evolving inner life), the *other* characters (must NOT see it — `character_turns` feeds them each other's beats as `[Name]:` turns, so interiority in a shared beat leaks every character's inner life to everyone), and the reader (wants clean prose). One *visible* representation cannot serve all three.
3. **The scene body is the working record.** Roleplay is authored beat by beat in one document; the author needs to review what's happening and to rewind — delete a run of beats and regenerate. Whatever holds interiority must not desync from that record.

## Decision

**Each beat carries its character's private interiority in a hidden marker on the beat itself; `character_turns` keeps it private per character during the session; and a final cleanup stage projects the scene to clean, POV-correct prose.**

### 1. Interiority rides the beat, in a hidden marker

Generation delivers two parts — the **external** beat (visible dialogue/action) and the character's **internal** state (objective, subtext, reasoning). The external is stored exactly as a beat is today: visible text under a `data-character` mark. The internal rides **the same comment-marker round-trip**, as a self-contained hidden comment on that beat's span — present in the markdown body, rendered as nothing. **No separate field, no `{character → text}` channel** — interiority lives with the beat that produced it.

### 2. Live per-character privacy, in `character_turns`

Reconstruction already discriminates by character; it gains one rule: **include the focus character's own internals** (on their `assistant` turns) and **strip every other character's internal** (their `[Name]:` turns stay external-only). So a character maintains its own evolving subtext across its beats, and never sees anyone else's — no mid-session leak, no metagaming.

### 3. Two writers, edited in place

The internal channel has two writers: the **actor** writes it per beat (the model's inner state for that beat), and the **author** reviews and edits it in the editor (a reveal affordance on a beat), authoritatively — an author edit governs the next generation and is never silently overwritten (ADR-0046 author authority).

### 4. A final cleanup stage projects the clean scene

Once the scene is complete, an AI pass — reusing the extract/commit transform shape — projects the working record **in place** to **clean, POV-correct prose**: keep the focal character's interiority as legitimate narration, externalize or cut everyone else's (`scene.pov` drives the filter), and drop the internal markers. The projection is **destructive** (the scene *is* the record; there is no node to keep a rich copy), so a snapshot is taken first as the safety net. The messy working scene becomes the finished scene.

## Why the beat, not a separate channel

A separate per-character inner-state field was the first draft of this ADR. It was rejected because keeping interiority in the one ordered record buys two properties a side-channel can't:

- **Traceability.** Per-beat interiority, in document order, is reviewable — the author can trace each character's inner life against the beats that expressed it.
- **Clean rewind.** Deleting a run of beats rolls back the beats *and* their interiority together; regeneration continues from that point. A side-channel would desync on truncation, and would also need a new `{character → text}` field type the schema does not have.

## Invariants

- **No cross-character leak.** A character's invocation never receives another character's interiority (the reason it is marked and stripped, not shared).
- **Visible prose stays external.** The rendered beat shows only observable action/dialogue; interiority is a hidden marker.
- **One ordered record.** Beats and their interiority live together in the scene body, so review, trace, and rewind operate on a single source of truth.
- **Author edits are authoritative** over actor-written interiority.

## Anti-goals

- **Not a separate inner-state field/channel** — rejected above (loses traceability + clean rewind; needs a new field type).
- **Not GMO-enforced** — the internal is free text; GMO is a convention for filling it, never a schema.
- **Not a roleplay node** — the review/steer surface is the editor plus reconstruction; no new node kind (ADR-0051 stands).
- **Not "inline, unmarked, cleaned only at the end"** — leaving interiority unmarked in beats and relying solely on the cleanup pass would leak every character's inner life to the others *during* the session. Marking it (this ADR) is what buys live privacy; cleanup is the *final projection*, not the privacy mechanism.

## Resolved in review

1. **Two-part delivery follows the commit/revise pattern.** The `{external, internal}` split is produced the way the existing commit and revise prompts already yield structured output — no new generation mechanism is invented; the structured-output path is reused. (Byte-level details to the slice.)
2. **The reveal/edit affordance — one interiority glyph, per-beat plus a shell toggle** (settled by mockup, checked against `design-language.md`). Interiority is hidden by default; the reveal lives **on the beat**, co-located with the marker — the character underline grows a small handle that expands *that beat's* interiority inline to read and edit, and collapses it again. The **same glyph** is a **shell affordance** (like `⤢` zoom) at the editor's top-right, present **only while the scene holds roleplay**, a toggle that reveals/collapses all — quiet glyph when idle, gaining the name **"Interiority"** + an accent tint while showing (the guide's adaptive-stateful-selector rule). Two guide constraints bind this: a glyph *"means the same thing everywhere"* (so one mark, both places), and *compounds are banned* (so the keyboard shortcut lives in the tooltip, never as a `⌥I`-style label). **This ADR adds one interiority glyph to the affordance lexicon** — the sanctioned, by-PR path the "no ad-hoc glyphs" rule exists to channel (the rule guards against *uncontrolled* proliferation, not a considered addition) — as a single new entry meaning "a character's private inner state," used identically in both places. The mockup carries a working eye-mark; the exact glyph is a small visual call to lock at implementation (and to keep clear of `▤` "view"). A gutter-dot placement was weighed and set aside for the on-beat glyph's simplicity and touch-friendliness.
3. **Cleanup is destructive.** With no roleplay node to hold a separate rich record, the scene is the only home, so finalization projects the scene **in place** to clean POV-correct prose. A snapshot taken before finalization (0.8.0 snapshots) is the safety net.
4. **Marker shape** (author's call, decided): the interior is a hidden marker **bound to the beat's character span** — the same comment-marker round-trip as the character mark, carrying the internal text as marker *content* (not a cramped attribute), and **deleted atomically with the beat** so rewind stays clean. The exact encoding (nested vs. paired-with-atomic-delete) is a slice detail; the contract is: bound to the beat, self-contained, hidden, round-trips, dies with its beat.
5. **Cost is inherent and accepted.** A two-character scene is at least two per-character contexts plus a finalization pass; roleplay is knowingly an expensive feature.
6. **Prompt tuning expected.** Whether the actor sustains a *useful* self-authored interiority is behavioural; the prompt text will need iteration once live (as with the ADR-0051 S4 focus rewrite).


## The journey (why this shape)

A dedicated roleplay coordinating node was considered and rejected as YAGNI; roleplay stays a scene-hosted prompt. Per-character direction surfaced that a character's subtext can't ride in a *visible* beat without leaking to the others — the interiority-filtering problem the node would have owned. Three homes for interiority were weighed: a separate per-character channel (this ADR's own first draft), a hidden marker on the beat, and inline-unmarked-cleaned-at-the-end. The marker home won because it reuses the comment-marker round-trip, needs no new field type, and — decisively — keeps everything in one ordered record, so the author can trace each character's inner life and rewind the scene cleanly. Direction and subtext, which began as two features, are one channel with two writers; and the cleanup stage is where the "scene is a filtered projection of a richer record" idea, raised at the very start, finally lands.

## Amendment 1 — A beat is bracketed by two markers, and its interiority rides the close marker

**Accepted** 2026-11-03 (Anton); built in #2665. From Anton's first test of roleplay and its interiority on a real scene (#2665, #2666, #2669). It revisits Resolved-in-review 4 ("nested vs. paired-with-atomic-delete"), which the first slice answered with an attribute on the character mark. The invariants and the cleanup stage don't change.

### What prompted it

- **A beat had no identity of its own.** One `/roleplay` reply of four paragraphs was stored as four `character` spans, because a mark can't cross a paragraph break, and each span carried a full copy of the interiority. `character_turns` then gave the model the same inner monologue four times. The editor showed four eye handles, and an edit reached only the copy that was opened: Anton's test edit landed in one span and not the other three. Pressing Enter inside a beat does the same.
- **The interiority couldn't be edited safely.** It lived on the mark, so writing it back changed the mark, and ProseMirror redraws a changed mark together with the widgets beside it. Every save replaced the revealed textarea and the eye handle. No save moment was safe:
  - on a blur, a writing assistant's fix landed in a detached box;
  - on a press, the eye click was lost (#2649).
- **The interiority isn't proofread.** The revealed box is a plain textarea that the proofreading lens (ADR-0102) doesn't check. The cleanup stage (§4) can keep the focal character's interiority as narration, so its words can reach the reader.
- **A turn could see the future.** `character_turns` read the whole scene, so a turn inserted between two beats knew what came after it (#2669).

### Decision

1. **A beat is a pair of markers: an open marker and a close marker.** They are inline atoms in the prose, as mutation anchors are (ADR-0095), and a beat may span paragraphs. The open marker names the character, and the close marker carries the interiority, **stored once per beat**. The markdown keeps the existing comment-marker round-trip; the interiority moves from the opening comment to the closing one. The exact encoding is a slice detail. The contract: one beat is one pair, the interiority is stored once, it is hidden, it round-trips, and it dies with its beat.
2. **Who said what is drawn between the markers.** The coloured underline is a decoration over the range between a pair, not a mark on the text.
3. **Beats never nest.** All text between a pair belongs to that beat, including what the author types there and any paragraph breaks.
4. **The interiority is edited from the close marker, and an edit changes only that atom.** Its node view takes the new value without rebuilding its DOM, so the edit box stays live while it is open. A writing assistant's fix lands and stays, and the eye click works. Whether the box sits inline in the node view or in a popover anchored to the marker is a slice detail, with one requirement: **the proofreading lens checks the interiority, and its fixes apply there.** A popover hosting the long-text editor of ADR-0102 Amendment 3 meets that without new proofreading work.
5. **`/roleplay` is not offered inside a beat.** With the cursor between a pair, the slash menu shows `/roleplay` disabled, with the reason on its hint line ("Inside Elias's beat: move the cursor outside it, or split the beat"). The slash menu gains a disabled state for this.
6. **`/roleplay split` splits a beat at the cursor.** It is offered only inside a beat. It ends the beat with a new close marker and starts a new beat for the same character after it. Both halves get a copy of the interiority, and both are revealed, so the author trims each to its half. A beat never exists without an interiority, and the copy is made in plain view, on purpose.
7. **A turn knows nothing after its insertion point.** Everything a roleplay send reads from the scene body (the turn history, and anything else derived from the body) stops at the insertion point (#2669).
8. **A marker without its partner attributes nothing.** An open marker with no close, or a close with no open, is shown as broken in the editor and reported by validation (advisory, as for mutation anchors). Text is never silently reattributed. Deleting a beat's whole range removes both markers together. Deleting one marker alone leaves the other broken until the author fixes or removes it.
9. **Existing scenes migrate (ADR-0071).** Consecutive spans for the same character with identical interiority, separated only by paragraph breaks, merge into one beat. Spans whose interiority differs become separate beats, each keeping its own. The first case is the four-paragraph reply; the second is a copy the author already edited.

### Not changed

The invariants (no cross-character leak, visible prose stays external, one ordered record, author authority), the privacy rule in `character_turns`, the cleanup stage, and the reveal glyph and shell toggle of Resolved-in-review 2.
