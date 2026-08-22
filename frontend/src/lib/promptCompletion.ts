// Code-completion for the Jinja prompt-template editor (#30).
//
// A CodeMirror completion source over the prompt vocabulary. The static half
// (variables, helpers, filters, tags) comes from the generated manifest
// (promptVocab.json — reference.md is its single source, #1270), so it can never
// drift from what the backend registers. `inputs.<name>` completes from the
// prompt's own declared inputs, read live through a getter.
//
// Field names past a `.` (`scene.<field>`, `project.<field>`,
// `entry(inputs.x).<field>`) are resolved from the live metadata schema; a base
// whose type can't be known statically (a literal `entry("id")`, a reference
// chain) declines rather than guessing a wrong field.

import type { Completion, CompletionContext, CompletionResult, CompletionSource } from "@codemirror/autocomplete";

import promptVocabData from "@/lib/generated/promptVocab.json";
import type { MetadataSchema, NodePickerConfig, PromptInputDefinition } from "@/lib/types";
import { pickerMembership } from "@/lib/utils/pickerSources";

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

// The role tag takes a fixed enum, not an expression. Parse the values straight
// out of its documented signature (`{% role "system"|"user"|"assistant" %}`) so
// they stay in sync with the manifest rather than being hardcoded here.
const ROLE_SIGNATURE = VOCAB.find((s) => s.kind === "tag" && s.name === "role")?.signature ?? "";
const ROLE_OPTIONS: Completion[] = [...ROLE_SIGNATURE.matchAll(/"(\w+)"/g)].map((m) => ({
  label: `"${m[1]}"`,
  type: "constant",
}));

const VALID_WORD = /^\w*$/;
const VALID_ROLE = /^"?\w*$/;

// --- schema-driven field names ----------------------------------------------

// The always-present node intrinsics (reference.md's degrade-to set), offered on
// any resolvable node base alongside its schema fields.
const INTRINSIC_FIELDS: Completion[] = ["title", "body", "entry_type", "id"].map((name) => ({
  label: name,
  type: "property",
  detail: "intrinsic",
}));

// Well-known entry_type keys — the app uses these literals directly (no constant).
const SCENE_TYPE = "manuscript:scene";
const PROJECT_TYPE = "project:project";

function fieldOptions(schema: MetadataSchema, entryType: string): Completion[] {
  const options: Completion[] = [];
  for (const id of schema.entry_types[entryType]?.fields ?? []) {
    const field = schema.fields[id];
    // Skip what a template can't meaningfully read: computed fields, the
    // intrinsics (offered separately), and fields hidden by default.
    if (!field || field.type === "computed" || field.category === "intrinsic" || field.hidden) continue;
    options.push({
      label: id,
      type: "property",
      detail: field.name !== id ? field.name : undefined,
      info: field.description ?? undefined,
    });
  }
  return options;
}

// The entry_type a member-access base resolves to, or null when it can't be known
// statically (an untyped/ambiguous input, a literal id, a reference chain).
function resolveEntryType(base: string, inputs: PromptInputDefinition[], schema: MetadataSchema): string | null {
  if (base === "scene") return schema.entry_types[SCENE_TYPE] ? SCENE_TYPE : null;
  if (base === "project") return schema.entry_types[PROJECT_TYPE] ? PROJECT_TYPE : null;
  const inputName = base.match(/^entry\(\s*inputs\.(\w+)\s*\)$/)?.[1];
  if (inputName) {
    const target = inputs.find((input) => input.name === inputName)?.target;
    if (!target) return null;
    const fqns = Object.values(pickerMembership(target as unknown as NodePickerConfig).entryTypes).flat();
    return fqns.length === 1 ? fqns[0] : null; // one unambiguous type, or decline
  }
  return null;
}

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
 * Build the completion source. `getInputs` and `getSchema` are read on every
 * keystroke so `inputs.<name>` and `<node>.<field>` stay live as the prompt's
 * declared inputs and the project schema change.
 */
export function makePromptCompletionSource(
  getInputs: () => PromptInputDefinition[],
  getSchema: () => MetadataSchema | null,
): CompletionSource {
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

    if (region.kind === "tag") {
      // `{% <tag>` — the tag keyword itself is still being typed.
      if (/^\{%\s*\w*$/.test(head)) {
        const word = context.matchBefore(/\w*$/);
        return { from: word ? word.from : context.pos, options: TAG_OPTIONS, validFor: VALID_WORD };
      }
      // Past the keyword — `role` takes a fixed enum, so offer only its values,
      // never the whole expression vocabulary. Every other tag argument wraps an
      // expression (`do`, `if`, `for`, `set`, …), so it falls through to
      // expression completion below.
      const keyword = head.match(/^\{%\s*(\w+)/)?.[1];
      if (keyword === "role") {
        const partial = context.matchBefore(/"?\w*/);
        return { from: partial ? partial.from : context.pos, options: ROLE_OPTIONS, validFor: VALID_ROLE };
      }
    }

    // `value | <filter>`.
    const pipe = context.matchBefore(/\|\s*\w*/);
    if (pipe) {
      const word = context.matchBefore(/\w*$/);
      return { from: word ? word.from : context.pos, options: FILTER_OPTIONS, validFor: VALID_WORD };
    }

    // Member access `<base>.<partial>` — offer the base type's fields when the
    // type resolves (scene / project / a typed `entry(inputs.x)`), otherwise
    // decline (never offer top-level names after a dot).
    if (context.matchBefore(/[\w)\]"']\.\w*/)) {
      const typed = context.matchBefore(/(?:scene|project|entry\([^)]*\))\.\w*/);
      const schema = getSchema();
      if (typed && schema) {
        const dot = typed.text.lastIndexOf(".");
        const entryType = resolveEntryType(typed.text.slice(0, dot), getInputs(), schema);
        if (entryType) {
          return {
            from: typed.from + dot + 1,
            options: [...INTRINSIC_FIELDS, ...fieldOptions(schema, entryType)],
            validFor: VALID_WORD,
          };
        }
      }
      return null;
    }

    // A bare identifier in an expression (or a tag's expression part) → the
    // variables and helpers.
    const word = context.matchBefore(/\w+/);
    if (!word && !context.explicit) return null;
    return { from: word ? word.from : context.pos, options: EXPRESSION_OPTIONS, validFor: VALID_WORD };
  };
}
