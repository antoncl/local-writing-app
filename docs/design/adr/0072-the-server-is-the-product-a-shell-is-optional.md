# ADR-0072: The server is the product; a desktop shell is optional; updates ride GitHub Releases

- Status: **Proposed** — 2026-08-23. Awaiting Anton's review.
- Verified against `269d500f` (2026-08-23).
- Feature: #173 (packaging & installers, the last pre-public 0.9.5 pillar) · Follows: ADR-0056
  (a boundary is a choke point) · Relates: ADR-0047 (settings live behind the `≡` menu),
  ADR-0071 (the migration mechanism a real install will eventually run) · Touches: #161
  (detach-to-OS-window — scoped **out**, §9)
- Supersedes nothing. Establishes the distribution topology the app has never had.

## Problem

The app has no way to reach a non-technical user. `README.md:65-66` lists "an installer" under
*Deliberately absent*; today the only way in is a terminal — create a venv, `pip install -e`, run
uvicorn by hand, then `npm run dev` in a second terminal, open the Vite URL. #173 is the milestone
that closes this before the repo goes public.

Three structural facts decide the shape of any answer, and all three must be dealt with **before**
an installer is even meaningful:

- **The backend does not serve the frontend.** `main.py:120-129` mounts routers only — no
  `StaticFiles`, no SPA fallback (grep for `StaticFiles`: zero matches in app code). The product is
  two processes today: Vite serves the UI, which talks **cross-origin** to the backend, which is why
  the CORS regex at `main.py:64-77` exists at all.
- **The frontend's API base is baked at *build* time.** `api.ts:101` reads
  `import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8787/api"` — a compile-time define, with no
  runtime channel to tell the shipped bundle where its backend is.
- **There is no product entrypoint, and host/port are hardcoded in the invocation.** No
  `[project.scripts]` in `backend/pyproject.toml`, no `app/__main__.py`; host/port live only in the
  uvicorn command line and `scripts/dev_backend.py` (dev-only). Nothing reads a bind address from
  configuration.

A fourth fact decides *which* answer is possible: **the target machines are not all desktops.** Anton
runs a **headless Raspberry Pi** and wants to use it. A headless box has no display, so any topology
that makes "a native desktop window" *the product* is dead on that machine.

This ADR fixes the topology and the distribution/update path. It does **not** design the internals of
any installer, the self-update swap mechanics, code-signing, or the desktop window — each is named,
scoped to its slice (§10), and deliberately not sketched here (the P2 trap: a deferred feature's
*shape* guessed early acquires authority it never earned).

## Decision

**The product is a single self-contained server binary that also serves the built frontend from its
own origin. A desktop window is an optional convenience layer on top of it, never a requirement.
Distribution and updates ride GitHub Releases, on two channels the user chooses between.**

### 1 — One process, one origin

The packaged product is **one process**: the FastAPI backend serves both the JSON API and the built
Svelte bundle (`StaticFiles` + an SPA fallback to `index.html`). Consequences that fall straight out:

- **The cross-origin split disappears** for the shipped product. `api.ts` defaults to a **relative,
  same-origin** base (`/api`) so the bundle reaches its backend with no baked-in address — dissolving
  the second and (with §3) the fourth structural fact at once. The `VITE_API_BASE` override stays,
  for the **dev** stack only, where Vite still serves the UI cross-origin with HMR.
- **Dev stays two-process; the product is single-process.** This ADR adds a serving path, it does not
  remove the Vite dev workflow. The CORS regex (`main.py:64-77`) remains for dev; a same-origin
  product needs no CORS at all.

### 2 — A product entrypoint

The app gains a real entrypoint — an importable `run()` (a `[project.scripts]` console entry and a
`python -m app` path) that starts uvicorn against the app with the resolved bind (§3) and serves the
bundle (§1). This is what the freeze (§4) wraps and what a service unit (§8) invokes. uvicorn-by-hand
remains valid for development; it stops being the *only* door.

### 3 — The bind address is configuration, and the LAN bind is an explicit, consequential opt-in

Host and port become configurable — resolved in a fixed precedence (explicit flag/env → machine
settings → the loopback default), never hardcoded. The default is **`127.0.0.1`**, unchanged in
spirit from today.

**Binding a non-loopback address is a deliberate act with a named consequence.** The Pi case *requires*
it (a headless box is useless on loopback — the user connects from another machine on the LAN). But
the entire codebase assumes loopback: the CORS comment states the backend is "never network-exposed"
(`main.py:66-72`), and **there is no authentication anywhere** — the local-first model has always been
*one trusted user on `127.0.0.1`*. Therefore:

- The bind address is machine-scope configuration (it lives with the machine, not a project).
- **This ADR does not add authentication, and does not silently widen the threat model.** A
  LAN-bound instance is supported **only** for a single trusted user on a trusted private network
  (the Pi-in-your-home case). Turning it on must *say so* at the point of choice. Auth, TLS, and a
  real multi-user story are **out of scope** and explicitly *not* sketched here — naming the boundary
  is the decision; building past it is a separate future one. (This is the one place the packaging
  work touches security, and it must not leak past this paragraph.)

### 4 — The freeze: one PyInstaller artifact per (platform, architecture)

The server + its Python runtime + the built frontend are frozen with **PyInstaller** into a
self-contained artifact — no Python or Node install on the user's machine. The built frontend is baked
in as data; the serving path (§1) resolves the bundle location from the frozen data dir in a packaged
run and from `frontend/dist` in a source run.

The build matrix includes **`linux-arm64`** as a first-class target, because the Pi is a first-class
target. (ARM build *mechanism* — GitHub's arm64 runners vs. a self-hosted runner on the Pi — is a
slice decision, §10 S4, not an architectural one.)

### 5 — Distribution and updates ride GitHub Releases, on two channels

GitHub is the distribution channel and the update source. **GitHub CD** (a new workflow, §10 S4)
builds the matrix and publishes artifacts to **GitHub Releases**; the running app reads the Releases
API to discover and fetch updates. Two channels, per #173's "subscribe to updates":

- **Stable** — tagged releases (`v*`). The default.
- **Bleeding edge** — a single **rolling `nightly` prerelease** built from `master`. One moving
  prerelease, not per-commit builds (which would be noise + unbounded storage).

The chosen channel is **machine-scope state** (it is a property of this install, like the bind
address). The update *mechanism* — poll by channel, compare to the running version, download, and
**swap-on-restart** (a running binary cannot always overwrite itself in place; Windows in particular
holds the file) — is real work with platform quirks, scoped to §10 S6 and not solved here.

### 6 — The running version is visible; the update surface lives behind the `≡` menu (ADR-0047)

Today the version is **invisible to the UI**: `main.py:59-63` derives it from package metadata for the
OpenAPI docs only, `/api/health` returns `{"status": "ok"}` with no version (`project.py:51-53`), and
nothing renders it. Update-subscription (#173 point 5) needs it surfaced:

- A dedicated **`/api/version`** endpoint reports the running version (health stays a bare liveness
  probe — a different concern).
- The **update surface is machine-scope settings** (ADR-0047: global/project-scoped features live
  behind the `≡` menu; the `MachineSettings` model at `machine_settings.py:106-123` and its dialog are
  the established home — it already carries app-global preferences like `display`, `palette`, and
  `ai_policy`). It shows the current version, the available version for the chosen channel, a channel
  selector (Stable / Bleeding edge), and a check/update action.

### 7 — The desktop window is a thin, optional shell — not the product

On a desktop (Windows/macOS), the server is *optionally* wrapped in a native window using the OS's
built-in webview via **pywebview** — chosen because it is **pure Python**, rides along in the *same*
PyInstaller freeze (§4) with **no second toolchain**, and uses the platform webview (WebView2 /
WKWebView / WebKitGTK) rather than shipping a browser engine. The window points at the local server; a
tray affordance is optional.

The shell is a **layer, not a foundation**. If it is absent, or on the headless Pi, the product is the
server and the user opens a browser at its address. Nothing in the API, the bundle, or the update path
depends on the window existing. Its internals (window lifecycle, tray, multi-window) are the last,
optional slice (§10 S8) and are deliberately not designed here.

### 8 — The Linux server/Pi form is a service; the desktop Linux form is an AppImage

Linux gets two forms, because the two Linux use-cases genuinely differ, and neither justifies a
per-distro package zoo:

- **Server / headless (the Pi):** a **tarball + a `systemd` unit** — install, enable, it runs the
  server (§2) headless on the configured bind (§3) and self-updates (§5). No display, no shell (§7).
- **Desktop Linux:** an **AppImage** — one distro-agnostic file that runs the server + shell (§7).

Per-distro native packages (`.deb`/`.rpm` for every distribution) are the proliferation trap the
"Linux has a thousand flavors" problem warns against; AppImage + tarball covers effectively everyone.

### 9 — #161 (detach a tab to its own OS window) is out of scope, and stays a droppable nice-to-have

#161 presupposes a native multi-window shell and **cannot work on the headless Pi** (no display), so
it can never be load-bearing. It must not be allowed to pull the shell choice (§7) toward a heavier
multi-window toolchain (Tauri/Electron): the baseline job is *install, run, update*, and detach is a
desktop-only enhancement at most. #161 is **not** in the #173 baseline. If detach later proves to be
something worth having, *that* is the moment to weigh a heavier shell against it — on evidence, not
speculatively now. (Per Anton: if it causes any problems, it is dropped outright.)

### 10 — The Mac carve-out: build it, ship it experimental-unsigned, defer signing

CI can *build* a macOS artifact on a `macos` runner with no Mac in the loop — but an unsigned,
un-notarized app hits Gatekeeper ("app is damaged"). Proper signing needs an Apple Developer account
($99/yr) + notarization in CI. Decision for 0.9.5: **ship macOS as experimental, unsigned, with a
documented one-time workaround**, and add signing only if real Mac users appear. The milestone is not
held hostage to Apple bureaucracy, and Anton has no Mac to verify a signed build against anyway. The
signing/notarization mechanism is **not** designed here — it is a later decision with a cost attached.

## Why / rejected alternatives

- **The desktop app *is* the product; the server is an implementation detail.** The natural instinct,
  and the Pi kills it: a headless box has no window. Inverting it — server is the product, window is a
  layer — is the only topology that serves a desktop and a headless Pi from *one* codebase. Rejected.
- **Electron (or any bundled-Chromium shell).** Ships a whole browser engine (~150 MB), a heavy
  download and a second (Node) toolchain, and reads as the opposite of the "quiet writing desk"
  (ADR-0030). A pure-Python OS-webview shell (§7) is a fraction of the size and adds no toolchain.
  Rejected.
- **Tauri (Rust shell + Python sidecar).** Better multi-window than pywebview — but its one payoff
  here is #161, which is out of scope (§9) and droppable; against that it adds a Rust toolchain and a
  sidecar-process story to every build. Not worth it for a baseline that doesn't need multi-window.
  Rejected (revisit only if detach becomes a real requirement).
- **Keep the two-process, cross-origin split in the product.** Shipping two servers (uvicorn + a
  static server / Vite) to an end user is absurd operationally, keeps the CORS surface in production,
  and leaves the build-time API base (`api.ts:101`) unsolved on any non-default origin (the Pi).
  Serving the bundle same-origin (§1) removes all three at once. Rejected.
- **A runtime frontend-config channel (a served `config.js` the bundle reads for its API base).** A
  real pattern, and *unnecessary* the moment the backend serves the bundle same-origin — the base is
  simply relative. Adding a config channel would be machinery with no consumer. Rejected.
- **A per-document / per-distro native package for Linux.** `.deb` + `.rpm` + … per distro is the
  maintenance zoo the distro-proliferation problem is exactly about. AppImage (desktop) + tarball
  &nbsp;+ systemd (server) covers the field with two artifacts. Rejected.
- **Apple notarization now.** Costs money and adds an external dependency (Apple) to the release
  pipeline for a platform the author cannot even test. Experimental-unsigned ships value now; signing
  is a cheap follow-up *if demand appears*. Rejected for 0.9.5.
- **Per-commit bleeding-edge builds.** Every push a release is noise and unbounded artifact storage; a
  single rolling `nightly` prerelease gives "latest master" with none of that. Rejected.
- **A self-hosted-only build story (build releases on the Pi).** Couples every release to Anton's Pi
  being online and healthy. GitHub-hosted runners are the primary path; a self-hosted Pi runner is a
  *fallback* for arm64 only if GH's arm64 runners aren't available (§4). Rejected as the primary.
- **Add authentication as part of the LAN bind.** Tempting, because the LAN bind exposes an
  unauthenticated app — but auth/TLS/multi-user is a large design of its own, and folding a half-baked
  version into a packaging milestone would ship a false sense of security. The honest move is to *name*
  the boundary (§3: single trusted user, trusted network) and not cross it here. Rejected (deferred,
  not sketched).

## Consequences

- **The Foundation slice (S1) is independently valuable before any installer exists.** Serve-the-bundle
  + same-origin `api.ts` + an entrypoint + a configurable bind means "the product is one process you
  can start and reach from a browser (or the Pi's LAN)" — testable on Windows and the Pi long before
  freezing, installers, or macOS enter the picture. It is the keystone every later slice builds on.
- **Same-origin removes CORS from the product.** The regex (`main.py:64-77`) becomes dev-only; a
  packaged instance serves bundle and API from one origin and needs no cross-origin allowance.
- **The version stops being invisible.** `/api/version` + the settings surface (§6) are the foundation
  the update UI (S7) sits on; nothing renders the version today.
- **A LAN-exposed instance is single-trusted-user-on-a-trusted-network only** — stated at the point of
  choice (§3), not assumed. Any future that wants real network exposure must first build auth; this
  ADR deliberately does not, and must not be read as having widened the threat model.
- **Self-updating a running binary has real platform quirks** — Windows cannot overwrite the running
  executable, so the swap happens on restart (§5); named here, solved in S6.
- **macOS is best-effort until someone signs it** (§10) — users get a documented Gatekeeper
  workaround, not a clean first-run, until a signing decision is made.
- **A body-format or storage change now has an install to migrate.** The moment real users install,
  the recreate-projects escape hatch is gone — which is exactly why ADR-0071 built the migration
  mechanism ahead of this. This ADR is what makes that pre-work load-bearing.
- **#161 stays parked** (§9); the shell (§7) is intentionally single-window so nothing has to be
  un-built if detach is dropped for good.

## Slices

Sequenced as **one lane** — dependent work sequenced, not parallelised (worktree-first, one lane).
Each lands via its own PR under #173.

1. **Foundation — one process, one origin** (§1, §2, §3): backend serves the built bundle
   (`StaticFiles` + SPA fallback); `api.ts` defaults to same-origin relative `/api` (`VITE_API_BASE`
   retained for Vite dev); a product entrypoint (`[project.scripts]` + `python -m app`); host/port
   resolved from flag/env → machine settings → loopback default, with the LAN-bind opt-in surfaced.
   *The keystone. Testable on Windows and the Pi with no packaging.*
2. **Version surface** (§6): `/api/version`; the running version shown in the settings/About surface.
3. **Freeze** (§4): a PyInstaller build producing one runnable artifact that serves the bundled
   frontend. Windows first (Anton can test it).
4. **GitHub CD** (§4, §5): a release workflow — matrix (windows-x64, macos, linux-x64, **linux-arm64**)
   on tag → GitHub Release; a nightly workflow on `master` → the rolling `nightly` prerelease. Settles
   the arm64 runner question (GH arm64 runner, else self-hosted Pi runner).
5. **Installers / packaging** (§8, §10): Windows installer; Linux AppImage (desktop) + tarball & systemd
   unit (server/Pi); macOS `.dmg` (experimental, unsigned, documented workaround).
6. **Auto-update backend** (§5): poll GitHub Releases by channel, compare to the running version,
   download + swap-on-restart; channel persisted in machine settings.
7. **Auto-update UI** (§6): the settings "Updates" pane — current/available version, channel selector,
   check + update.
8. **Desktop shell** (§7), *optional*: a thin pywebview window (+ optional tray) launching the server
   and opening the UI; absent → browser; headless → server only.

Binding = the Decision (§1–§10) and its anti-goals (the rejected list). Slice boundaries may shift if
implementation argues for it — amending this ADR before code.
