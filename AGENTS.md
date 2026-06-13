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

- Backend: Python local application service.
- API style: REST-like HTTP plus streaming later for AI/events.
- Frontend: TypeScript browser UI.
- Editor: WYSIWYG, currently TipTap/ProseMirror.
- Scene storage: Markdown files with YAML front matter.
- Structure storage: a backend-owned structure file.
- Derived data: SQLite/cache later, never canonical.

## Current Scope

Current prototype scope:

- Create/open a local project folder.
- Read/write a manuscript structure.
- Create/read/save/delete scenes.
- Edit one scene at a time.
- Support headings, bold, italic, and tables.
- Store scenes as Markdown.
- Maintain project-level and scene-level TODOs.
- Support basic search.

Out of scope for now:

- Word, PDF, or EPUB export.
- Hosted accounts or subscriptions.
- Collaboration.
- Full Markdown support.
- AI provider integration.
- Semantic rename/global replace beyond basic search.

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
