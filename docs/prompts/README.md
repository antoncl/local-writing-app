# Prompts and AI — developer pages

Contributor-facing notes on the AI integration: the HTTP endpoints, the template
engine, and how helpers are built. Prompt *authors* want the two bundled guides
instead — they are what the app shows in its help pane.

## What's here

**For prompt authors** (bundled in the app):

| Page | Covers |
| --- | --- |
| [Writing prompts](guide.md) | A progressive introduction: roles, reading the story, inputs, choosing what the AI sees, snippets. |
| [Prompt reference](reference.md) | Every variable, helper, filter and tag, at a glance and in detail. Gate-checked against the code (`scripts/check_prompt_vocab_docs.py`). |

**For contributors:**

| Page | Covers |
| --- | --- |
| [Snippets and prompts](snippets-and-prompts.md) | The `prompt` node kind, its entry types, input types, inheritance across nested projects. |
| [Template engine](template-language.md) | The sandboxed Jinja environment, the `{% role %}` marker stream, the snippet loader, what a render returns. |
| [Helpers](helpers.md) | How helpers are registered, the `EntryRef` wrapper, and how to add a helper. |
| [Preview](preview.md) | `POST /api/ai/preview` — render without calling a model; the cache strip. |
| [Generate](generate.md) | `POST /api/ai/generate` (+ `/stream`) — render a template and call the model. |
| [Chat](chat.md) | `POST /api/ai/chat` (+ `/stream`) — a chat turn; AI policy; the streaming line protocol. |

Request and response **fields** are not copied into these pages — they drift. The
running backend serves FastAPI's generated schema: the interactive docs at
`http://127.0.0.1:8787/docs` and the raw schema at `/openapi.json`. The models
behind it are in [`backend/app/models/ai.py`](../../backend/app/models/ai.py).

## Mental model

The writer **subscribes** to a **provider** (Anthropic, OpenAI, OpenRouter, or a
local Ollama) and **hires an assistant** — an `assistant` node naming a provider,
model, temperature and output budget. Assistants are layered like prompts and lore,
with a per-machine base layer so a roster follows the user across projects. Each
run, the assistant gets a **role** (who to be — the system content), a **task**
(the prompt), and the **data** (what the template selects plus what the app adds).

A call's parameters resolve **request override → the named assistant (or the
default one) → the legacy `default_provider` / `default_models` machine
settings** (`services/ai/call_resolver.py`). An unset `max_tokens` falls to the
resolver's default — 32768, or 8192 for Ollama, where it also sizes the context
window — clamped to the model's own output ceiling.

## Design principles

1. **Don't bomb the context window.** Lore inclusion is retrieval, not a dump. A
   template only *selects* nodes — `use(node)` names one, `auto_lore()` turns on
   the scene's implicit lore — and the backend does the retrieval, dedup,
   budgeting, placement and caching. A selection prints nothing.
2. **Stable prefix, dynamic suffix.** The backend orders what it sends by
   volatility — settled content first, per-call material last — so editing one
   lore entry doesn't invalidate the prefix above it. Authors never place cache
   breakpoints; each provider adapter maps the ordering onto its own caching
   (`docs/design/context-caching.md`).
3. **Local-first.** Every provider runs through the same pipeline. Ollama is
   first-class; caching is used where a provider supports it and is a no-op
   elsewhere.

The user-facing account of what a send carries is [What the AI sees](../ai-context.md).
