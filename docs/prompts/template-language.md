# Template language

A prompt's body markdown is rendered as a [Jinja2](https://jinja.palletsprojects.com/) template inside a sandbox. Jinja's standard syntax — variables, conditionals, loops, includes, filters — works as documented upstream. This page covers only the additions specific to this project.

## What rendering produces

A template doesn't produce a single string. It produces a list of role-tagged messages that the provider layer serializes into whatever shape Anthropic, OpenAI, or Ollama wants. The Python shape:

```python
RenderedTemplate
├── messages: list[RenderedMessage]
│   ├── role: str   # "system" | "user" | "assistant" (and rare custom values)
│   └── blocks: list[ContentBlock]
│       ├── text: str
│       └── cache_break_after: bool
└── warnings: list[str]
```

A message is built from one `{% role %}` block; a block within a message is a span of text bounded by `{% cache_break %}` markers.

## `{% role %}` — required wrapper for everything sent to the model

```jinja
{% role "system" %}
You are an expert thriller writer.
{% endrole %}

{% role "user" %}
Write a paragraph about the rain.
{% endrole %}
```

**Only text inside a role block is sent to the model.** Anything outside is dropped with a warning. This is deliberate: it forces authors to be explicit about which content belongs to which role.

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

## `{% cache_break %}` — split a message into cacheable blocks

```jinja
{% role "system" %}
You are a thriller writer.
{% include "snippet_house_style" %}
{% cache_break %}
{% endrole %}

{% role "user" %}
{{ relevant_lore(scene) }}
{% cache_break %}
Scene so far:
{{ text_before }}
{% endrole %}
```

Inside a role block, `{% cache_break %}` ends the current content block and starts a new one. The block before the marker carries `cache_break_after=True`. The provider serializer translates that into Anthropic `cache_control: { type: "ephemeral" }` markers; for OpenAI / Ollama it's a no-op.

**Up to four cache breakpoints** can be honored per request by Anthropic. Authors should spend them coarsely: system style + world canon + stable lore + (volatile lore + instruction). See [strategy_ai_integration](../README.md) for the recommended layering.

**Cache_break outside any role block** is a warning. It has no effect.

**A trailing cache_break** (the marker at the end of the role's body) marks the LAST block of that message for caching — equivalent to caching the whole message.

**Multiple cache_breaks in a row** produce empty content blocks. Don't do this.

## The sandbox

Templates render inside [`jinja2.sandbox.SandboxedEnvironment`](https://jinja.palletsprojects.com/en/latest/sandbox/). This:

- Forbids access to dunder attributes (`obj.__class__`, etc.) and most callable attributes on arbitrary Python objects
- Restricts operations on registered "unsafe" types (none registered by default)
- Allows the full set of standard Jinja filters and tests

**Undefined variables are strict.** A typo like `{{ scnee.summary }}` raises `UndefinedError` rather than rendering empty. This catches author errors early.

## Variables available

The dispatch pipeline populates the context. Common variables (the actual set will be documented per task type in M2.4+):

| Variable | Meaning |
| --- | --- |
| `scene` | The currently active scene node (`scene.title`, `scene.summary`, `scene.body`, …) |
| `project` | The current project's settings node (`project.tense`, `project.language`, `project.style_voice`) |
| `effective` | Resolved effective AI settings (`effective.model_class`, `effective.provider_policy`) |
| `input` | User-supplied inputs declared by the prompt entry (e.g., `input.words`) |

Helpers (callable functions like `text_before`, `relevant_lore`) are documented in [helpers.md](helpers.md). They land in M2.2.

## Warnings

Author errors that don't block rendering, returned on `RenderedTemplate.warnings`:

| Warning | Meaning |
| --- | --- |
| `Text outside any role block is ignored: '...'` | Non-whitespace text was found outside a `{% role %}` block. It is not sent to the model. |
| ``cache_break` outside a role block has no effect` | A `{% cache_break %}` was encountered between or before role blocks. |
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
Always write in {{ project.tense }} tense using {{ project.language }} spelling.
{% include "snippet_house_voice" %}
{% cache_break %}
{% endrole %}

{% role "user" %}
{{ relevant_lore(scene) }}
{% if scenes_before(scene) %}
The story so far:
{{ scenes_before(scene) }}
{% endif %}
{% cache_break %}
{% endrole %}

{% role "assistant" %}
{{ text_before }}
{% endrole %}

{% role "user" %}
Write {{ input.words }} words that continue the story:

{{ input.message }}
{% endrole %}
```

Three of those helpers (`relevant_lore`, `scenes_before`, `text_before`) land in M2.2; the include (`snippet_house_voice`) is a snippet node — see [snippets-and-prompts.md](snippets-and-prompts.md).

## Implementation reference

The engine lives in [`backend/app/services/ai/templates.py`](../../backend/app/services/ai/templates.py). The relevant entrypoints are `render_template(source, context)` (returns a `RenderedTemplate`) and `create_environment()` (returns the sandboxed env if you need to customize). Tests are in [`backend/tests/test_ai_templates.py`](../../backend/tests/test_ai_templates.py) and double as worked examples of every feature on this page.
