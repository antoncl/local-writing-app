# Running from source

For the keenly interested. If you just want to write, the
[installers](https://github.com/antoncl/local-writing-app/releases/latest)
(Windows, macOS, Linux) are the short path.

## How it's put together

The app is two processes: a Python/FastAPI service on `127.0.0.1:8787` that owns
the project files, and a Svelte 5 + TipTap browser UI that talks to it. Nothing
phones home — the service binds to localhost, and every write to a project goes
through it (the UI never touches your files directly).

## Prerequisites

Python 3.11+ and Node 20+. Windows is the developed-on platform; nothing is
deliberately Windows-only, but the paths below use PowerShell.

## Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8787
```

## Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL it prints. The frontend expects the backend at
`http://127.0.0.1:8787`.

## Enabling AI

AI is off until you turn it on: set a project's policy to `local-only` or
`cloud-allowed` in the Project pane, and add provider keys (or an
[Ollama](https://ollama.com) host) in machine settings.

## Contributing

Quality gates (lint, type-check, tests, file-size and design-token guards) run
as git hooks and in GitHub Actions; `CLAUDE.md` documents the layout and the
rules, and `docs/development/` holds the mechanics behind them. Issues and
milestones on GitHub are the real backlog.
