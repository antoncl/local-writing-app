# Prompts and AI

This is the technical reference for the local-writing-app's AI integration: how prompts are stored, how their templates are rendered, and what helper functions are available inside them.

> **Status:** in progress. The architecture is described in this folder; individual features ship over milestones M1–M6 (see [strategy_ai_integration](https://github.com/antoncl/local-writing-app) in the project memory).

## Mental model

The writer **subscribes** to a **provider** (Anthropic, OpenAI, OpenRouter, or a local Ollama). Through that subscription they **hire an assistant** — a specific model. The assistant is then told three things, every time it runs:

- a **role** — who to be (the system prompt / persona)
- a **task** — what to do (the prompt entry, defined as a sub-type of `prompt`)
- the **data** — what to look at (the context envelope: scenes, lore, snippets, helpers)

Most of the surface in this folder concerns the last two. The subscription and the assistant live in machine settings; the role lives on the prompt sub-type; the task *is* the sub-type; the data is everything assembled by the template + helpers + context picker.

This is the user-facing framing — internal docs still use the technical terms (provider, model, system prompt, context strategy) so be ready to translate.

## What's here

| Page | Covers | Stable? |
| --- | --- | --- |
| [Snippets and prompts](snippets-and-prompts.md) | The `snippet` and `prompt` node kinds — what they are, file layout, inheritance across nested projects | Yes (M2.0) |
| [Template language](template-language.md) | Jinja2 sandbox + the two custom directives (`{% role %}`, `{% cache_break %}`) | Stub — fills in at M2.1 |
| [Helpers](helpers.md) | Reference for every function callable from a prompt template (`text_before`, `relevant_lore`, `pov`, …) | Stub — fills in at M2.2 |

## Design principles

The AI integration was scoped to fix two specific complaints with Novelcrafter:

1. **Don't bomb the context window.** Lore inclusion is a retrieval problem, not a "dump everything" pass. The reference graph is the retrieval index. Helpers like `relevant_lore(scene)` walk it.
2. **Stable prefix, dynamic suffix.** The envelope is ordered so that cache breakpoints can sit between rarely-changing and per-call-changing material. Iterative edits to one lore entry don't invalidate the prefix above it.
3. **Local-first.** Every provider runs through the same envelope. Ollama is a first-class provider; Anthropic's prompt caching is exploited where supported and treated as a no-op elsewhere.

See the [strategy memory file](../../README.md) (private to the project for now) for the full discussion.

## Audience

These pages are for prompt authors: the technical user writing or customizing prompt templates. They are not tutorials for end users; the slash menu surfaces prompts under friendlier labels.
