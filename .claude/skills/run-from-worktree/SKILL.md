---
name: run-from-worktree
description: Start this app's backend and frontend dev servers from a linked worktree and open them in the Browser pane. Use before running, previewing or verifying the app in a worktree.
---

# Running the app from a worktree — start the servers yourself

**`preview_start` by config *name* runs the PRIMARY tree's code from any
worktree** (#360) — which is Anton's WIP and his live projects. So in a worktree,
start the servers by hand (an approved exception to the "never use Bash for dev
servers" guidance) and open the Browser pane on the URL:

```bash
python scripts/dev_backend.py                  # background it; publishes the port
npm run dev --prefix frontend -- --mode claude # background it, AFTER the backend's verified line
```

Then `preview_start {url: "<Vite's Local: URL>"}` and verify with `read_page`,
`read_network_requests`, and the console.

- **Never pick either port by hand.** Both derive from this checkout's path
  (`dev_backend.py`; `vite.config.js` in `--mode claude` without `PORT`). A
  hand-picked backend port silently shares on Windows (#364); a hand-picked
  frontend port collides with another session's, which opens the *other*
  tree's UI and — storage being per origin — its last-opened project. The one
  exception: if a derived port is already taken (a hash collision with a
  sibling — the start fails loudly), rerun that server with `PORT=<free port>`.
- Read the startup lines rather than assuming isolation: `dev_backend: verified
  <path> is serving 127.0.0.1:<port>` names the checkout actually being served,
  and Vite's `Local:` line names the frontend's port.
- **To stop a server, kill the process *tree*, and don't trust the PID the OS
  reports** — `taskkill /F /T /PID <reloader pid>`. → `docs/development/worktrees.md`
- A `SessionEnd` hook now stops this worktree's own dev servers automatically
  (#452). It never touches another tree's, so killing one by hand mid-session is
  still yours to do.
