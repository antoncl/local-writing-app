# Helpers

Functions callable from a prompt template. All are registered as globals on the sandboxed Jinja2 environment by `register_helpers(env, project_service)`; users cannot define new helpers (security boundary). For the one-line-per-entry roster with types, see [reference.md](reference.md#helpers).

There are two flavors:

- **Pure helpers** (`last_words`) need no project state. Always available.
- **Project-bound helpers** (`pov`, `story_so_far`, `use`) need to look up nodes, walk the reference graph, or read prior scenes. They are bound to a specific project at env-construction time.

Everything is resolved **as of the prompt's one scene** (ADR-0012): `scene.pov.title`, `entry(x)`, `story_so_far(scene)` all read the values effective at that scene. A scene-less prompt reads book-start values.

Two values that look like helpers but are actually template **variables**, populated by the dispatch layer per call:

- `text_before` — body markdown before the cursor in the current scene (string)
- `text_after` — body markdown after the cursor (string)

These are not callable; use them like any other context var: `{{ text_before }}`.

## `last_words(text, n)`

Returns the trailing `n` words of a string.

**Signature**
```python
last_words(text: str, n: int) -> str
```

**Returns**: a string. The whole text if it has ≤ n words. Empty if text is empty/whitespace, n ≤ 0, or n is not a valid integer.

**Example**
```jinja
{% if is_start_of_text and pov(scene) == pov(scene.previous) %}
{{ last_words(scene.previous.body, 650) }}
{% endif %}
```

**Caveats**: split is on any whitespace (including newlines); no smart sentence-boundary handling. For "trailing N sentences" you'd write a different helper.

## `pov(scene)`

Returns the POV character entity for a scene, resolved through lore.

**Signature**
```python
pov(scene) -> EntryRef | None
```

**Returns**: `None` when the scene has no `pov` lore reference, otherwise an [EntryRef](#entryref) for the linked character.

**Example**
```jinja
{% if pov(scene) %}
POV: {{ pov(scene).title }} (also known as: {{ pov(scene).aliases | join(", ") }})
{% endif %}
```

**Caveats**:

- The seeded `pov` field on the `scene` entry type is an `entity_ref` targeting characters. A `pov` field with free-form text (no lore id) returns `None`; read `scene.metadata.pov` directly if you need the raw string.
- If the metadata holds a list of refs, only the first is returned.

## `entry(x, at=scene, position=n)` and `original(x)`

Resolve a node into an [EntryRef](#entryref) you can walk. `entry(x)` returns the node **as of the prompt's scene** — the values effective at that point in the story; `original(x)` returns the same node at **book-start**, ignoring every mutation. Useful when you have the raw id (or a picked ref) of an entry and want to walk into its fields without writing the lookup by hand.

**Signature**
```python
entry(value, at=<scene>, position=None) -> EntryRef | None
original(value) -> EntryRef | None
```

- `at=` overrides the resolution scene — `entry(x, at=other_scene)` reads `x` as of a different anchor; `at=None` forces book-start (so `entry(x, at=None) == original(x)`). In a scene-less prompt `entry(x) == original(x)` already.
- `position=` is an optional within-scene cursor for mid-scene mutation resolution.

**Returns**: an EntryRef for the resolved id, or `None` when the input is empty / unrecognized. The EntryRef itself is lazy — it doesn't touch disk until you read a non-id attribute.

**Accepted shapes**:

- A string id: `entry("lore_abc123")`.
- An existing EntryRef (returned unchanged).
- Any object with an `.id` attribute.
- A `dict` with an `id` key (e.g. a single ContextPickRef).
- A `list` of any of the above — the **first** element wins.
- A JSON-string of a list (the form a `context_pick` input takes when rendered into a template). Auto-parsed; the first picked ref is used.

The last two shapes mean `entry(inputs.character)` works directly when `character` is a `context_pick` input (whether single- or multi-pick).

**Example**
```jinja
{% set honor = entry(scene.pov) %}
{{ honor.title }} lives on {{ honor.home_place.title }}.

{# Or against a context_pick input — first picked ref wins #}
{% set bob = entry(inputs.character) %}
You are playing {{ bob.title }}.

{# Book-start value, ignoring mid-story mutations #}
{{ original(honor).title }} started the book as a {{ original(honor).rank }}.
```

## `character_turns(scene, character)`

Reconstruct a per-character chat thread from a scene body's character markers (the `<!-- character:id=X -->…<!-- /character -->` spans the Roleplay flow writes on Accept). Emits its own role-tagged content using the same markers the `{% role %}` extension produces, so the renderer splits the output into multiple alternating chat messages.

**Must be used OUTSIDE any `{% role %}` block** — it owns its role boundaries.

**Signature**
```python
character_turns(scene, character) -> str
```

- `scene` — the target scene (an EntryRef or anything exposing `.body`). The helper reads `.body` directly.
- `character` — the focus character whose turn is being generated. Accepts the same shapes `entry()` does: a bare id, an EntryRef, a ContextPickRef dict, a list, or a JSON-string list. In practice you pass `inputs.<your_character_pick_name>`.

**Mapping** (each segment of the body becomes a message):

| Span in body | Becomes |
| --- | --- |
| Tagged with the focus character's id | `assistant` turn |
| Tagged with another character's id | `user` turn prefixed `[Name]:` (titles resolved via lore lookup; falls back to the id if unresolved) |
| Untagged narration | `user` turn, no prefix |
| No markers anywhere (first invocation) | Whole body as one `user`-narration message |
| Scene ends on the focus character's own span | Synthetic `user` "Continue as <Name>." appended so the chat API has a turn to respond to |

Consecutive same-role segments are coalesced into one message, and empty messages are dropped at payload-assembly time, so the LLM always sees a clean user/assistant/user alternation regardless of how spans interleave with narration.

**Example** (the Roleplay default body, abridged):
```jinja
{% set char = entry(inputs.character) %}
{% role "system" %}
You are playing {{ char.title }}.
{{ char.body }}
{% endrole %}

{% role "user" %}
{% if scene.dynamics %}
## Dynamics
{{ scene.dynamics }}
{% endif %}
{{ use_lore() }}
{% if story_so_far(scene) %}
## The story so far
{{ story_so_far(scene) }}
{% endif %}
{% endrole %}

{# Per-character thread takes over below. Outside the role block. #}
{{ character_turns(scene, inputs.character) }}
```

**Caveats**:

- The helper emits raw control-character markers (`ROLE_START`, `ROLE_END`). The template environment is `autoescape=False`, so they pass through verbatim and get re-parsed. Don't manually `e()` or `Markup()` the result.
- Nesting `character_turns` inside a `{% role %}` block triggers the renderer's "nested role" warning and drops the outer wrapper — keep it outside.
- See [`docs/roleplay.md`](../roleplay.md) for the user-facing howto on Roleplay prompts and the marker scheme.

## EntryRef

A lazy wrapper around a single entry returned by `pov(scene)`, `entry(...)`, and any auto-resolved `entity_ref` / `entity_ref_list` field inside another EntryRef's metadata. Templates read it like a normal object; the underlying entry is loaded on demand through the layered node index, so ancestor-layer entries (lore from the universe or series) just work.

| Attribute | Returns |
| --- | --- |
| `.id` / `.raw_id` | The string id without resolving. Always available, even if the target doesn't exist. |
| `.title` | The entry's title. Falls back to `.id` when the entry is missing. |
| `.entry_type` | The entry's `entry_type` (e.g. `character`, `place`). |
| `.body` | The entry's markdown body. |
| `.found` | `True` when the id resolves through the index, `False` otherwise. Useful for `{% if ref.found %}` guards. |
| `.metadata.<field>` | The metadata value for that field. `entity_ref` fields auto-resolve to a child EntryRef; `entity_ref_list` fields resolve to a list of EntryRef. Other fields pass through as their raw value. |
| `.<field>` | Shortcut for `.metadata.<field>`. Lets you write `honor.home_place` instead of `honor.metadata.home_place`. |
| `str(ref)` | The title (or raw id) — so `{{ honor }}` works directly. |

**Auto-resolve and the depth limit**: each `entity_ref` hop produces a child EntryRef carrying a `depth` counter. After 6 hops the EntryRef refuses to load and `.title` falls back to the raw id. This is a defensive ceiling for unbounded link cycles; hand-written chains stay nowhere near it.

**Example — chasing a ref graph**
```jinja
{% if pov(scene) %}
POV: {{ pov(scene).title }}
Home: {{ pov(scene).home_place.title }}
{% for friend in pov(scene).related_entries %}
- {{ friend.title }} ({{ friend.entry_type }})
{% endfor %}
{% endif %}
```

## `full_outline()`

Returns the manuscript structure as a list of nested outline nodes — useful when a prompt needs to brief the model on the whole book's shape rather than just one scene's context.

**Signature**
```python
full_outline() -> list[OutlineNode]
```

**Node shape** (attribute access; templates write `node.title` etc.):

- `.title` — node title
- `.summary` — `summary` metadata of the linked scene, if any
- `.entry_type` — the structure node's type (`act`, `chapter`, `scene`)
- `.scene_id` — id of the linked scene, or `None` for containers without one
- `.children` — list of OutlineNode, recursive

**Example**
```jinja
{% for top in full_outline() %}
# {{ top.title }}
{% for child in top.children %}
- {{ child.title }} — {{ child.summary }}
{% endfor %}
{% endfor %}
```

**Caveats**: walks `manuscript.structure.yaml` depth-first. Containers without summary metadata still appear with `.summary == ""`. For a flat scene list with bodies (not summaries), use `full_text()`.

## `full_text()`

Returns every scene's prose in manuscript order. Heavy — sized for templates that want the whole book in context.

**Signature**
```python
full_text() -> list[SceneText]
```

**Scene shape**:

- `.title` — scene title
- `.body` — full markdown body
- `.scene_id` — id
- `.entry_type` — the scene's `entry_type`

**Example**
```jinja
{% for s in full_text() %}
## {{ s.title }}

{{ s.body }}

{% endfor %}
```

**Caveats**: skips structure nodes that don't link to a scene (acts, chapters with no body). For an outline-only view use `full_outline()`.

## `story_so_far(scene)`

Returns an XML-wrapped recap of every scene that appears before `scene` in manuscript order (scenes 1 → n-1, reading order). A derived, per-scene-deterministic block: it is **emitted** (not selected), and because it is deterministic for a given scene it rides the stable prefix and caches there.

**Signature**
```python
story_so_far(scene) -> str
```

**Returns**: a string. Output shape:
```xml
<story_so_far>
<scene title="The Departure">
Honor takes the Salamander into battle.
</scene>

<scene title="The Briefing">
The crew receives their orders.
</scene>
</story_so_far>
```
Empty string if there are no prior scenes (which produces no message if the surrounding `{% role %}` block has no other content).

**Example**
```jinja
{% if story_so_far(scene) %}
The story so far:
{{ story_so_far(scene) }}
{% endif %}
```

**Caveats**:

- **Scope is the current book.** Under a nested layout (a Honorverse → series → book folder chain) the recap is the book's own scenes, not the whole universe.
- Only scenes with a non-empty `summary` metadata field contribute. Empty-summary scenes are skipped silently.
- The walk is depth-first through `manuscript.structure.yaml`. Containers (acts, chapters) contribute their own summaries if they have one; otherwise they're invisible structural nodes.

## `use(node, "stable"|"volatile")` and `use_lore()`

These **select** context; they do not emit it. The template's job is to name what the model should know about — `use(node)` picks one specific node, `use_lore()` enables the scene's implicit lore (the reference-graph retrieval). The backend then does the work: it selects, dedups, places, tiers, and caches the chosen nodes. **Both return an empty string** — nothing lands in the template output where you call them.

**Signature**
```python
use(node, hint: str | None = None) -> str   # "" — selection side-effect only
use_lore() -> str                            # "" — enables implicit lore for the scene
```

- `node` accepts an id, an EntryRef, or a picked ref — reach for `use(inputs.character)` to force a specific picked node into context. Handed a **multi-select** `context_pick` (a list), `use()` selects **every** pick, so `use(inputs.places)` pulls them all in one call; this is where it parts ways with `entry()`, which takes only the first of a list. (The explicit `{% for p in inputs.places %}{{ use(p) }}{% endfor %}` loop is equivalent and lets you hint each pick differently.)
- The optional `hint` is `"stable"` or `"volatile"` — an **advisory** cache-tier prior. It nudges where the backend orders the node in the volatility sequence; correctness (a changed node cannot be served as stable) always wins over the hint.
- `use_lore()` is the gate for the scene's *implicit* lore: the union of lore the scene references directly, lore whose name appears in the scene summary, and a one-hop expansion. Calling it turns that retrieval on; leaving it out means no implicit lore is pulled.

**Example**
```jinja
{% role "user" %}
{{ use_lore() }}
{{ use(inputs.pinned_place, "stable") }}
Scene so far:
{{ text_before }}
{% endrole %}
```

Nothing above renders lore text into the message — the `use_lore()` / `use(...)` calls emit `""`. The backend places the selected lore into the send-path envelope, tiered by volatility, and the [preview](preview.md) shows exactly where it lands and how it is badged.

**Why selection instead of emission?** The template no longer decides placement or caching. That removes the old cache-coherence footwork — there is no author-managed stable/volatile split, no cache breakpoint to spend, and no double-resolution of a "relevant set." One deterministic ordering, owned by the backend, feeds every provider.

### Resolving lore as of a different scene

Mid-scene lore mutations (#33) resolve against the prompt's scene by default — `scene.pov.rank`, `entry(x)`, and the lore that `use_lore()` selects all show their effective value at that point. To resolve against a *different* anchor, pass `at=` to `entry`:

```jinja
{# A roleplay prompt with a `scene_ref` input named `as_of`: #}
Your rank as of this point: {{ entry(inputs.character, at=inputs.as_of or scene).rank }}
```

A `scene_ref` value injects **no content** — it is only the resolution setting (ADR-0012). With no anchor at all (`entry(x, at=None)`, or a scene-less general chat) resolution falls to **book-start** via `original(x)`.

## Caching and tiering are not the author's job

There is no author-facing session or stable/volatile split in the template language. A prompt **selects** nodes with `use()` / `use_lore()`; the backend orders the whole envelope by volatility (stable content first), tiers each selected node, and maps that ordering onto each provider's caching primitive. The template author writes meaning, not placement — see [Caching is a backend concern](template-language.md#caching-is-a-backend-concern) and the [preview's cache strip](preview.md#the-cache-strip), which shows the resulting `stable` / `volatile` badging.

## Adding a new helper

When you add a helper, in the same change:

1. Add the function to `backend/app/services/ai/helpers.py`.
2. Register it in `register_helpers()` (project-bound) or expose it as a module attribute (pure).
3. Add tests in `backend/tests/test_ai_helpers.py`.
4. Add a section here following the pattern: signature, returns, example, caveats.
5. If the helper grows complex enough to need its own page, split it out into `helper-<name>.md` and link from this index.

## Implementation reference

- Module: [`backend/app/services/ai/helpers.py`](../../backend/app/services/ai/helpers.py)
- Tests: [`backend/tests/test_ai_helpers.py`](../../backend/tests/test_ai_helpers.py)
- Template engine that calls them: [template-language.md](template-language.md)
