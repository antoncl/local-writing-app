# Local Writing App Prototype

This is the first vertical slice for a private, local-first fiction writing app.

The app is split into:

- `backend/`: a Python FastAPI local application service
- `frontend/`: a TypeScript/Svelte browser UI with a TipTap editor

The project format is file-based. Scenes are stored as Markdown files with YAML
front matter, and manuscript arrangement is stored in `manuscript.structure.yaml`.
Markdown front matter carries each node's stable `id`; filenames are not the
canonical identity.

## Current Scope

- Create/open one local project folder
- Maintain a manuscript tree of acts, chapters, and scenes
- Create, read, save, and delete scenes
- Edit a scene with a WYSIWYG editor
- Store scene prose as Markdown
- Maintain Lore entries with entry types, tags, aliases, and Markdown bodies
- Edit layered metadata field and node-type definitions
- Maintain project-level and scene-level TODOs
- Basic full-project search

AI, export, installer packaging, comments, and semantic rename are intentionally
out of scope for this first slice.

## Project Format

```text
project.yaml
manuscript.structure.yaml
metadata.schema.yaml
scenes/
lore/
prompts/
todo.yaml
.cache/
```

`lore/` is the collection name. Individual items are entries.

`project.yaml` also carries project configuration such as UI preferences and
allowed Manuscript Structure container types. The manuscript tree remains in
`manuscript.structure.yaml`, and prose remains in Scene Markdown files.

Metadata definitions are intentionally layered. The application provides only a
minimal built-in schema, then merges every `metadata.schema.yaml` from the
configured `settings.projects_base_folder` down to the open project folder.
Nearer folders override farther ancestors, so users can choose their own
folder depth for world, series, book, or other levels without the app modeling
those concepts directly. The project base folder can be changed from the
Project pane after opening a project.

The Metadata Schema pane lists effective schema definitions and their source
layers. Node types are displayed as an embedded tree for the current context,
with local field bindings shown on each node and inherited fields visible by
expanding parent nodes. New fields and node types are saved to an explicit
schema layer, such as the base folder, an ancestor folder, or the project
folder. The app creates a `metadata.schema.yaml` file at that layer only when a
definition is saved there.

Anchored TODO ownership and synchronization invariants are documented in
`docs/editor-todo-invariants.md`.

The planned metadata model for Scenes, Lore Entries, and Prompt Entries is
documented in `docs/metadata-strategy.md`.

## Run Locally

Backend:

```powershell
cd C:\Users\anton\Documents\Codex\local-writing-app\backend
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8787
```

Frontend:

```powershell
cd C:\Users\anton\Documents\Codex\local-writing-app\frontend
npm install
npm run dev
```

Then open the Vite URL shown in the terminal. The frontend expects the backend
at `http://127.0.0.1:8787`.
