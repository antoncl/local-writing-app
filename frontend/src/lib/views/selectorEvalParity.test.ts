// Frontend half of the cross-runtime selector-evaluator parity gate.
//
// Runs the shared corpus (spec/selector-eval-corpus.json) through the canonical
// frontend `evaluateView`. The backend half (backend/tests/test_selector_eval_parity.py)
// runs the SAME corpus through the Python `evaluate_selector_membership`. Both
// must return each case's `expected` verbatim, so the picker's live count and
// the AI's actual context can't silently drift (ADR-0074 slice 5). Add a case in
// the corpus and BOTH runtimes' gates must reproduce it.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { MetadataSchema, ViewSpec } from "@/lib/types";
import { evaluateView, type EvalNode } from "@/lib/views/evaluateView";

type CorpusNode = { id: string; entry_type: string; metadata?: Record<string, unknown> | null };
type CorpusCase = { name: string; expr: unknown; nodes: CorpusNode[]; expected: string[] };
type Corpus = { schema: { entry_types: Record<string, { parent?: string }> }; cases: CorpusCase[] };

const here = dirname(fileURLToPath(import.meta.url));
const corpusPath = resolve(here, "../../../../spec/selector-eval-corpus.json");
const corpus = JSON.parse(readFileSync(corpusPath, "utf-8")) as Corpus;

// Only the entry_types parent chain is load-bearing (type / descendants_of); the
// rest of MetadataSchema is irrelevant to membership, so a thin cast is enough —
// matching how evaluateView.test.ts constructs its SCHEMA.
const schema = {
  version: 1,
  entry_types: corpus.schema.entry_types,
  fields: {},
} as unknown as MetadataSchema;

// `kind` does not scope evaluateView — the nodes array IS the universe — so a
// constant kind is fine; each case's `type` leaves do any entry_type narrowing.
const memberIds = (expr: unknown, nodes: EvalNode[]): string[] =>
  evaluateView({ kind: "lore", expr } as ViewSpec, nodes, { schema }).nodes.map((n) => n.id);

describe("selector evaluator parity (shared corpus)", () => {
  for (const testCase of corpus.cases) {
    it(testCase.name, () => {
      const nodes: EvalNode[] = testCase.nodes.map((n) => ({
        id: n.id,
        entry_type: n.entry_type,
        title: n.id,
        metadata: n.metadata ?? {},
      }));
      expect(memberIds(testCase.expr, nodes)).toEqual(testCase.expected);
    });
  }

  it("corpus is non-trivial", () => {
    expect(corpus.cases.length).toBeGreaterThanOrEqual(12);
  });
});
