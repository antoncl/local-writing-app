// ADR-0075 §5 — the FE/BE parity gate.
//
// Drives `compileMatcher` (implicitContextMatcher.ts) against the
// hand-authored oracle at `spec/implicit-context-corpus.json`, shared with
// the backend's pytest counterpart (`test_implicit_context_parity.py`).
// Neither suite regenerates the corpus from a matcher (see its `_comment`).

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { compileMatcher } from "./implicitContextMatcher";
import type { LoreEntrySummary } from "@/lib/types";

const __dirname = dirname(fileURLToPath(import.meta.url));
const CORPUS_PATH = resolve(__dirname, "../../../../spec/implicit-context-corpus.json");

type CorpusEntity = { id: string; title: string; aliases: string[] };
type CorpusCase = {
  name: string;
  entities: CorpusEntity[];
  text: string;
  expected: { id: string; start: number; end: number; matchedText: string }[];
};

const corpus = JSON.parse(readFileSync(CORPUS_PATH, "utf-8")) as { cases: CorpusCase[] };

function toEntry(entity: CorpusEntity): LoreEntrySummary {
  return {
    id: entity.id,
    title: entity.title,
    entry_type: "",
    metadata: { aliases: entity.aliases },
    body: "",
  };
}

describe("implicitContextMatcher — ADR-0075 §5 parity corpus", () => {
  for (const c of corpus.cases) {
    it(c.name, () => {
      const matcher = compileMatcher(c.entities.map(toEntry));
      const hits = matcher.scan(c.text);

      const actual = hits
        .map((h) => [h.entryId, h.start, h.end, h.matchedText] as const)
        .sort((a, b) => a[1] - b[1]);
      const expected = c.expected
        .map((e) => [e.id, e.start, e.end, e.matchedText] as const)
        .sort((a, b) => a[1] - b[1]);

      expect(actual).toEqual(expected);
    });
  }
});
