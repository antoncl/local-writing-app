# ADR-0025: Views evaluate frontend-side; a SQLite index is rejected

- Status: Accepted (v1) — 0.5.0, 2026-07-02
- Feature: #35 Views & Filters · Doc: `views-and-filters.md` §2, §2.1 · Issue: #35
- Governed by: `memory/project_overview.md` (files-are-truth, `.cache/` rebuildable)

## Decision
Views evaluate **frontend-side** via one pure `evaluateView(spec, nodes)` module, consumed by
panes and pickers alike. The backend **stores and validates** view nodes but runs **no queries**.
A **SQLite index as the evaluator is rejected.** Server-side evaluation is deferred until
something that cannot see the frontend (e.g. context expansion) needs it.

## Why / rejected alternative
Measured, not assumed. `evaluateView` over a realistic large project (800 lore entries, simple
view) costs **~42 µs**; over a pathological project (10,000 nodes — ~20× a large collection — with
a deep view: 2× descendants-of, tag + field predicate, difference/intersection/union, 2 annotates,
sort, row materialize) costs **~3.2 ms**, against a 16 ms frame budget. Set ops over a few
thousand ids are not where wall-clock goes.

SQLite would **cost, not save**: (1) the data is already frontend-side (panes load their kind's
summaries), so a DB adds a ~1–5 ms HTTP round-trip per evaluation — more than the whole in-memory
pass — and the designer's live preview would feel it; (2) a DB index is a derived write-through
cache needing correct invalidation on every mutation path, including external edits and the
uvicorn-restart-mid-save class (#72) — a **new failure category**, whereas `.cache/` is
rebuildable *by design*; (3) the ops don't map cleanly — `descendants-of` needs recursive CTEs or
a closure table, and the multi-label **annotate** pass-through has no SQL shape, so you'd run N
queries and merge in code anyway.

Where SQLite would win — data exceeding memory, selective indexed lookups over 100k+ rows — a
fiction project never reaches; if it did, the "pane holds the whole kind" model breaks *before*
the evaluator does (a larger redesign, independent of evaluator location).

## Consequences
- **Two real perf concerns, neither a DB problem:** (1) *payload width* — field-predicate leaves
  need their fields in the frontend summaries, which may widen the summary payload (or those leaves
  evaluate backend-side); verify at build step 2. (2) *rendering, not evaluating* — a 1,700-row
  result is µs to compute, real ms to lay out; fix if it bites is NodeList **virtualization**,
  orthogonal to the evaluator.
- **Escape hatch by construction:** `evaluateView(spec, nodes)` is pure over a serialized spec —
  if the backend ever needs it (context expansion), port that one function to Python over the
  existing node index, still no database.
