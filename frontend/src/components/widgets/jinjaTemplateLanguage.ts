import { StreamLanguage, type StreamParser } from "@codemirror/language";

// Highlighting for prompt templates (#2496), matching the engine that renders
// them (backend services/ai/templates.py): a Jinja sandbox with NO line
// statements, so only `{{ }}`, `{% %}` and `{# #}` are template code — a `#` in
// prose is just a Markdown heading. CodeMirror's stock jinja2 mode implements
// line statements, so a heading like `# WORKING PRINCIPLES (don't …)` turned the
// rest of the line into a tag, its apostrophe opened a string that ran on for
// lines, and words like "in" / "and" / "by" got keyword colour mid-prose.
//
// Prose is uncoloured, except a Markdown heading line (bold). Inside a tag:
// keywords, constants, strings, numbers, names and operators. A string lives
// only inside its tag, as in Jinja.

type Tag = "{{" | "{%" | "{#";

export interface TemplateState {
  /** The open tag, or null in prose. */
  tag: Tag | null;
  /** The quote of an open string inside the tag. */
  quote: "'" | '"' | null;
  /** This line is a Markdown heading (its prose is styled as one). */
  heading: boolean;
  /** The first word of the open `{% %}` statement (`raw`, `if`, …), or null. */
  stmt: string | null;
  /** Inside a `{% raw %}` block: literal text up to `{% endraw %}`. */
  raw: boolean;
}

const KEYWORDS = new Set([
  "if", "elif", "else", "endif", "for", "endfor", "in", "not", "and", "or", "is",
  "set", "endset", "do", "include", "import", "from", "as", "with", "without", "context",
  "endwith", "macro", "endmacro", "call", "endcall", "filter", "endfilter", "block",
  "endblock", "extends", "raw", "endraw", "role", "endrole", "recursive", "ignore", "missing",
]);
const CONSTANTS = new Set(["true", "false", "none", "True", "False", "None"]);
const CLOSER: Record<"{{" | "{%", RegExp> = { "{{": /^-?\}\}/, "{%": /^-?%\}/ };
const ENDRAW = /\{%-?\s*endraw\b/;

type Stream = Parameters<StreamParser<TemplateState>["token"]>[0];

function proseToken(stream: Stream, state: TemplateState): string | null {
  if (state.raw) {
    // Literal text: nothing is a tag until `{% endraw %}`.
    const at = stream.string.slice(stream.pos).search(ENDRAW);
    if (at !== 0) {
      if (at < 0) stream.skipToEnd();
      else stream.pos += at;
      return state.heading ? "heading" : null;
    }
    state.raw = false;
  }
  const opener = stream.match(/^\{[{%#]-?/) as RegExpMatchArray | null;
  if (opener) {
    const tag = opener[0].slice(0, 2) as Tag;
    state.tag = tag;
    return tag === "{#" ? "comment" : "meta";
  }
  // Up to the next tag opener (or the end of the line).
  do {
    if (!stream.match(/^[^{]+/)) stream.next();
  } while (!stream.eol() && !stream.match(/^\{[{%#]/, false));
  return state.heading ? "heading" : null;
}

function tagToken(stream: Stream, state: TemplateState): string | null {
  const tag = state.tag as Tag;
  if (tag === "{#") {
    // A comment runs to its `#}`, across lines.
    while (!stream.eol()) {
      if (stream.match("#}")) {
        state.tag = null;
        return "comment";
      }
      stream.next();
    }
    return "comment";
  }
  if (state.quote) {
    let escaped = false;
    while (!stream.eol()) {
      const ch = stream.next();
      if (ch === state.quote && !escaped) {
        state.quote = null;
        break;
      }
      escaped = !escaped && ch === "\\";
    }
    return "string";
  }
  if (stream.eatSpace()) return null;
  if (stream.match(CLOSER[tag])) {
    state.raw = tag === "{%" && state.stmt === "raw";
    state.tag = null;
    state.stmt = null;
    return "meta";
  }
  const ch = stream.peek();
  if (ch === "'" || ch === '"') {
    stream.next();
    state.quote = ch;
    return tagToken(stream, state);
  }
  if (stream.match(/^\d+(\.\d+)?/)) return "number";
  const word = stream.match(/^[A-Za-z_][A-Za-z0-9_]*/) as RegExpMatchArray | null;
  if (word) {
    if (tag === "{%" && state.stmt === null) state.stmt = word[0];
    if (CONSTANTS.has(word[0])) return "atom";
    if (KEYWORDS.has(word[0])) return "keyword";
    return "variableName";
  }
  stream.next();
  return "operator";
}

export const jinjaTemplateParser: StreamParser<TemplateState> = {
  name: "jinja-template",
  startState: () => ({ tag: null, quote: null, heading: false, stmt: null, raw: false }),
  copyState: (s) => ({ ...s }),
  token: (stream, state) => {
    // A Markdown heading is a line of prose that starts with `#`s and a space.
    if (stream.sol()) state.heading = state.tag === null && /^#{1,6}\s/.test(stream.string);
    return state.tag ? tagToken(stream, state) : proseToken(stream, state);
  },
  languageData: { commentTokens: { block: { open: "{#", close: "#}" } } },
};

export const jinjaTemplateLanguage = () => StreamLanguage.define(jinjaTemplateParser);
