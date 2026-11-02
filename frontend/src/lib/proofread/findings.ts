// Proofreading (ADR-0102 §3): what an engine hands the editor. An engine lints
// one text block's plain text and returns findings in UTF-16 offsets into that
// text (JS string indices); the highlight layer maps them onto the document.
// Harper is the first engine; LanguageTool (step 2) and #2646's story-aware
// checks return the same shape, so they share the one layer and popover.
import type { ProofreadingDialect } from "@/lib/types";

/** One way to fix a finding: put `insert` over `[from, to)` of the block text.
 *  A removal inserts ""; an insertion has `from === to`. */
export type FindingFix = { label: string; from: number; to: number; insert: string };

export type Finding = {
  /** Which engine produced it, e.g. "harper". */
  engine: string;
  from: number;
  to: number;
  /** The engine's category (Harper's `LintKind`, e.g. "Spelling"). */
  kind: string;
  /** The engine's rule name, e.g. Harper's "SpellCheck". */
  ruleId: string;
  message: string;
  fixes: FindingFix[];
};

/** What the writer's files tell an engine besides words (ADR-0102 §5). */
export type EngineConfig = {
  /** Rule name -> on/off, merged down the chain. Names it lacks are skipped. */
  rules: Record<string, boolean>;
  dialect: ProofreadingDialect;
  /** Every ignore-here hash the open project holds. */
  ignored: string[];
};

/** An engine as the lens drives it: lint a block's text, and take the words,
 *  rules and ignores it must honour. */
export interface ProofreadEngine {
  readonly id: string;
  lint(text: string): Promise<Finding[]>;
  setWords(words: string[]): Promise<void>;
  configure(config: EngineConfig): Promise<void>;
  /** The ignore-here hashes of the spot `finding` covers in `text`, the block
   *  it was found in: one per finding there, the ones the engine hid behind it
   *  included. Empty when the engine finds nothing there. */
  hashesOf(text: string, finding: Finding): Promise<string[]>;
}

/** Whether a finding draws as a spelling mark or as any other kind. */
export function isSpelling(finding: Pick<Finding, "kind">): boolean {
  return finding.kind === "Spelling" || finding.kind === "Typo";
}
