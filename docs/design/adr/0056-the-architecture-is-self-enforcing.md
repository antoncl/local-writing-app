# ADR-0056: The architecture is self-enforcing — a boundary worth keeping is a gate or a choke point, not a convention

- Status: **Proposed** — 2026-08-15 (awaiting Anton). Designed with him over the AI-maintainability thread.
- Issue: #977 (the enforcement work this decision authorizes) · Pre-1.0 (targets 0.9.0 — code quality / technical debt)
- Relates: `docs/development/code-standards.md` (the per-file / per-function size rules — the same "make the right thing structural" instinct), `docs/development/quality-gates.md` (the three enforcement layers this generalizes), the class–instance model and the "one uniform shape" it buys (`kind`/`entry_type`/`entry`)
- **Verified against `9e5740f` (2026-08-15).**

## Context

This project has two properties that, together, make it unlike a normal codebase:

1. **The author does not read the code.** By deliberate choice, Anton reads no source. On a normal team the reviewer is what keeps layering honest — the person who says "that logic doesn't belong in the route" or "we already have a logger, use it." That backstop is gone.
2. **The maintainer has no persistent memory.** The codebase is written almost entirely by an AI assistant whose context is per-session and lossy. Across sessions it reconstructs understanding from `CLAUDE.md` (always loaded), a handful of memory notes it happens to recall, and whatever code it reads into context on demand. It has no ambient familiarity with the whole and no reliable recall of what mechanisms already exist.

The failure mode that follows is concrete, not hypothetical: working on feature X, the assistant does not have the existence of some cross-cutting mechanism in context, so it re-implements or omits it — the canonical example being "log this error," when a logging path already exists but nothing at the change site surfaced it. The same lossy memory re-derives judgment calls (`where does this logic belong?`) from scratch each session, producing *inconsistent* placement over time. Neither failure is visible to the author, because he is not reading the code.

**Verified current state (against `9e5740f`):**

- **The layering is real but entirely unenforced by tooling.** Routes live in `backend/app/routers/*.py` and are thin delegators to `ProjectService` (composed from ~40 mixins at `backend/app/services/project_service.py:77`); the dominant shape is `with translate_errors(): return project.<method>(...)`. The frontend routes all network I/O through one client, `frontend/src/lib/api.ts` (`request` at `:165`, `streamNdjson` at `:241`), and keeps domain state in rune controllers under `frontend/src/lib/stores/*.svelte.ts`, not components. But **no gate checks any of this.** ruff `select` is `E,F,W,I,B,UP,C4,SIM` — `I` is import *sorting*, not import *direction*; the complexity rules run advisory; the file-size and style-token guards check line counts and CSS tokens. The layering rule lives only as prose in `backend/app/main.py`'s module docstring and in `CLAUDE.md`.
- **The drift already happens.** `create_project` / `open_project` (`backend/app/routers/project.py:69`) inline cross-service orchestration — `node_index_gate.invalidate()`, `touch_recent_project(...)` — directly in the route handler instead of behind a single service method. A reviewer would have caught it; there was none.
- **One cross-cutting concern is already done right, and it proves the thesis.** Error logging is a choke point: a single `@app.middleware("http")` (`backend/app/main.py:67`) records every unhandled backend error through one writer, `error_log.append_error_line` (`backend/app/services/error_log.py:53`); on the frontend a single `run()` funnel (`frontend/src/App.svelte:460`) is injected into every store and routes action failures through `errorLog.ts`. Errors get logged **whether or not the assistant remembers the mechanism exists**, because the architecture — not a remembered call — puts the logging in the path. That is the pattern this ADR generalizes.

## Decision

### 1. The gates are the review

Because there is no human reading the code, the quality gates (in-session hook, pre-commit, CI) are not a safety net *under* review — they *are* the review. It follows that **a boundary is only as real as its enforcement.** A layering rule that lives only as prose is a rule that will drift, silently and unseen. This is not a criticism of prose docs; it is a statement about what they can and cannot hold given who maintains this repo.

### 2. Two enforcement shapes: choke point (preferred) and fitness gate (fallback)

A boundary worth keeping is made real in one of two ways:

- **A choke point** routes the work through a single unavoidable path, so the correct behaviour happens by construction and nothing needs to be remembered. The error-log middleware and the frontend `run()` funnel are the exemplars. This is strictly preferred: it cannot be forgotten, because there is nothing to forget.
- **A fitness gate** is a cheap machine check (a `scripts/check_*.py` wired into the gates, grep- or AST-level) that fails when a boundary is crossed. It is the fallback for boundaries that cannot be collapsed into a single path — e.g. "a `services/` module must not import FastAPI," "a route handler must not contain business logic."

When a boundary can be a choke point, make it one. Reach for a gate only when it can't.

### 3. Uniformity is the third pillar — one shape per layer

A cold session works by pattern-matching a local example, not from global knowledge. So the strongest defence against inconsistent placement is that every instance of a layer has the **same shape**, letting a new one be written correctly by reading a single sibling. The enemy is not depth — five layers applied identically are cheap to maintain — it is *variety*: two layers applied three different ways rot, because there is no canonical sibling to copy. This is the same force that already makes the node model tractable (everything reduces to a small set of shapes).

### 4. Cross-cutting concerns are choke points, never remembered call-sites

Any concern that must be applied "everywhere" — logging, error capture, scope resolution, atomic writes — is expressed as a single path the work already flows through, not as a convention to invoke at each site. Scope resolution already is one (`CurrentProject` / `scopeHeaders`); error logging already is one. New cross-cutting concerns follow the same rule: if the design would require the assistant to *remember to call* it, the design is wrong for this repo.

### 5. Not every boundary earns a gate

This is deliberately not a mandate to gate everything — over-gating is its own debt, and a wall of brittle checks is as unmaintainable as none. A boundary earns enforcement in proportion to the **blast radius of a silent violation**: how badly a breach corrupts behaviour, and how invisible it would be to the author. A boundary whose violation is loud, self-correcting, or cosmetic can stay a convention. Enforcement is spent where a quiet breach would be dangerous and unseen.

### 6. The one rule

If a boundary matters, make it structural or make it checked. If it is neither, assume it will drift — and decide, on purpose, whether that is acceptable.

## Why / rejected alternatives

- **Documentation as enforcement — rejected.** "Write it in `CLAUDE.md` / a memo and the assistant will follow it." This is the status quo for layering, and it is exactly what fails: the assistant does not reliably recall a convention that isn't visible at the change site. Docs remain valuable as the *why*; they cannot be the *guarantee*.
- **A capability-inventory doc — rejected.** "Keep a list of every mechanism that exists, so the assistant reuses them." A big inventory fights the context budget (it can't be loaded every turn) and still isn't recalled at the moment of need. The fix is never "document the inventory," it is "make the infrastructure unavoidable at the point of use."
- **Trust and discipline — rejected.** Relying on the maintainer's care assumes persistent working memory and accumulated familiarity. Neither exists across sessions here.
- **Heavy enterprise layering — rejected as a goal.** The point is not more layers. Added layers that are not uniform and not enforced only multiply the surface that can drift. Depth is cheap when uniform and checked; expensive otherwise.

## Anti-goals

- **Not a mandate to gate every boundary.** §5 is explicit: enforcement is rationed by blast radius, not applied universally.
- **Not a call for more layers.** This ADR adds no architectural layer; it changes how the *existing* boundaries are held.
- **Not documentation-as-enforcement.** A note in this file or `CLAUDE.md` does not satisfy the decision; a choke point or a gate does.
- **Not a design of the specific gates.** Which boundaries get hardened, and how each check is implemented, is the audit-and-build work of #977 — deliberately not pre-designed here, so the sketch doesn't acquire authority it hasn't earned.

## Developer / maintainer journey

The "users" of this decision are the two parties who maintain the app:

- **A future assistant session** opens #977's second slice, adds an endpoint, and puts a slice of business logic in the route handler out of habit. CI fails with "business logic in a route — move it to a service," naming the boundary. The session moves it, reading one sibling route to match the shape. The mistake never reaches the author.
- **Anton** never reads the diff. He does not need to: the boundary that would have rotted is now a red check, and the error that would have gone unlogged is logged by the middleware regardless of what any session remembered. His confidence comes from the gates being green, not from having reviewed the code — which is the arrangement he chose.

## Consequences

- **0.9.0 gains an enforcement workstream (#977):** audit the informal boundaries, harden the two or three highest-blast-radius ones into fitness gates, and annotate the error-path choke point so it survives future edits. Bounded on purpose — the highest-value boundaries, not all of them.
- **New cross-cutting concerns carry a design constraint:** they must be expressible as a choke point, or they don't get built that way. If a concern genuinely cannot be funnelled, that is a signal to reconsider its shape.
- **The exemption ratchet extends naturally:** a new architectural check is ratcheted like the existing guards (`scripts/check_exemptions.py`), so it can only tighten.
- **`CLAUDE.md` and this ADR stay the *why*; the gates become the *guarantee*.** The prose explains intent to a human contributor; the machine holds the line.
- **Cost:** each fitness gate is code to maintain and can produce false positives; §5 is the guard against that becoming its own debt.

## Slice plan — one lane, disjoint, vertical (reorderable)

Carried by #977; sketched here only at the level the decision implies (implementation is the issue's, not this ADR's):

1. **Audit + rank** the informal boundaries by blast-radius of a silent violation; pick the two or three worth hardening.
2. **Harden** each chosen boundary into a `scripts/check_*.py` wired into `gates.yml` and ratcheted — or, where possible, refactor it into a choke point instead.
3. **Annotate** the error-path choke point (middleware + `run()` funnel) with a comment naming why it exists, so it is not "simplified" away.
4. **Resolve** the known counter-example (`create_project` / `open_project` route orchestration) — fold it behind a service method, or accept it explicitly as the documented exception.

## Deliberately out of scope (deferred, not sketched)

- **Which specific boundaries get gated, and the exact check for each.** That is the audit in #977; pre-committing the list here would guess at findings not yet made.
- **Any general "architectural fitness function" framework.** If more than a handful of checks accrue, a shared harness may be worth extracting — but only once the concrete checks exist to generalize from, not before.
