# Helpers

Functions callable from a prompt template. All are registered as globals on the sandboxed Jinja2 environment by `register_helpers(env, project_service)`; users cannot define new helpers (security boundary).

There are two flavors:

- **Pure helpers** (`last_words`) need no project state. Always available.
- **Project-bound helpers** (`pov`, `scenes_before`, `relevant_lore`) need to look up nodes, walk the reference graph, or read prior scenes. They are bound to a specific project at env-construction time.

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
{{ last_words(scene.previous.body_markdown, 650) }}
{% endif %}
```

**Caveats**: split is on any whitespace (including newlines); no smart sentence-boundary handling. For "trailing N sentences" you'd write a different helper.

## `pov(scene)`

Returns the POV character entity for a scene, resolved through lore.

**Signature**
```python
pov(scene) -> dict | None
```

**Returns**: `None` if the scene has no `pov` metadata field set, or a dict with:

- `id` — lore entry ID, or `None` if the field was a raw string
- `title` — character name (or the raw string if the ref didn't resolve)
- `aliases` — list of alias strings from the lore entry

Templates can access these with attribute or item notation: `{{ pov(scene).title }}` and `{{ pov(scene)['title'] }}` are equivalent.

**Example**
```jinja
{% if pov(scene) %}
POV: {{ pov(scene).title }} (also known as: {{ pov(scene).aliases | join(", ") }})
{% endif %}
```

**Caveats**:

- The seeded `pov` field on the `scene` entry type is an `entity_ref` targeting characters. A `pov` field with a different type (e.g., `text`) is still read but won't resolve through lore — the returned dict will have `id: None`.
- If the metadata holds a list of refs, only the first is returned.

## `scenes_before(scene)`

Returns an XML-wrapped listing of every scene that appears before `scene` in manuscript order.

**Signature**
```python
scenes_before(scene) -> str
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
{% if scenes_before(scene) %}
The story so far:
{{ scenes_before(scene) }}
{% endif %}
```

**Caveats**:

- **Scope is the entire project** for now. Once nested-project support lands (a Honorverse → series → book layout), the scope narrows to the current book. Don't include this helper in a prompt that's supposed to span multiple books — that case will need a different helper (`scenes_before_series(scene)` or similar).
- Only scenes with a non-empty `summary` metadata field contribute. Empty-summary scenes are skipped silently.
- The walk is depth-first through `manuscript.structure.yaml`. Containers (acts, chapters) contribute their own summaries if they have one; otherwise they're invisible structural nodes.

## `relevant_lore(scene, mode="implicit", partition="all")`

Returns an XML block of lore entries the model should know about for this scene. Each entry uses its `entry_type` as the tag name. [Anthropic specifically recommends XML tags](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/use-xml-tags) for delimiting structure in prompts; the format helps the model locate entities unambiguously.

**Output shape**:
```xml
<lore>
<character name="Honor Harrington" aliases="The Salamander">
Captain of the Fearless. Treecat-adopted.
</character>

<character name="Nimitz">
Honor's treecat companion.
</character>

<place name="Manticore" aliases="Star Kingdom">
A binary star system; the capital world of the Star Kingdom.
</place>
</lore>
```

The entry's body is XML-escaped (so `Captain & Crew` becomes `Captain &amp; Crew`); markdown structure within the body is preserved as-is. Aliases are comma-joined into a single attribute. An entry with no body or summary renders as a self-closing tag (`<character name="..." />`).

**Signature**
```python
relevant_lore(scene, mode: str = "implicit", partition: str = "all") -> str
```

**Modes** (what lore is in scope):

| Mode | What's included |
| --- | --- |
| `"implicit"` (default) | Union of: (a) lore directly referenced by the scene's entity_ref / entity_ref_list metadata; (b) lore whose title or any alias appears in the scene's `summary` field as a whole word; (c) one-hop expansion through the entries found by (a) + (b). |
| `"explicit"` | Only (a) — lore directly referenced via entity_ref fields. No alias scan, no graph walk. |
| `"pinned_only"` | Empty for now. Pinning UI ships in M4. |

**Partitions** (which of the in-scope lore is returned, only meaningful when a session is bound — see [Sessions](#sessions)):

| Partition | What's included |
| --- | --- |
| `"all"` (default) | Every in-scope entry, regardless of session baseline. |
| `"stable"` | Entries whose `revision` matches the session baseline (unchanged since the prior call). |
| `"volatile"` | Entries that are new or changed since the prior call. |

**Returns**: a string. Sorted by lore ID for stable ordering — important for cache coherence; see [strategy_ai_integration](README.md).

**Example — partition-aware**
```jinja
{% role "user" %}
{{ relevant_lore(scene, "implicit", "stable") }}
{% cache_break %}
{{ relevant_lore(scene, "implicit", "volatile") }}
Scene so far:
{{ text_before }}
{% endrole %}
```

This is the canonical pattern for cache-coherent assembly: stable lore above the cache_break, volatile below. On the second call in a session, the stable block is byte-identical and hits Anthropic's prompt cache.

**Caveats**:

- Alias matching is **case-insensitive** and **whole-word**. Multi-word names (like "Star Kingdom") are matched as a substring with word boundaries. This catches normal prose mentions but won't match if the prose mangles capitalization across word boundaries (e.g., `starkingdom`).
- The one-hop expansion only walks lore→lore references via fields whose values look like lore IDs. It does not follow scene references back into other scenes.
- Stable ordering by ID is important: changing order between calls invalidates the cache breakpoint. The helper sorts internally; don't sort the output yourself in templates.
- The scope, like `scenes_before`, is the entire project for now and narrows to the current book under nesting.
- Calling `relevant_lore` twice in a render (e.g., for stable + volatile) re-resolves the relevant set both times. Cheap for now; a future pass may cache it within a single render.

## Sessions

A session lets `relevant_lore`'s `stable` / `volatile` partition distinguish entries that have been seen unchanged from entries that are new or have been edited since the prior call. It's the engine's answer to the cache-coherence objection in the [strategy doc](README.md).

### Lifecycle

```python
from app.services.ai.sessions import AISession
from app.services.ai.helpers import create_environment_for_project
from app.services.ai.templates import render_template

session = AISession(id="scene_xxxxx")           # caller-supplied ID
env = create_environment_for_project(svc, session=session)
out = render_template(source, context=ctx, env=env)
session.commit()                                 # promote touched → baseline
```

Every entry that `relevant_lore` returns (in any partition) is **snapshotted** into `session.touched` automatically. Calling `session.commit()` at the end of a successful render promotes touched to baseline. The next call partitions against that baseline.

### First-call behavior

The first call has an empty baseline, so **every entry is volatile**. After commit, the second call sees the same set as stable. The cache builds up naturally — you don't need to special-case the first call.

### Without a session

If `create_environment_for_project` is called without a session, the partition parameter on `relevant_lore` is ignored — all calls behave like `partition="all"`. This is the right default for testing and for one-shot prompts where caching isn't useful.

### Session keying

Sessions are keyed by a string ID the caller supplies. The typical choice is the scene_id of the current target: opening a scene starts a new session keyed by that scene; reopening the same scene resumes the same session. The dispatch endpoint (M2.4) will manage this; the engine just provides the machinery.

### `AISessionRegistry`

A process-wide registry exists at `app.services.ai.sessions.default_registry`. It's a simple `dict[str, AISession]` with `get_or_create(id)`, `get(id)`, `drop(id)`, and `clear()`. No expiry yet — the dispatch layer will own the expiry policy when it lands.

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
