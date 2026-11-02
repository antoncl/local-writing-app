// Proofreading (ADR-0102 §2): Harper's lints as findings — spans taken as the
// UTF-16 offsets harper.js reports, each suggestion kind as a fix, the rule from
// `organizedLints` — and the engine's calls into the linter. The WASM never
// loads here; the linter and its lints are stand-ins of the same shape.
import { describe, expect, it, vi } from "vitest";
import { Dialect, SuggestionKind } from "harper.js";
import { harperEngineFor, mergedRules, toFindings } from "./harperEngine";

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

/** A linter stand-in with every call the engine makes. */
function fakeLinter() {
  return {
    lint: vi.fn(async (): Promise<never[]> => []),
    organizedLints: vi.fn(async (): Promise<Record<string, never[]>> => ({})),
    clearWords: vi.fn(async () => undefined),
    importWords: vi.fn(async () => undefined),
    setLintConfig: vi.fn(async () => undefined),
    setDialect: vi.fn(async () => undefined),
    clearIgnoredLints: vi.fn(async () => undefined),
    ignoreLintHash: vi.fn(async () => undefined),
    contextHash: vi.fn(async () => 18446744073709551615n),
  };
}

describe("mergedRules", () => {
  it("puts the writer's switches over Harper's defaults and skips names it lacks", () => {
    expect(mergedRules({ SpellCheck: true, OxfordComma: true }, { OxfordComma: false, RetiredRule: false })).toEqual({
      SpellCheck: true,
      OxfordComma: false,
    });
  });
});

describe("harperEngineFor", () => {
  it("configures rules, dialect and ignores, replacing earlier ignores", async () => {
    const linter = fakeLinter();
    const engine = harperEngineFor(linter as never, { SpellCheck: true, Hedging: true });
    await engine.configure({ rules: { Hedging: false }, dialect: "british", ignored: ["18446744073709551615", "7"] });
    expect(linter.setLintConfig).toHaveBeenCalledWith({ SpellCheck: true, Hedging: false });
    expect(linter.setDialect).toHaveBeenCalledWith(Dialect.British);
    expect(linter.clearIgnoredLints).toHaveBeenCalled();
    // Exact as a bigint: a JS number would round the largest u64.
    expect(linter.ignoreLintHash.mock.calls.map((c) => (c as unknown[])[0])).toEqual([18446744073709551615n, 7n]);
  });

  it("hashes every lint at the finding's spot, the hidden overlapping ones included", async () => {
    const linter = fakeLinter();
    // Two rules flag "untill"; Harper's overlap removal would show only one.
    const spelling = lint(4, 10, "Spelling", "until?");
    const wordChoice = lint(4, 10, "WordChoice", "distill?");
    const elsewhere = lint(11, 18, "Spelling", "?");
    linter.lint.mockResolvedValueOnce([spelling, wordChoice, elsewhere] as never);
    linter.contextHash.mockResolvedValueOnce(1n).mockResolvedValueOnce(18446744073709551615n);
    const engine = harperEngineFor(linter as never);
    const finding = toFindings({ WrongNegative: [wordChoice] })[0];
    expect(await engine.hashesOf("Then untill mornin", finding)).toEqual(["1", "18446744073709551615"]);
    expect(linter.lint).toHaveBeenCalledWith("Then untill mornin", { language: "plaintext", dedup: false });
    expect(linter.contextHash.mock.calls.map((c) => (c as unknown[])[1])).toEqual([spelling, wordChoice]);
  });

  it("lints as plaintext and skips blank text", async () => {
    const linter = fakeLinter();
    const engine = harperEngineFor(linter as never);
    await engine.lint("Some *prose*.");
    expect(linter.organizedLints).toHaveBeenCalledWith("Some *prose*.", { language: "plaintext" });
    expect(await engine.lint("   ")).toEqual([]);
    expect(linter.organizedLints).toHaveBeenCalledTimes(1);
  });

  it("replaces the added words rather than appending to them", async () => {
    const calls: string[] = [];
    const linter = {
      ...fakeLinter(),
      clearWords: vi.fn(async () => void calls.push("clear")),
      importWords: vi.fn(async (words: string[]) => void calls.push(`import ${words.join(",")}`)),
    };
    const engine = harperEngineFor(linter as never);
    await engine.setWords(["Kael", "Kael's"]);
    await engine.setWords([]);
    expect(calls).toEqual(["clear", "import Kael,Kael's", "clear"]);
  });
});
