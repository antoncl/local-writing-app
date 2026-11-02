// Proofreading (ADR-0102 §2): the Harper engine. The ONLY module that imports
// `harper.js` — the package calls its API "early access, not yet stable", so it
// is pinned exactly in package.json and an upgrade touches this file alone.
//
// Loaded with a dynamic import the first time the lens is switched on, so
// startup and the first-draft path never fetch the 20 MB binary. The slim
// binary, a separate asset the app serves itself: the "full" flavour loads the
// slim one AND a second 20 MB binary on top, and the slim one alone does all
// the lens needs (lints by rule, words, rule config, ignores by hash — checked
// in the browser, ADR-0102 Amendment 1).
import { Dialect, SuggestionKind, WorkerLinter, type Lint, type Linter, type Suggestion } from "harper.js";
import { slimBinary } from "harper.js/slimBinary";
import type { Finding, FindingFix, ProofreadEngine } from "@/lib/proofread/findings";

const ENGINE_ID = "harper";
// Harper's default is markdown, which would read the prose's own asterisks and
// underscores as markup; the editor hands it a block's plain text.
const LINT_OPTIONS = { language: "plaintext" } as const;

/** The parts of a lint the app reads — the shape `toFinding` converts. */
type LintLike = Pick<Lint, "span" | "lint_kind" | "message" | "suggestions">;

function fixLabel(kind: SuggestionKind, replacement: string): string {
  if (kind === SuggestionKind.Remove) return "Remove";
  if (kind === SuggestionKind.InsertAfter) return `Insert “${replacement}”`;
  return replacement;
}

function toFix(suggestion: Suggestion, from: number, to: number): FindingFix {
  const kind = suggestion.kind();
  const replacement = kind === SuggestionKind.Remove ? "" : suggestion.get_replacement_text();
  if (kind === SuggestionKind.InsertAfter) return { label: fixLabel(kind, replacement), from: to, to, insert: replacement };
  return { label: fixLabel(kind, replacement), from, to, insert: replacement };
}

/** One Harper lint as a finding in UTF-16 offsets into `text`.
 *
 *  harper.js 3.0.0 reports spans in UTF-16 code units — JS string indices —
 *  though the docs' Spans page says Unicode scalar values (that describes the
 *  Rust core). Measured in the browser on 2026-11-02: in "a 🙂 untill b" the
 *  span of "untill" is 5–11, which is its UTF-16 slice. An upgrade rechecks it
 *  (ADR-0102 Amendment 1). */
export function toFinding(ruleId: string, lint: LintLike): Finding {
  const { start: from, end: to } = lint.span();
  return {
    engine: ENGINE_ID,
    from,
    to,
    kind: lint.lint_kind(),
    ruleId,
    message: lint.message(),
    fixes: lint.suggestions().map((s) => toFix(s, from, to)),
  };
}

/** The lints `organizedLints` returns, keyed by rule, as findings. */
export function toFindings(byRule: Record<string, LintLike[]>): Finding[] {
  const findings: Finding[] = [];
  for (const [ruleId, lints] of Object.entries(byRule)) {
    for (const lint of lints) findings.push(toFinding(ruleId, lint));
  }
  return findings.sort((a, b) => a.from - b.from || a.to - b.to);
}

/** The engine over an already-constructed linter (tests pass a fake). */
export function harperEngineFor(linter: Pick<Linter, "organizedLints" | "clearWords" | "importWords">): ProofreadEngine {
  return {
    id: ENGINE_ID,
    async lint(text) {
      if (!text.trim()) return [];
      // `organizedLints` rather than `lint`: only it says which rule produced a
      // lint, which "stop checking this rule" (slice 2) needs.
      const byRule = await linter.organizedLints(text, LINT_OPTIONS);
      return toFindings(byRule);
    },
    async setWords(words) {
      await linter.clearWords();
      if (words.length > 0) await linter.importWords(words);
    },
  };
}

/** Start Harper in its worker. */
export async function createHarperEngine(): Promise<ProofreadEngine> {
  const linter = new WorkerLinter({ binary: slimBinary, dialect: Dialect.American });
  await linter.setup();
  // harper #3490: a WorkerLinter's default-on rules stay inactive until the
  // default config is read once after setup; setting it arms them as well.
  await linter.setLintConfig(await linter.getDefaultLintConfig());
  return harperEngineFor(linter);
}
