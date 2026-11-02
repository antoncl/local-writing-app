// Proofreading (ADR-0102 §6–§7): mirrors `backend/app/models/proofreading.py`.

export type ProofreadingDialect = "american" | "british" | "australian" | "canadian" | "indian";

/** One layer a word or rule can be read from and written to. */
export interface ProofreadingLayer {
  id: string;
  label: string;
  is_machine: boolean;
  /** The built-in Library: read-only; it carries the fiction default. */
  is_library: boolean;
  is_root: boolean;
  /** What this layer's own file says (the merged result is on the setup). */
  words: string[];
  rules: Record<string, boolean>;
  dialect: ProofreadingDialect | null;
}

/** The open project's merged proofreading setup. */
export interface ProofreadingSetup {
  words: string[];
  word_layers: Record<string, string[]>;
  rules: Record<string, boolean>;
  rule_layers: Record<string, string>;
  dialect: ProofreadingDialect;
  /** Library, machine, then the project chain, outermost first. */
  layers: ProofreadingLayer[];
  /** Node id -> ignore-here hashes (unsigned 64-bit, as decimal strings). */
  ignored: Record<string, string[]>;
}
