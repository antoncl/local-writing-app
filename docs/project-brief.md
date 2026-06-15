# Local Writing App Project Brief

## Why This Exists

The goal is to build a standalone alternative to hosted fiction-writing tools:
a private writing environment with AI support later, no platform lock-in, and no
subscription dependency.

The user has long experience as a developer and architect, but has not written
production code recently. The project should therefore favor clear architecture,
incremental progress, and understandable code over fashionable complexity.

## Core Decisions So Far

- The backend is a Python local application service.
- The frontend is TypeScript.
- The editor should be WYSIWYG, not a raw Markdown editor.
- TipTap/ProseMirror is the current editor direction.
- Scenes are the atomic draft unit.
- Acts, chapters, sequences, and other groupings organize scenes.
- Scene prose is stored as Markdown with YAML front matter.
- Lore is stored as Markdown entries with YAML front matter.
- Lore entries have schema-driven entry types, tags, aliases, references, and
  Markdown bodies.
- Metadata schemas are layered from a configured projects base folder down to
  the open project folder.
- Node types can inherit field definitions from parent node types. The current
  implementation has Scene and Lore Entry roots; a broader base Node model is
  the intended direction.
- The manuscript arrangement is stored separately and owned by the backend.
- The story information collection is called Lore.
- Individual Lore items are called Entries.
- Export to Word, PDF, and EPUB is explicitly out of scope.

## Project Format Direction

```text
project.yaml
manuscript.structure.yaml
metadata.schema.yaml
tags.yaml
scenes/
lore/
prompts/
todo.yaml
.cache/
```

Scenes live in `scenes/` as Markdown files. Lore entries will live under
`lore/`. Tags live in `tags.yaml`. Cache data must be disposable.

`project.yaml` may contain project configuration such as UI preferences,
default project folder hints, and allowed Manuscript Structure container types.
It must not become a canonical store for prose or the manuscript tree.

`manuscript.structure.yaml` is a tree. Scenes are leaf nodes. Organizational
nodes such as acts, chapters, and sequences are containers chosen from project
configuration rather than a mandatory default hierarchy. A new empty project
starts with a single empty Scene in the tree.

## Backend Responsibilities

- Open/create/validate projects.
- Read and write scene files.
- Own manuscript structure mutations.
- Perform atomic saves.
- Maintain TODOs.
- Provide search.
- Later: maintain SQLite indexes, render prompts, and call AI providers.

## Frontend Responsibilities

- Provide the writing UI.
- Own editor state between saves.
- Render manuscript structure.
- Present TODOs and search results.
- Later: present AI prompt/suggestion workflows.

## Current Code Location

The working codebase is:

```text
C:\Users\anton\Documents\Codex\local-writing-app
```

The old generated-thread copy under the previous `outputs/` folder should be
ignored.
