import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

// House syntax palette for the code surface (CodeEditor / prompt + JSON bodies).
//
// `basicSetup` ships CodeMirror's `defaultHighlightStyle` as a FALLBACK, and its
// token colors are fixed hues meant for a white page (#708/#256/#404740/…), so a
// Jinja/JSON body's highlighted tokens ({{ }} vars, {% %} tags, strings, {# #}
// comments) rendered dark-on-dark in dark mode (base text was fine — it uses
// var(--text)). Registering a NON-fallback style overrides the default entirely;
// its colors are theme tokens (styles.css --syntax-*), so they follow the active
// theme live with no reconfigure. Any tag left unstyled falls through to the
// themed base color — so this cannot regress into dark-on-dark.
//
// Built once at module load (the style is static — colors are CSS vars, nothing
// varies per editor instance), then shared by every CodeEditor.
const codeHighlightStyle = HighlightStyle.define([
  {
    tag: [t.keyword, t.controlKeyword, t.operatorKeyword, t.definitionKeyword, t.moduleKeyword],
    color: "var(--syntax-keyword)",
  },
  {
    tag: [t.name, t.variableName, t.special(t.variableName), t.propertyName, t.labelName],
    color: "var(--syntax-name)",
  },
  { tag: [t.string, t.special(t.string), t.character], color: "var(--syntax-string)" },
  { tag: [t.number, t.integer, t.float, t.bool, t.atom, t.null], color: "var(--syntax-number)" },
  {
    tag: [t.comment, t.lineComment, t.blockComment, t.docComment],
    color: "var(--syntax-comment)",
    fontStyle: "italic",
  },
  {
    tag: [t.operator, t.punctuation, t.bracket, t.brace, t.paren, t.separator, t.meta, t.tagName, t.angleBracket],
    color: "var(--syntax-punct)",
  },
]);

export const codeSyntaxHighlighting = syntaxHighlighting(codeHighlightStyle);
