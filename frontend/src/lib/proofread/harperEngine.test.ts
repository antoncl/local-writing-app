// Proofreading (ADR-0102 §2): Harper's lints as findings — spans taken as the
// UTF-16 offsets harper.js reports, each suggestion kind as a fix, the rule from
// `organizedLints` — and the engine's calls into the linter. The WASM never
// loads here; the linter and its lints are stand-ins of the same shape.
import { describe, expect, it, vi } from "vitest";
import { SuggestionKind } from "harper.js";
import { harperEngineFor, toFindings } from "./harperEngine";

type FakeSuggestion = { kind: () => SuggestionKind; get_replacement_text: () => string };
const suggestion = (kind: SuggestionKind, text = ""): FakeSuggestion => ({ kind: () => kind, get_replacement_text: () => text });

function lint(start: number, end: number, kind: string, message: string, suggestions: FakeSuggestion[] = []) {
  return {
    span: () => ({ start, end }),
    lint_kind: () => kind,
    message: () => message,
    suggestions: () => suggestions,
  } as never;
}

describe("toFindings", () => {
  it("takes the span as UTF-16 offsets, past an emoji too (measured on 3.0.0)", () => {
    const text = "We 🙂 saw teh cat";
    const at = text.indexOf("teh");
    const [finding] = toFindings({ SpellCheck: [lint(at, at + 3, "Spelling", "Did you mean “the”?")] });
    expect(text.slice(finding.from, finding.to)).toBe("teh");
    expect(finding).toMatchObject({ engine: "harper", ruleId: "SpellCheck", kind: "Spelling" });
  });

  it("turns each suggestion kind into a fix over the right range", () => {
    const [finding] = toFindings({
      Repeated: [
        lint(0, 2, "Repetition", "Repeated word", [
          suggestion(SuggestionKind.Replace, "a"),
          suggestion(SuggestionKind.Remove),
          suggestion(SuggestionKind.InsertAfter, ","),
        ]),
      ],
    });
    expect(finding.fixes).toEqual([
      { label: "a", from: 0, to: 2, insert: "a" },
      { label: "Remove", from: 0, to: 2, insert: "" },
      { label: "Insert “,”", from: 2, to: 2, insert: "," },
    ]);
  });

  it("orders findings from every rule by position", () => {
    const findings = toFindings({
      B: [lint(8, 13, "Style", "b")],
      A: [lint(0, 3, "Style", "a")],
    });
    expect(findings.map((f) => f.ruleId)).toEqual(["A", "B"]);
  });
});

describe("harperEngineFor", () => {
  it("lints as plaintext and skips blank text", async () => {
    const linter = { organizedLints: vi.fn(async () => ({})), clearWords: vi.fn(), importWords: vi.fn() };
    const engine = harperEngineFor(linter as never);
    await engine.lint("Some *prose*.");
    expect(linter.organizedLints).toHaveBeenCalledWith("Some *prose*.", { language: "plaintext" });
    expect(await engine.lint("   ")).toEqual([]);
    expect(linter.organizedLints).toHaveBeenCalledTimes(1);
  });

  it("replaces the added words rather than appending to them", async () => {
    const calls: string[] = [];
    const linter = {
      organizedLints: vi.fn(),
      clearWords: vi.fn(async () => void calls.push("clear")),
      importWords: vi.fn(async (words: string[]) => void calls.push(`import ${words.join(",")}`)),
    };
    const engine = harperEngineFor(linter as never);
    await engine.setWords(["Kael", "Kael's"]);
    await engine.setWords([]);
    expect(calls).toEqual(["clear", "import Kael,Kael's", "clear"]);
  });
});
