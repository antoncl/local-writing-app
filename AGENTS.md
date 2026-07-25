# Project Guidance

This project is a private, local-first fiction writing application.

## Product Principles

- The app is standalone and local-first.
- The user's writing should live in ordinary project files, not a hosted platform.
- Files are the source of truth. Caches and indexes must be rebuildable.
- Privacy matters. Network calls for AI must be explicit and user-controlled.
- Keep scope incremental. Build thin vertical slices before broad systems.

## Vocabulary

- Use `Lore` for the collection of story information.
- Use `Entry` in the UI for each item in Lore.
- Use `LoreEntry` in code when a type name needs to be unambiguous.
- Use `Scene` as the atomic prose file.
- Use `Manuscript Structure` for acts, chapters, sequences, and scene ordering.

Avoid the term `Codex` for story information because it reads as derivative and now has OpenAI product baggage.

## Architecture

- Backend: Python/FastAPI local application service on `127.0.0.1:8787`.
- API style: REST-like HTTP, plus SSE streaming for AI responses.
- Frontend: TypeScript/Svelte 5 browser UI.
- Editor: WYSIWYG, TipTap/ProseMirror; CodeMirror for code/JSON bodies.
- Scene storage: Markdown files with YAML front matter.
- Structure storage: backend-owned structure files.
- Derived data: `.cache/`, never canonical, always rebuildable.

## Current Scope

Shipped and in daily use:

- Create/open local project folders, with a layered metadata schema merged
  from the projects base folder down to the open project.
- A manuscript tree of acts, chapters, and scenes, and a separate research tree.
- Create/read/save/delete scenes; Markdown storage; headings, bold, italic,
  tables, and more.
- Lore entries with entry types, tags, aliases, references, and backlinks,
  including mid-scene mutations and a mutation timeline.
- Views: a set-algebra query language authored in a node-graph designer, and
  the backing for every node list in the app.
- AI: Anthropic, OpenAI, OpenRouter, and Ollama providers; Jinja2 prompt
  entries with declared inputs; chat sessions as nodes; implicit context
  detection; per-call token and cost accounting.
- Project-level and scene-anchored TODOs; full-project search; an assistant
  roster; saveable pane layouts.

Out of scope:

- Word, PDF, or EPUB export.
- Hosted accounts or subscriptions.
- Collaboration and cloud sync.
- Semantic rename/global replace beyond basic search.

AI is off by default: a project's `ai_policy` starts at `off` and must be
raised to `local-only` or `cloud-allowed` deliberately. It resolves over the
declared layer chain — nearest layer that states one wins, none anywhere means
`off` — so a universe can raise it once for every book beneath it. Credentials live in
per-machine settings, never in the project folder.

## Engineering Notes

- Keep backend mutations intentful: save scene, create scene, move scene, create TODO.
- Do not let the frontend mutate project files directly.
- Use atomic writes for prose and structure files.
- Prefer small, readable modules over clever abstractions.
- Do not introduce a second canonical store for prose.
- The draggable pane prototype intentionally uses document-level mousemove/mouseup
  handlers and immediate DOM style updates, then mirrors values back into Svelte
  state. The earlier pointer-capture/state-only version looked right but did not
  move panes reliably in the local browser runtime; do not "simplify" this path
  without re-testing drag and resize in the actual app.
