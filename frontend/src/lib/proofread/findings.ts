// Proofreading (ADR-0102 §3): what an engine hands the editor. An engine lints
// one text block's plain text and returns findings in UTF-16 offsets into that
// text (JS string indices); the highlight layer maps them onto the document.
// Harper is the first engine; LanguageTool (step 2) and #2646's story-aware
// checks return the same shape, so they share the one layer and popover.

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

/** An engine as the lens drives it: lint a block's text, and take the words it
 *  must accept. */
export interface ProofreadEngine {
  readonly id: string;
  lint(text: string): Promise<Finding[]>;
  setWords(words: string[]): Promise<void>;
}

/** Whether a finding draws as a spelling mark or as any other kind. */
export function isSpelling(finding: Pick<Finding, "kind">): boolean {
  return finding.kind === "Spelling" || finding.kind === "Typo";
}
