# Benchmarks

Measured evidence for ADRs. One subfolder per subject (`cache/`, and whatever
comes next) so a benchmark is findable from the decision it backs.

## Rules

**Drive the real code.** A benchmark that reimplements the path it measures will
drift from it, silently, and the ADR built on it inherits the drift. The cache
benchmark's first revision did exactly that: it reimplemented front-matter
parsing and extracted reference edges by *field-name prefix*, while the real
extractor is **schema-driven** — so its fixtures produced thousands of edges the
app would never have found, and its "faithful to the real parse path" claim was
an assertion rather than a property. Import `ProjectService` and call it.

**Fixtures are generated, never committed.** They run to tens of thousands of
files. Generate under `tmp/benchmark-fixtures/<subject>/` (gitignored); commit
the generator. `--regen` rebuilds.

**Quote the scope you measured.** The node index is built per *open project* —
the ancestor chain — not over the whole shelf. Numbers taken over a different
scope than the code walks are not wrong so much as unrelated, and they are easy
to quote by accident.

## Subjects

- **`cache/`** — node index build / persistence / staleness / query strategy.
  Backs [ADR-0040](../../docs/design/adr/0040-node-index-persisted-incremental-no-sqlite.md).

  ```powershell
  backend/.venv/Scripts/python.exe scripts/benchmark/cache/hierarchy_bench.py --regen
  backend/.venv/Scripts/python.exe scripts/benchmark/cache/hierarchy_bench.py weber
  ```
