# Prompts and AI

This is the technical reference for the local-writing-app's AI integration: how prompts are stored, how their templates are rendered, and what helper functions are available inside them.

> **Start with the typed surface.** [reference.md](reference.md) is the completion
> contract for the prompt language: every variable, helper, filter, and tag with
> its declared type or shape. The pages here explain the model; that page is the
> lookup table.

## Mental model

The writer **subscribes** to a **provider** (Anthropic, OpenAI, OpenRouter, or a local Ollama). Through that subscription they **hire an assistant** — a saved configuration of a specific model with its own temperature and output budget. The assistant is then told three things, every time it runs:

- a **role** — who to be (the system prompt / persona)
- a **task** — what to do (the prompt entry, defined as a sub-type of `prompt`)
- the **data** — what to look at (the context envelope: scenes, lore, snippets, helpers)

Most of the surface in this folder concerns the last two. The subscription lives in machine settings as API keys + endpoint. **Assistants** also live in machine settings — a user-defined roster `(name, provider, model, temperature, max_tokens)` with one marked default. The role lives on the prompt sub-type; the task *is* the sub-type; the data is everything assembled by the template + helpers + context picker.

When an AI endpoint runs, the resolution order is: explicit overrides on the request → the named assistant (or the default) → the legacy `default_provider` + `default_models` fallback. So a chat request can carry just `{messages: [...]}` and get the default assistant's settings, or `{assistant_id: "cheap-summary", ...}` to pick one specifically, or `{model: "claude-opus-4-8", ...}` to override on top of an assistant.

This is the user-facing framing — internal docs still use the technical terms (provider, model, system prompt, context strategy) so be ready to translate.

## What's here

| Page | Covers |
| --- | --- |
| [Reference](reference.md) | The typed surface — every variable, helper, filter, and tag with its type/shape. The completion contract. |
| [Snippets and prompts](snippets-and-prompts.md) | The `prompt` node kind and its entry types (invocable prompts vs. import-only snippets), input types, inheritance across nested projects |
| [Template language](template-language.md) | Jinja2 sandbox + the custom `{% role %}` tag, and how a rendered template becomes role-tagged messages |
| [Helpers](helpers.md) | Reference for every function callable from a prompt template (`text_before`, `use`, `pov`, …) |

## Design principles

The AI integration was scoped to fix two specific complaints with Novelcrafter:

1. **Don't bomb the context window.** Lore inclusion is a retrieval problem, not a "dump everything" pass. The reference graph is the retrieval index. A template only *selects* nodes — `use(node)` picks one, `use_lore()` enables the scene's implicit lore — and the backend does the retrieval, dedup, placement, and caching. The template emits nothing for a selection.
2. **Stable prefix, dynamic suffix.** The backend orders the envelope by volatility — rarely-changing content first, per-call material last — so iterative edits to one lore entry don't invalidate the stable prefix above it. Authors never place cache breakpoints; the ordering is provider-neutral and each adapter maps it to its own caching primitive.
3. **Local-first.** Every provider runs through the same envelope. Ollama is a first-class provider; Anthropic's prompt caching is exploited where supported and treated as a no-op elsewhere.

See the [strategy memory file](../../README.md) (private to the project for now) for the full discussion.

## Roles: system, user, and assistant

A model doesn't read one blob of text — a chat API takes an ordered list of **messages**, each tagged with a **role**. `{% role "…" %}…{% endrole %}` (see [template-language.md](template-language.md)) marks which message a chunk of your template belongs to.

Most of the time you don't write it. Un-roled prose is **homed to the base type's default role** (usually `system`), so a plain instruction paragraph just works. Reach for `{% role %}` only when a prompt is **more than one message** — a multi-turn exchange, or an instruction plus an example dialogue.

The three roles, and when each is for:

- **`system`** — the standing setup: who the model is, the rules it follows, the world facts and lore it should honor. It frames the *whole* conversation and the model treats it as authoritative context, not as something to answer. This is the "role/persona" from the mental model above, plus the selected data — and it is the most stable content, so it caches (below).
- **`user`** — the human's turn: the request, the selected prose, the material to work on. This is what the model responds *to*.
- **`assistant`** — the model's own turns: earlier replies in a continued conversation, or example outputs you supply to show the shape you want (some providers also let an `assistant` block *prefill* the start of the response).

A single-message prompt is all `system` (the default). A back-and-forth — like the Roleplay prompt reconstructing a scene with `character_turns` — alternates `user` and `assistant`.

## Caching

A long prompt — persona, world rules, the lore in scope — is mostly the **same bytes every turn**. **Prompt caching** lets a provider recognize a repeated prefix and charge a fraction for it (on Anthropic a cache *read* is ≈0.1× a fresh write) instead of re-billing the whole thing. Over a chat that re-sends the same setup each turn, that is most of the cost saved.

**You never place caches.** The backend orders the prompt **stable content first, volatile content last** — the system prompt and settled lore lead; new-or-changed lore and the latest turn trail — so editing one lore entry doesn't invalidate the stable prefix above it. Each provider maps that ordering to its own caching: Anthropic gets breakpoints with a 1-hour lifetime on the stable tier and 5 minutes on the volatile tier; OpenAI caches the stable prefix automatically; Ollama ignores it. Nothing about caching appears in your template — it is a provider-neutral volatility ordering, not an author control.

To make caching work for you:

- **Put stable content in the `system` role** — persona, world rules, style. It caches for an hour and is reused across turns.
- **Select lore with `use()` / `use_lore()`; don't paste it.** The backend places it in the right tier and keeps a settled entry as a cheap cache read; a freshly-edited one re-writes just that turn, then re-settles.
- **The one lever, when you know the churn:** `use(node, "stable")` starts a node in the cached tier from turn one (e.g. a roleplay's POV character, fixed for the whole chat); `use(node, "volatile")` pins one you're actively editing to the cheap-rewrite tier. It is advisory — a `"stable"`-hinted node that actually changes still re-writes, so you never see stale text.
- **Watch it in the preview.** The [preview](preview.md#the-cache-strip)'s cache strip shows the send-path composition, each block badged `stable` / `volatile` — so you can see what will be reused and what will re-send before you spend a token.

## Audience

These pages are for prompt authors: the technical user writing or customizing prompt templates. They are not tutorials for end users; the slash menu surfaces prompts under friendlier labels.
