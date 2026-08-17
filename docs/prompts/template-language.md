# Template language

A prompt's body markdown is rendered as a [Jinja2](https://jinja.palletsprojects.com/) template inside a sandbox. Jinja's standard syntax — variables, conditionals, loops, includes, filters — works as documented upstream. This page covers only the additions specific to this project. For the exhaustive list of variables, helpers, filters, and tags with their types, see [reference.md](reference.md).

## What rendering produces

A template doesn't produce a single string. It produces a list of role-tagged messages that the provider layer serializes into whatever shape Anthropic, OpenAI, or Ollama wants. The Python shape:

```python
RenderedTemplate
├── messages: list[RenderedMessage]
│   ├── role: str   # "system" | "user" | "assistant"
│   └── blocks: list[ContentBlock]
│       └── text: str
└── warnings: list[str]
```

A message is built from one `{% role %}` block (or from un-roled prose homed to the base type's default role). A content block is just text — the author never marks where caching happens; that ordering is the backend's job (see [Caching is a backend concern](#caching-is-a-backend-concern)).

## `{% role %}` — an override, not a required wrapper

```jinja
{% role "system" %}
You are an expert thriller writer.
{% endrole %}

{% role "user" %}
Write a paragraph about the rain.
{% endrole %}
```

**Un-roled prose is homed to the base type's default role** (usually `system`), so a prose-only prompt just works — you don't need to wrap anything. `{% role %}` is the **override** you reach for when a prompt needs more than one message: a system persona plus a user instruction, or an assistant turn carrying prior prose. Text is split across roles exactly as the blocks fall.

The role argument is an expression — usually a string literal, but `{% role pov_role %}` works if `pov_role` is in the context.

**Valid role names:** `system`, `user`, `assistant`. Other names render but emit a warning, in case a future provider needs custom roles.

**An empty role block** produces no message. This is convenient for conditionally including a message:

```jinja
{% role "assistant" %}
{% if previous_text %}{{ previous_text }}{% endif %}
{% endrole %}
```

If `previous_text` is empty, no assistant message is emitted.

**Nested roles** are an author error. The outer wrapper is discarded; inner roles still produce messages. A warning is appended.

## `{% include %}` — inline a snippet node

```jinja
{% role "system" %}
You are a thriller writer.
{% include "builtin-house-style" %}
{% endrole %}
```

Standard Jinja `{% include %}`, backed by a loader that resolves the name to a `prompt:snippet` node by id and inlines its rendered body. See [snippets-and-prompts.md](snippets-and-prompts.md) for how snippets are stored and inherited.

## Caching is a backend concern

The author never places cache breakpoints. Caching is a provider-neutral **volatility ordering** the backend produces: it lays stable content down first (persona, world canon, the lore it selected and tiered `stable`) and the per-call material last, then each provider adapter maps that ordering onto its own caching primitive — Anthropic `cache_control: { type: "ephemeral" }` markers where supported, a no-op for OpenAI / Ollama.

Because ordering is the backend's job, prose you want cached just needs to be stable prose: authored system content rides the stable system prefix automatically, and lore you select with `use(node)` is placed and tiered by the backend (with `use(node, "stable")` as an advisory hint). You write the meaning; the engine handles the byte-stability. See [reference.md](reference.md) and [preview.md](preview.md#the-cache-strip) — the preview shows the resulting tier-badged composition.

## The sandbox

Templates render inside [`jinja2.sandbox.SandboxedEnvironment`](https://jinja.palletsprojects.com/en/latest/sandbox/). This:

- Forbids access to dunder attributes (`obj.__class__`, etc.) and most callable attributes on arbitrary Python objects
- Restricts operations on registered "unsafe" types (none registered by default)
- Allows the full set of standard Jinja filters and tests

**Undefined variables are strict.** A typo like `{{ scnee.summary }}` raises `UndefinedError` rather than rendering empty. This catches author errors early.

## Variables available

The dispatch pipeline populates the context. See [reference.md](reference.md#variables) for the full table with types; the common ones:

| Variable | Meaning |
| --- | --- |
| `scene` | The prompt's scene node (`scene.title`, `scene.summary`, `scene.body`, …). Field access is uniform attribute access — `scene.pov.title` chases an entity-ref field — resolved as of this scene. |
| `project` | The project node. `project.<field>` reads an authored project field (`project.spelling`, `project.tense`, `project.measurement_system`, …). Each is resolved nearest-explicit-wins over the inheritance chain, so a value set on the universe reaches every book under it; a field no layer sets is absent, so guard with `{% if 'tense' in project.metadata %}` (`.metadata` is the explicit whole-map escape; a bare `{{ project.tense }}` raises `UndefinedError` when unset). |
| `inputs` | User-supplied inputs declared by the prompt entry (e.g., `inputs.words`). |
| `selection`, `text_before`, `text_after` | The editor selection and the body markdown around the cursor (strings; `""` when not dispatched from an editor). |

Helpers (callable functions like `use`, `story_so_far`, `pov`) and the `json` filter are documented in [helpers.md](helpers.md) and [reference.md](reference.md).

## Warnings

Author errors that don't block rendering, returned on `RenderedTemplate.warnings`:

| Warning | Meaning |
| --- | --- |
| `Unknown role 'foo'. Valid roles: ['assistant', 'system', 'user']` | The role argument is not one of the canonical names. The message is still emitted. |
| `Nested role block inside 'foo' is not supported; outer role discarded, inner roles preserved` | A role block contained another role block. The outer wrapper is dropped; inner roles produce messages. |

## Errors

Things that abort rendering by raising:

- `jinja2.UndefinedError` — referenced an undefined variable (typo, missing context)
- `jinja2.TemplateSyntaxError` — malformed Jinja syntax
- `jinja2.sandbox.SecurityError` — sandbox-forbidden access (e.g., dunder attribute, unsafe call)

These propagate up to the dispatch / preview layer and are reported to the user.

## Example: a minimal `continue_scene` template

```jinja
{% role "system" %}
You are an expert fiction writer.
{% if 'tense' in project.metadata %}Always write in {{ project.tense }} tense.{% endif %}
{% if 'spelling' in project.metadata %}Use {{ project.spelling }} spelling.{% endif %}
{% if 'measurement_system' in project.metadata %}Measurements are {{ project.measurement_system }}.{% endif %}
{% include "builtin-house-voice" %}
{{ use_lore() }}
{% endrole %}

{% role "user" %}
{% if story_so_far(scene) %}
The story so far:
{{ story_so_far(scene) }}
{% endif %}
{% endrole %}

{% role "assistant" %}
{{ text_before }}
{% endrole %}

{% role "user" %}
Write {{ inputs.words }} words that continue the story:

{{ inputs.message }}
{% endrole %}
```

`use_lore()` enables the scene's implicit lore — the backend selects, places, tiers, and caches it; the template emits nothing for it. `story_so_far` and `text_before` are documented in [helpers.md](helpers.md); the include (`builtin-house-voice`) is a snippet node — see [snippets-and-prompts.md](snippets-and-prompts.md).

## Implementation reference

The engine lives in [`backend/app/services/ai/templates.py`](../../backend/app/services/ai/templates.py). The relevant entrypoints are `render_template(source, context)` (returns a `RenderedTemplate`) and `create_environment()` (returns the sandboxed env if you need to customize). Tests are in [`backend/tests/test_ai_templates.py`](../../backend/tests/test_ai_templates.py) and double as worked examples of every feature on this page.
