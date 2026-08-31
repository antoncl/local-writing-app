# Roleplay — Howto

Have two (or more) characters take turns in a single scene. Each `/roleplay <Name>` invocation generates that character's next beat, in voice, with their own conversation history reconstructed from the scene body. The author writes narration between beats; the AI plays the characters.

## What it gives you

- A built-in **Roleplay** prompt, ready to invoke as `/roleplay <Character>` — it ships with the app; there is nothing to create.
- A per-scene **Dynamics** field for the author's beat notes (motivations, tensions, blocking), read verbatim as direction.
- Coloured underlining in the editor on every accepted beat, so you can see at a glance who said what.
- Per-character thread reconstruction at send time: Bob's invocations see Bob's beats as `assistant` turns, everyone else's as `user` turns prefixed `[Alice]: …`, narration as plain user text. Each character's persona forms a stable prefix the backend caches, so Bob's cache stays warm even as Alice's turns interleave.

## The built-in prompt

Roleplay is the built-in **Roleplay** prompt, an app-owned **Library** entry (a `prompt:general` node). It is read-only in place — to change the model, the framing, or how the persona is assembled, **clone it** and edit the copy (the built-in is your starting template, not a fixed behaviour). Its one input is a required, single-pick `character` of type `context_pick` targeting lore characters.

## Set up your characters (one time per character)

Roleplay reads the character's lore entry to seed their persona:

- **Title** — used for the picker, the `/roleplay <Title>` lookup (resolves by exact, case-insensitive title), and the `[Name]:` prefix when this character appears as a `user` turn in another character's thread.
- **Body (markdown)** — the persistent persona / arc / voice. The whole body is dropped into the system prompt of every invocation for this character. Keep it focused; long bodies cost cache space.

Optional but recommended: write the character's **arc** in the body too — what they want across the work, what they fear, how they sound. This is what gives the AI a stable centre across many turns.

## Optional: scene dynamics

Scenes carry a **Dynamics** long-text field alongside Summary / Status / POV. Put per-scene beat notes here:

```
Bob: wants the confession out of her. Will not raise his voice.
Alice: needs to deflect without lying outright. Touches her sleeve when stalling.
Shared: the bar's last call in 15 minutes — pressure rises.
```

Every character sees the whole Dynamics block on every invocation — mirror what skilled actors do: read the whole scene, not just your own beats. If you leave Dynamics empty, the prompt still works; the AI just has less framing.

## Invoke it

1. Put the cursor on a blank line in the scene body.
2. Type `/roleplay Bob` (or `/rol` then Tab to autocomplete, then the name).
3. If the name resolves to exactly one character, the generation fires immediately. If ambiguous or unresolved, an inputs dialog opens so you can pick.
4. The AI proposes Bob's next beat as a tracked suggestion. **Accept** wraps it in a `data-character` mark and a coloured underline; **Retry** regenerates; **Discard** removes it.
5. Write narration between beats. Type `/roleplay Alice` for the next turn.

Slash conveniences:
- `/roleplay` (no name) → the inputs dialog, to pick the character.
- `/rol` + Tab → expands to `/roleplay ` so you can keep typing.
- `/roleplay Annie Oakley` → an unquoted multi-word name resolves fine (the character slot absorbs the trailing words).
- `/roleplay "Honor Harrington"` → quotes also work, and are handy to disambiguate.
- `/roleplay Nobody` (unresolved) → the dialog opens with the field cleared and a red error naming the failed token.

## How marks behave in the editor

- Each character beat gets a 2px coloured underline plus a faint wash, its colour derived from the character's lore id (same id → same colour), set as `--character-color` on the span.
- Marks are `inclusive: false` — typing at the boundary of Bob's beat does NOT extend the mark over your narration. Editing inside the beat keeps the mark; deleting it removes the mark.
- Marks round-trip through markdown as HTML comment markers: `<!-- character:id=lore_abc -->text<!-- /character -->`. Safe inside tables, lists, and code fences — comment markers survive every markdown parser.

## How the thread is reconstructed (send-time)

When `/roleplay Bob` fires, the backend walks the scene body and produces an alternating chat thread for Bob:

| Span in scene body | Becomes |
|---|---|
| Tagged with Bob's id | `assistant` turn |
| Tagged with another character's id (e.g. Alice) | `user` turn, prefixed `[Alice]: ` |
| Untagged (your narration) | `user` turn, no prefix |
| No markers anywhere (first invocation) | Whole body as one `user` narration message |
| Scene ends on Bob's own beat | Synthetic `user` "Continue as Bob." appended, so the chat API has a turn to respond to |

The reconstruction also coalesces consecutive same-role messages and drops whitespace-only turns, so the model sees a clean user/assistant/user alternation regardless of how beats interleave with narration.

This is the `character_turns(scene, character)` Jinja helper, called at the bottom of the Roleplay body **outside** any `{% role %}` block (it emits its own role-tagged content). A minimal roleplay-flavoured body looks like:

```jinja
{% set char = entry(inputs.character) %}
{% role "system" %}
You are playing {{ char.title }}.
{{ char.body }}
{% endrole %}

{% role "user" %}
{% if scene.metadata.dynamics %}## Scene dynamics
{{ scene.metadata.dynamics }}{% endif %}
{{ use_lore() }}
{% if story_so_far(scene) %}## The story so far
{{ story_so_far(scene) }}{% endif %}
{% endrole %}

{{ character_turns(scene, inputs.character) }}
```

`use_lore()` flips the lore gate — the backend places the relevant lore itself, tiered stable/volatile for caching. `story_so_far(scene)` supplies the preceding-scenes narrative context.

## Caching

You don't manage caching in the template. The per-character persona (the system block) is a stable prefix, and the backend places lore tiered stable/volatile, so the cacheable prefix stays intact as beats accumulate. Bob's reconstructed thread only changes when spans *before his last own beat* mutate; Alice's interleaved turns extend the tail but leave Bob's cached prefix intact, so Bob's invocations after Alice's are cache hits on the persona + setup. Same for Alice.

## Inputs reference

The `character` input on the Roleplay prompt:

| Field | Value |
|---|---|
| `name` | `character` (matches the template's `inputs.character`) |
| `type` | `context_pick` |
| `target.sources` | `[{ kind: lore, expr: { type: lore:character } }]` |
| `target.multiple` | `false` (single-pick — one focus character per invocation) |
| `required` | `true` |

If you clone the prompt and change this, the template's `entry(inputs.character)` still works as long as the value resolves to a single lore entry.

## Caveats

- **Title collisions in lore** break name resolution. `/roleplay Bob` fires directly only when exactly one character has that exact title; two "Bob"s fall back to the inputs dialog for you to pick.
- **Multi-character (3+) scenes work**, just slower to cache — every additional character adds another stable persona to cache. Two-character battles are the sweet spot.
- **The colour is the only who-said-what cue** on a span today; there is no hover tooltip yet.
