# View grammar — single-source IDL + generators (#277, ADR-0041)

`ViewExpr` is a small set-algebra / relational **language**. Its grammar is defined **once**, here,
and generated into both runtimes so a slot can't be half-added across the FE/BE boundary (the
#260/#275/#276 drift). This folder is the source of truth for the grammar's *shape*; the evaluator,
designer, and validators live in the app and consume it.

## Files

| File | Role |
|---|---|
| `view-grammar.yaml` | **The IDL — edit this.** The single source of truth for the grammar. |
| `emit_python.py` | Emitter → `../../backend/app/view_grammar_generated.py` (Pydantic `ViewExpr` family + `children()`). |
| `emit_ts.py` | Emitter → `../../frontend/src/lib/viewGrammar.generated.ts` (TS `ViewExpr` types + `children()`). |
| `../../backend/app/view_grammar_generated.py` | **Machine-generated — do not edit.** The backend's live grammar (imported by `models_views.py`). |
| `../../frontend/src/lib/viewGrammar.generated.ts` | **Machine-generated — do not edit.** The frontend's live grammar (re-exported by `types.ts`; `walkViewExpr` uses its `children()`). |
| `../../backend/tests/test_view_grammar.py` | Grammar guards: freshness (both runtimes) + `children()`. |

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
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_view_grammar.py -q   # freshness (both runtimes) + children
npm run check --prefix frontend                                                    # the whole app type-checks on the generated types
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

**Backend + frontend cutover: done.** Both runtimes consume the generated grammar:
`models_views.py` imports it from `app/view_grammar_generated.py`; `types.ts` re-exports the TS
family from `viewGrammar.generated.ts` and `walkViewExpr` delegates to its `children()`. The
reproduce-vs-hand-written proofs retired (nothing left to compare); the freshness guards +
behaviour tests (`test_views.py`, the view unit tests) carry on. Full backend suite + svelte-check
+ the view unit tests green.

The **prescriptive** grammar changes (Filter first-class, injector-role, kind-typed payloads) now
ride on the single source. That is where `specToGraph` / `viewGraph.ts` reshape (informing #278).
