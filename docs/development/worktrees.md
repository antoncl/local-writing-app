# Worktrees — why the rules are what they are

CLAUDE.md carries the rules in imperative form. This file carries the incidents
they came from. Read it when a rule looks arbitrary, when you are tempted to
work around one, or when something about worktree isolation is misbehaving.

## Why every Claude session gets its own worktree

The invariant — *Claude work happens in a linked worktree, always, forked from
`origin/master`* — retired three separate rules that each existed because of a
distinct failure:

- **Anton keeps uncommitted WIP in the primary tree.** A broad `git add` swept
  it into a commit once. Worse, `pre-commit`'s stash is a patch file under
  `~/.cache/pre-commit`, *not* a git stash — so `git stash list` looks empty
  while the tree has been reverted repo-wide for the duration of the run. A
  concurrent session in the same directory sees its edits vanish and reappear.
  In a separate directory neither mechanism can reach his files.
- **HEAD used to drift mid-session.** Another session merges a PR, its branch is
  deleted, and the shared tree silently lands on `master`. A private worktree has
  a private HEAD.
- **The base ref is the harness's job now, not yours.** Reading a floating `HEAD`
  to decide what to branch from is what produced the wrong-branch commit this
  policy came from. `worktree.baseRef` is pinned to `fresh` so the branch forks
  `origin/master`.

**The carve-out:** work that genuinely depends on *unmerged* work forks the
dependency's branch, explicitly, and says so in the PR. Forking `master` for a
dependent slice is what got #312 rolled back — repairing it cost more than the
parallelism saved. Prefer not to be in that position at all: **one work lane**,
sequence dependent work rather than running it in parallel.

## Running the app from a worktree

**`preview_start` by config name resolves `.claude/launch.json` from the PRIMARY
tree, so it runs the primary tree's code no matter which worktree the session is
in** (#360). Verified: a fresh start from a worktree watched `<primary>/backend`,
wrote no port file, and used a config the worktree had rewritten.

That is the same defect as #352 — a verification path exercising the wrong tree
— and it is worse here than for the gates, because the primary tree holds
Anton's WIP *and his live projects*. A worktree session that believed it was
driving an isolated backend would be driving his.

So in a worktree, start the servers by hand (a deliberate, Anton-approved
exception to the general "never use Bash to run dev servers" guidance, which
predates worktree isolation), then point the Browser pane at the URL with
`preview_start {url: …}` — the `url` form opens a tab without starting a server.

## Why you must not pick the backend port by hand

`scripts/dev_backend.py` derives the port from *this checkout's path*
(8800–8899), which separates sibling worktrees. `PORT` still overrides, and is
the escape hatch if two checkouts ever hash to the same slot (1-in-100, and it
now fails loudly rather than silently).

Hand-picking is how #364 happened. Every worktree defaulted to `8788`, and on
Windows `uvicorn --reload` binds with `SO_REUSEADDR` — which Windows reads as
"share this address" when *both* sides set it, as every `--reload` server does.
The second start then **succeeds silently**, receives nothing, and the first
tree's server answers every request.

The launcher now refuses an occupied port up front, and after startup makes the
server prove it is the one just started: a per-launch nonce over
`/__dev_backend_provenance`, served by `scripts/dev_backend_app.py`. It publishes
`tmp/dev-backend-port` only once that passes, so the frontend inherits the
guarantee — `--mode claude` hard-fails on a missing port file rather than
quietly showing another tree's data.

Read the startup line rather than assuming isolation:

```
dev_backend: verified <path> is serving 127.0.0.1:<port>
```

names the checkout actually being served.

## Why stopping a server needs the process *tree*

`uvicorn --reload` spawns a `multiprocessing` child that survives its parent and
keeps holding the port. Worse, `netstat -ano` and `Get-NetTCPConnection` both
report the socket against the *reloader* that created it, which by then is
usually **dead** — so you kill that PID, it reports success, and the port keeps
serving.

This is exactly how #364's "I killed every listener on the port" step produced a
false negative and sent the diagnosis after the import system instead. Ask the
server who it is (`curl 127.0.0.1:<port>/__dev_backend_provenance` returns the
real pid), or find the live child:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*multiprocessing*' } |
  Select-Object ProcessId,ParentProcessId
taskkill /F /T /PID <the reloader pid>   # /T is the part that matters
```

## Housekeeping

- A worktree gets its own `node_modules` (`scripts/npm_run.py` runs a real
  `npm install`). That costs minutes and disk, so let it happen when a session
  first needs frontend gates, not upfront — docs-only work never needs it.
- **Never link or junction a shared `node_modules`/venv into a worktree.** A
  recursive delete — `git worktree remove -f` among them — walks through the link
  and guts the primary install (#350, and
  `memory/feedback_never_junction_shared_venv.md`).
- A worktree is a fresh checkout, so gitignored files do not come along. If some
  local file must be present in every worktree, list it in a `.worktreeinclude`
  at the repo root (`.gitignore` syntax; only gitignored matches are copied)
  rather than copying it by hand.
- Clean up when the PR merges: `ExitWorktree` with `remove`. It refuses while
  uncommitted changes or unmerged commits remain, which is the behaviour you
  want. Stale worktree directories are not free — each one carrying a
  `node_modules` adds ~24k files under the repo root.
