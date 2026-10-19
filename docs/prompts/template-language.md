# Template engine

How a prompt body becomes role-tagged messages. This page covers the engine's
internals. What an author can write — every variable, helper, filter and tag — is in
[reference.md](reference.md), and the author's introduction is [guide.md](guide.md).

## The environment

A prompt body is a [Jinja2](https://jinja.palletsprojects.com/) template rendered
in a `SandboxedEnvironment` (`create_environment()`, `services/ai/templates.py`):

- **`StrictUndefined`** — a typo like `{{ scnee.title }}` raises instead of rendering
  empty.
- **`autoescape=False`**, `trim_blocks=True`, `lstrip_blocks=True` — a statement on
  its own line leaves no blank line behind.
- **Extensions:** the custom `{% role %}` tag (`RoleExtension`) and Jinja's
  `jinja2.ext.do`. `{% do … %}` is the form for the helpers that work by side effect
  (`{% do use(node) %}`, `{% do field_contract.store(f) %}`).
- The sandbox forbids dunder access and unsafe calls. Users can't register their
  own helpers or filters. The vocabulary is fixed in code (see [helpers.md](helpers.md)).

`create_environment_for_project()` (`services/ai/helpers.py`) is what the render
paths use. It builds that environment, installs the snippet loader, and calls
`register_helpers()`. Environments are built per render, so per-render state (the
`use()` picks, the `auto_lore()` flag, the field contract) lives on the environment
and never leaks between renders.

## Roles: a marker stream

`{% role "user" %}…{% endrole %}` doesn't build a message directly. It wraps its
body in control-character markers (`ROLE_START` / `ROLE_END`, starting with `\x00`),
and the template renders to **one string**. `_parse_marker_stream()` then splits
that string into messages. That is why a helper can emit its own role boundaries:
`character_turns()` returns text already wrapped in role markers, which the parser
splits like any `{% role %}` block. It must therefore be called outside a
`{% role %}` block. Because `autoescape` is off, the markers pass through untouched.

- **Text outside any role block** becomes a message of the caller's `default_role`.
  The send and preview paths always pass `system`, so a prose-only prompt is one
  system message. With no default role (`None`), loose text is dropped with a
  warning.
- The role argument is an expression, usually a string literal.
- An **empty** role block produces no message, so a conditional turn needs no
  special handling.

### Warnings

Author mistakes that don't stop the render are collected on
`RenderedTemplate.warnings`:

| Warning | Meaning |
| --- | --- |
| `Unknown role 'x'. Valid roles: [...]` | Not `system` / `user` / `assistant`. The message is still emitted. |
| `Nested role block inside 'x' is not supported; …` | A role block inside another. The outer wrapper is dropped; the inner blocks still become messages. |
| `Text outside any role block is ignored: …` | Loose text with no default role. The send paths never trigger this. |
| `Malformed role marker…` / `… missing end marker…` | The marker stream is corrupt. Rendering stops there. |

### Errors

Rendering raises Jinja's own errors — `UndefinedError`, `TemplateSyntaxError`,
`SecurityError` — plus the loader's error for an unresolvable include and the
`stop()` helper's error. `build_preview` turns each into a `PreviewError` with a
coarse `kind` (`undefined`, `syntax`, `include`, `stopped`, `scene_not_found`,
`other`). [Preview](preview.md#errors-are-data) returns these as data, and
[generate](generate.md#errors) as HTTP errors.

## `{% include %}` — the snippet loader

`PromptSnippetLoader` (`services/ai/snippet_loader.py`) resolves an include name to
a `prompt:snippet` node, and Jinja inlines its body:

1. A name that is a snippet's **id** resolves to that snippet.
2. Otherwise the name is matched against snippet **titles** (the shipped prompts
   include by title). Among the matches, the one in the **nearest layer** wins, so a
   project's own snippet overrides an inherited or built-in one with the same title.
3. Two matches with the same title in that nearest layer are **ambiguous**. Like no
   match at all, that is an `include` error naming the snippet.

An included snippet also contributes its declared inputs to the prompt's effective
inputs (ADR-0061, see [preview.md § Effective inputs](preview.md#effective-inputs)).
How snippets are stored and inherited is in
[snippets-and-prompts.md](snippets-and-prompts.md).

## What a render returns

```python
render_template(source, context=None, *, env=None, default_role=None) -> RenderedTemplate
```

`RenderedTemplate.messages` is a list of `RenderedMessage(role, blocks)`, where each
block is a `ContentBlock(text)`. A block carries no cache flag, because the author
never places caches. `warnings` is described above.

The rest of `RenderedTemplate` is **execution state copied off the environment** by
`build_preview` after the render, plus the send-path lore it computes from that
state:

- what the template *did*: `lore_invoked` (`auto_lore()` ran), `lore_free`
  (`no_lore()` ran), `lore_position` (`lore_as_of()`), `used_node_ids`,
  `used_node_hints` and `used_snapshots` (`use()`), `field_contract_stored`;
- what the backend will place: the `send_lore_*` fields — each tier's text, member
  ids, per-entry XML and snapshot elements — and `send_lore_fit`, the lore
  budget's report.

A chat persists the execution state, so later turns place the same lore without
re-rendering. The preview and generate routes turn the `send_lore_*` fields into
the cache strip and the one-shot system blocks.

## Caching is not in the template

The author never marks cache breakpoints (the old `{% cache_break %}` tag is
retired, ADR-0060 §5). The backend orders what it sends by volatility — system
prefix, stable lore, volatile lore, then the turns — and each provider adapter maps
that order onto its own caching: Anthropic cache-control markers, OpenAI's automatic
prefix cache, and nothing for Ollama. See `docs/design/context-caching.md` and
[preview.md § The cache strip](preview.md#the-cache-strip).

## Implementation reference

- Engine: [`backend/app/services/ai/templates.py`](../../backend/app/services/ai/templates.py) — `create_environment`, `render_template`, `RoleExtension`
- Snippet loader: [`backend/app/services/ai/snippet_loader.py`](../../backend/app/services/ai/snippet_loader.py)
- Render orchestration: [`backend/app/services/ai/preview.py`](../../backend/app/services/ai/preview.py) — `build_preview`
- Tests: `backend/tests/test_ai_templates.py` — they double as worked examples of every rule above
