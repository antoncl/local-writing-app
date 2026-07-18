# View grammar — single-source IDL + generators (#277, ADR-0041)

`ViewExpr` is a small set-algebra / relational **language**. Its grammar is defined **once**, here,
and generated into both runtimes so a slot can't be half-added across the FE/BE boundary (the
#260/#275/#276 drift). This folder is the source of truth for the grammar's *shape*; the evaluator,
designer, and validators live in the app and consume it.

## Files

| File | Role |
|---|---|
| `view-grammar.yaml` | **The IDL — edit this.** The single source of truth for the grammar. |
| `emit_python.py` | Emitter → `../../backend/app/view_grammar_generated.py` (the Pydantic `ViewExpr` family + `children()`). |
| `emit_ts.py` | Emitter → `generated_grammar.ts` (TS `ViewExpr` types + `children()`). Frontend not cut over yet. |
| `../../backend/app/view_grammar_generated.py` | **Machine-generated — do not edit.** Imported by `models_views.py`; the backend's live grammar. |
| `generated_grammar.ts` | **Machine-generated — do not edit.** Frontend spike output (in scripts pending the frontend cutover). |
| `equiv.ts` + `tsconfig.check.json` | TS reproduce-today proof (structural type-equality vs `types.ts`). |
| `../../backend/tests/test_view_grammar.py` | Backend grammar guards: freshness + `children()`. |

## Regenerate

```
backend/.venv/Scripts/python.exe scripts/viewgrammar/emit_python.py
backend/.venv/Scripts/python.exe scripts/viewgrammar/emit_ts.py
```

Regeneration is **not** wired into the build (generators complicate builds). The generated files
are committed artifacts; a freshness guard in the Python test fails if the committed
`view_grammar_generated.py` diverges from a fresh emit — so "edit the IDL, forget to regenerate" is
caught, without a build-time codegen step.

## Verify (the guards)

```
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_view_grammar.py -q        # backend: freshness + children
node frontend/node_modules/typescript/bin/tsc -p scripts/viewgrammar/tsconfig.check.json  # TS: type-equality vs types.ts
```

The Python guard runs on `git push` via the existing pre-push `pytest`. The `tsc` guard is a manual
check for now (kept out of the build deliberately).

## The stable surface — what you may build on

A grammar change **regenerates these files and may churn their internals**. Depend only on:

- **The exported grammar type/model names** — `ViewExpr` and its family (`ViewNestOp`,
  `ViewFieldPredicate`, …) — and their documented field semantics. This is the language's public API.
- **`children(expr)`** — the one canonical traversal every walker should route through.
- **The validation behaviour** — exactly-one-primary, the pairing/payload/min-item rules.

**Do NOT build on** (these change freely as the grammar evolves — Filter becoming first-class,
kind-typed payloads, new operators):

- the exact **slot membership** of `ViewExpr`;
- **internal helper names** (e.g. `_VIEW_EXPR_PRIMARY_SLOTS`), field ordering, formatting;
- the **absence of docstrings** — rationale lives in the ADRs and this file, not in generated code
  (generated docstrings read as abstract boilerplate; deliberately omitted).

Don't subclass, extend, or hand-edit the generated modules. Change the grammar by editing the IDL.

## Status (Phase 2, ADR-0041)

The IDL models the grammar **descriptively** (today's shape, warts included — two incidental TS
quirks are reproduced via `ts_*` hints, flagged inline as normalization candidates).

**Backend cutover: done.** `models_views.py` deleted its hand-written grammar classes and imports
them from `app.view_grammar_generated`; `services/project/views.py` and the tests import grammar
from the same module. The reproduce-vs-hand-written proof retired (nothing left to compare); the
freshness guard + `test_views.py` behaviour tests carry on. Full backend suite green.

**Frontend cutover: pending.** `types.ts` still hand-writes the `ViewExpr` family; `equiv.ts`
guards it against the generated TS by strict `tsc` equality. Cutover = emit into `frontend/src`,
re-export from `types.ts`, route `walkViewExpr` through the generated `children()`.

The **prescriptive** grammar changes (Filter first-class, injector-role, kind-typed payloads) ride
on top of the single source once both runtimes are cut over — that is where `specToGraph` /
`viewGraph.ts` reshape (informing #278).
