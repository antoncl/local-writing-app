# Roleplay — Howto

Have two (or more) characters take turns in a single scene. Each `/roleplay <Name>` invocation generates that character's next beat, in voice, with their own conversation history reconstructed from the scene body. The author writes narration between beats; the AI plays the characters.

## What it gives you

- A `roleplay` prompt sub-type (inherits Continuation) ready to invoke as `/roleplay <CharacterName>`.
- A per-scene **Dynamics** field for the author's beat notes (motivations, tensions, blocking).
- Coloured underlining in the editor on every accepted span so you can see at a glance who said what.
- Per-character thread reconstruction at send time: Bob's invocations see Bob's lines as `assistant` turns, everyone else's as `user` turns prefixed `[Alice]: …`, narration as plain user text. Each character has a stable cached system prompt, so Bob's cache stays warm even as Alice's turns interleave.

## Set up a Roleplay prompt (one time)

1. Open **Prompts** in the top bar. Under **Continuation**, click **+ Entry** next to **Roleplay**.
2. The new prompt arrives pre-seeded with:
   - **Body**: a Jinja starter that uses the per-character thread helper. You can edit it freely later.
   - **Inputs**: a `character` input of type `context_pick` targeting lore characters. Required, single-pick.
3. Give the prompt a memorable title (e.g. "Roleplay"). The CLI matches on the entry-type, so the title can be anything — but a short title makes the prompts pane easier to scan.

That's it for setup. You can create more Roleplay prompts later (different personas, different writing styles, different model) — each one is independent.

## Set up your characters (one time per character)

Roleplay reads the character's lore entry to seed their persona:

- **Title** — used for the picker, the CLI lookup (`/roleplay Bob` resolves by exact case-insensitive title), and the `[Name]:` prefix when this character appears as a `user` turn in another character's thread.
- **Body (markdown)** — the persistent persona / arc / voice. The whole body is dropped into the system prompt of every invocation for this character. Keep it focused; long bodies eat cache space.

Optional but recommended: write the character's **arc** here too — what they want across the work, what they fear, how they sound. This is what gives the AI a stable centre across many turns.

## Optional: scene dynamics

Scenes now have a **Dynamics** long-text field next to Summary/Status/POV. Put per-scene beat notes here:

```
Bob: wants the confession out of her. Will not raise his voice.
Alice: needs to deflect without lying outright. Touches her sleeve when stalling.
Shared: the bar's last call in 15 minutes — pressure rises.
```

Both characters see the whole Dynamics block on every invocation. Mirror what skilled actors do — they read the whole scene, not just their own beats.

If you leave Dynamics empty, the prompt still works; the AI just has less framing.

## Invoke it

1. Put the cursor on a blank line in the scene body.
2. Type `/roleplay Bob` (or `/rol` then Tab to autocomplete, then the name).
3. If the name resolves to exactly one character, the generation fires immediately. If ambiguous or unresolved, an inputs dialog opens so you can pick.
4. The AI proposes Bob's next beat as a tracked suggestion. **Accept** wraps the new text in a `data-character="<bob's lore id>"` mark and a coloured underline. **Revert** discards.
5. Write narration between beats. Type `/roleplay Alice` for the next turn.

Slash CLI conveniences:
- `/roleplay` (no name) → inputs dialog with whatever character was last picked.
- `/rol` + Tab → expands to `/roleplay ` so you can keep typing.
- `/roleplay "Honor Harrington"` → quoted strings preserve spaces.
- `/roleplay Nobody` (unresolved) → dialog opens with the field cleared and a red error naming the failed token.

## How marks behave in the editor

- Each character span gets a 2px coloured underline, derived from a stable hash of their lore id (same id always → same colour). An explicit colour field on the lore entry can override this later — there's a TODO marker in [DocumentEditorPane.svelte](../frontend/src/DocumentEditorPane.svelte) and [styles.css](../frontend/src/styles.css) where that lookup will land.
- Marks are `inclusive: false` — typing at the boundary of Bob's span does NOT extend the mark over your narration. Editing inside the span keeps the mark; deleting the span removes it.
- Marks round-trip through markdown as HTML comment markers: `<!-- character:id=lore_abc -->text<!-- /character -->`. Safe inside tables, lists, code fences — comment markers survive every markdown parser.

## How the thread is reconstructed (send-time)

When `/roleplay Bob` fires, the backend walks the scene body and produces an alternating chat thread for Bob:

| Span in scene body | Becomes |
|---|---|
| Tagged with Bob's id | `assistant` turn |
| Tagged with another character's id (e.g. Alice) | `user` turn, prefixed `[Alice]: ` |
| Untagged (your narration) | `user` turn, no prefix |
| No markers anywhere (first invocation) | Whole body as one `user` narration message |
| Scene ends on Bob's own span | Synthetic `user` "Continue as Bob." appended so the chat API has a turn to respond to |

The renderer also coalesces consecutive same-role messages and drops whitespace-only turns, so the LLM sees a clean user/assistant/user alternation regardless of how spans interleave with narration.

This happens automatically in the `character_thread(scene, character)` Jinja helper at the bottom of the Roleplay default body. If you write your own roleplay-flavoured prompt, call the helper outside any `{% role %}` block — it emits its own role-tagged content. Example skeleton:

```jinja
{% set char = entry(input.character) %}
{% role "system" %}
You are playing {{ char.title }}.
{{ char.body }}
{% endrole %}

{% role "user" %}
{% if scene.metadata.dynamics %}## Dynamics
{{ scene.metadata.dynamics }}{% endif %}
{% endrole %}

{{ character_thread(scene, input.character) }}
```

## Cache identity

The system prompt is stable per character (persona + arc). The setup user block is stable per scene (dynamics, lore, scenes-before). The `{% cache_break %}` between them lets the provider cache that prefix with a 1h TTL.

Bob's reconstructed thread only changes when spans *before his last own turn* mutate. Alice's interleaved turns extend the tail of Bob's thread but leave the cached prefix intact — so Bob's invocations after Alice's are cache hits on the system + setup. Same for Alice.

The persistent per-scene cost chip in the editor footer rolls up everything for the current scene. Per-character cost breakdown waits on the upcoming `cost` computed field; for now, switch characters and watch the chip.

## Inputs reference

The `character` input on a Roleplay prompt:

| Field | Value |
|---|---|
| `name` | `character` (must match what the template references: `input.character`) |
| `type` | `context_pick` |
| `target.kinds` | `["lore"]` |
| `target.entry_types` | `{"lore": ["character"]}` |
| `target.multiple` | `false` (single-pick — only one focus character per invocation) |
| `required` | `true` |

This is the shape `default_inputs` seeds onto fresh Roleplay prompts. If you change it, the template's `entry(input.character)` call still works as long as the value resolves to a single lore entry.

## Caveats

- **Pre-existing roleplay prompts use the OLD body.** `default_body` only runs at prompt creation. If you have a Roleplay prompt from before the helper landed and want the new template, copy the seed body from a freshly-created Roleplay prompt or from [project_service.py](../backend/app/services/project_service.py) (`DEFAULT_METADATA_SCHEMA["entry_types"]["roleplay"]["default_body"]`).
- **Roleplay sub-types of roleplay** (e.g. you create your own `gritty_roleplay` with `parent: "roleplay"`) inherit `default_body` and `default_inputs` automatically; both are in the schema resolver's inheritable list.
- **Title collisions in lore** break CLI resolution. `/roleplay Bob` matches only when exactly one character lore entry has that exact title. Two characters both named "Bob" → dialog falls back, user picks.
- **Multi-character (3+) scenes work**, just slower to cache — every additional character adds another stable system prompt to cache. Two-character battles are the sweet spot.
- **The character mark doesn't yet show a tooltip** for who the underlined span belongs to. The colour is the only cue at the moment. Hover-tooltip with the character's title is a small follow-up.
