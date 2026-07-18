# View grammar — single-source IDL + generators (#277, ADR-0041)

`ViewExpr` is a small set-algebra / relational **language**. Its grammar is defined **once**, here,
and generated into both runtimes so a slot can't be half-added across the FE/BE boundary (the
#260/#275/#276 drift). This folder is the source of truth for the grammar's *shape*; the evaluator,
designer, and validators live in the app and consume it.

## Files

| File | Role |
|---|---|
| `view-grammar.yaml` | **The IDL — edit this.** The single source of truth for the grammar. |
| `emit_python.py` | Emitter → the Pydantic `ViewExpr` family + `children()`. |
| `emit_ts.py` | Emitter → the TS `ViewExpr` types + `children()`. |
| `generated_grammar.py` / `.ts` | **Machine-generated — do not edit.** Committed for inspection + the tsc proof. |
| `equiv.ts` + `tsconfig.check.json` | TS reproduce-today proof (structural type-equality vs `types.ts`). |
| `../../backend/tests/test_grammar_spike.py` | Python reproduce-today proof + a freshness guard. |

## Regenerate

```
backend/.venv/Scripts/python.exe scripts/viewgrammar/emit_python.py
backend/.venv/Scripts/python.exe scripts/viewgrammar/emit_ts.py
```

Regeneration is **not** wired into the build (generators complicate builds). The generated files
are committed artifacts; a freshness guard in the Python test fails if the committed
`generated_grammar.py` diverges from a fresh emit — so "edit the IDL, forget to regenerate" is
caught, without a build-time codegen step.

## Verify (the reproduce-today guards)

```
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_grammar_spike.py -q      # Python: parity + freshness
node frontend/node_modules/typescript/bin/tsc -p scripts/viewgrammar/tsconfig.check.json  # TS: type-equality
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

The IDL currently models the grammar **descriptively** — it reproduces today's hand-written
`app.models_views` (behaviourally) and `frontend/src/lib/types.ts` (by strict `tsc` structural
equality), warts included (two incidental TS quirks are reproduced via `ts_*` hints and flagged
inline as Phase-3 normalization candidates). The app still consumes the hand-written definitions.

**Cutover** — the app importing the generated grammar and deleting the hand-written copies — lands
with **Phase 3** (the prescriptive changes: Filter first-class, injector-role, kind-typed payloads),
when the single source first pays off. Cutting over while the outputs are identical is risk without
reward, and the generated-output **location** for app consumption (keeping imports clean without
complicating the build) is a decision best made at that point, not now.
