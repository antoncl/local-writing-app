# Local Writing App Prototype

This is the first vertical slice for a private, local-first fiction writing app.

The app is split into:

- `backend/`: a Python FastAPI local application service
- `frontend/`: a TypeScript/Svelte browser UI with a TipTap editor

The project format is file-based. Scenes are stored as Markdown files with YAML
front matter, and manuscript arrangement is stored in `manuscript.structure.yaml`.

## Current Scope

- Create/open one local project folder
- Maintain a manuscript tree of acts, chapters, and scenes
- Create, read, save, and delete scenes
- Edit a scene with a WYSIWYG editor
- Store scene prose as Markdown
- Maintain project-level and scene-level TODOs
- Basic full-project search

AI, export, installer packaging, comments, and semantic rename are intentionally
out of scope for this first slice.

## Project Format

```text
project.yaml
manuscript.structure.yaml
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

Anchored TODO ownership and synchronization invariants are documented in
`docs/editor-todo-invariants.md`.

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
