// Code-completion for the Jinja prompt-template editor (#30).
//
// A CodeMirror completion source over the prompt vocabulary. The static half
// (variables, helpers, filters, tags) comes from the generated manifest
// (promptVocab.json — reference.md is its single source, #1270), so it can never
// drift from what the backend registers. `inputs.<name>` completes from the
// prompt's own declared inputs, read live through a getter.
//
// Scope (slice 1): the manifest vocabulary + declared inputs. Schema-driven field
// names (`scene.<field>`, `entry(inputs.x).<field>`) are a follow-up — this slice
// deliberately declines to complete past a `.` so it never guesses a wrong field.

import type { Completion, CompletionContext, CompletionResult, CompletionSource } from "@codemirror/autocomplete";

import promptVocabData from "@/lib/generated/promptVocab.json";
import type { PromptInputDefinition } from "@/lib/types";

type VocabKind = "variable" | "helper" | "filter" | "tag";
type VocabSymbol = { name: string; kind: VocabKind; signature: string; summary: string };

const VOCAB = (promptVocabData as { symbols: VocabSymbol[] }).symbols;

// CodeMirror's completion `type` drives the little icon shown beside each option.
const ICON: Record<VocabKind, string> = {
  variable: "variable",
  helper: "function",
  filter: "function",
  tag: "keyword",
};

function toCompletion(symbol: VocabSymbol): Completion {
  return {
    label: symbol.name,
    type: ICON[symbol.kind],
    detail: symbol.signature !== symbol.name ? symbol.signature : undefined,
    info: symbol.summary,
  };
}

const EXPRESSION_OPTIONS = VOCAB.filter((s) => s.kind === "variable" || s.kind === "helper").map(toCompletion);
const FILTER_OPTIONS = VOCAB.filter((s) => s.kind === "filter").map(toCompletion);
const TAG_OPTIONS = VOCAB.filter((s) => s.kind === "tag").map(toCompletion);

const VALID_WORD = /^\w*$/;

type Region = { kind: "expr" | "tag"; from: number };

// The innermost `{{`/`{%` still open at `pos` (windowed — a template block is
// never remotely this long). Returns null outside any expression/tag.
function openRegion(context: CompletionContext): Region | null {
  const from = Math.max(0, context.pos - 4000);
  const text = context.state.sliceDoc(from, context.pos);
  const delimiters = /\{\{|\{%|\}\}|%\}/g;
  let open: Region | null = null;
  let match: RegExpExecArray | null;
  while ((match = delimiters.exec(text)) !== null) {
    if (match[0] === "{{") open = { kind: "expr", from: from + match.index };
    else if (match[0] === "{%") open = { kind: "tag", from: from + match.index };
    else open = null; // a `}}` / `%}` closes whatever was open
  }
  return open;
}

/**
 * Build the completion source. `getInputs` is read on every keystroke so the
 * `inputs.<name>` list stays live as the prompt's declared inputs change.
 */
export function makePromptCompletionSource(getInputs: () => PromptInputDefinition[]): CompletionSource {
  return (context: CompletionContext): CompletionResult | null => {
    const region = openRegion(context);
    if (region === null) return null;
    const head = context.state.sliceDoc(region.from, context.pos);

    // `inputs.<name>` — also fires inside `entry(inputs.…)`.
    const inputAccess = context.matchBefore(/inputs\.\w*/);
    if (inputAccess) {
      const dot = inputAccess.text.indexOf(".");
      const options = getInputs().map(
        (input): Completion => ({ label: input.name, type: "variable", detail: input.label || undefined }),
      );
      return { from: inputAccess.from + dot + 1, options, validFor: VALID_WORD };
    }

    // `{% <tag>` — only while the tag keyword itself is being typed.
    if (region.kind === "tag" && /^\{%\s*\w*$/.test(head)) {
      const word = context.matchBefore(/\w*$/);
      return { from: word ? word.from : context.pos, options: TAG_OPTIONS, validFor: VALID_WORD };
    }

    // `value | <filter>`.
    const pipe = context.matchBefore(/\|\s*\w*/);
    if (pipe) {
      const word = context.matchBefore(/\w*$/);
      return { from: word ? word.from : context.pos, options: FILTER_OPTIONS, validFor: VALID_WORD };
    }

    // Member access (`scene.`, `entry(x).`, …) is the schema-driven follow-up —
    // decline rather than offer the wrong (top-level) names after a dot.
    if (context.matchBefore(/[\w)\]"']\.\w*/)) return null;

    // A bare identifier in an expression (or a tag's expression part) → the
    // variables and helpers.
    const word = context.matchBefore(/\w+/);
    if (!word && !context.explicit) return null;
    return { from: word ? word.from : context.pos, options: EXPRESSION_OPTIONS, validFor: VALID_WORD };
  };
}
