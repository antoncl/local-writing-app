// The code body's half of the search reveal (#1925) — the CodeMirror twin of
// editor-core's `SearchMatchHighlight`: the same pattern, the same match
// scan and choice, the same classes, over a CodeMirror document. An edit or
// Escape clears the marks; a new reveal replaces them.
import { EditorSelection, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, keymap, type DecorationSet } from "@codemirror/view";
import {
  chooseMatch,
  compileSearchPattern,
  findMatchesInContext,
  SEARCH_MATCH_CLASS,
  SEARCH_MATCH_CURRENT_CLASS,
  type MatchContext,
  type SearchReveal,
} from "@/lib/editor-core/searchMatchHighlight";

const setReveal = StateEffect.define<DecorationSet>();

const revealField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(marks, tr) {
    for (const effect of tr.effects) if (effect.is(setReveal)) return effect.value;
    return tr.docChanged ? Decoration.none : marks;
  },
  provide: (field) => EditorView.decorations.from(field),
});

// Registered after basicSetup, so its own Escape bindings (close a completion,
// the search panel) run first; they return false when nothing of theirs is open.
const escapeClears = keymap.of([
  {
    key: "Escape",
    run: (view) => {
      if (view.state.field(revealField).size === 0) return false;
      view.dispatch({ effects: setReveal.of(Decoration.none) });
      return true;
    },
  },
]);

/** The extension a CodeEditor registers. */
export const searchReveal = [revealField, escapeClears];

const plain = Decoration.mark({ class: SEARCH_MATCH_CLASS });
const current = Decoration.mark({ class: `${SEARCH_MATCH_CLASS} ${SEARCH_MATCH_CURRENT_CLASS}` });

/** The matches line by line, so a neighbourhood never runs past the line —
 *  the excerpt it is compared with is one line's. */
function scanLines(view: EditorView, pattern: RegExp): MatchContext[] {
  const matches: MatchContext[] = [];
  const doc = view.state.doc;
  for (let n = 1; n <= doc.lines; n += 1) {
    const line = doc.line(n);
    for (const match of findMatchesInContext(line.text, pattern)) {
      matches.push({ ...match, start: line.from + match.start, end: line.from + match.end });
    }
  }
  return matches;
}

/** Mark every match of the query and put the caret at the hit's; false —
 *  and nothing marked — when the document has no match. */
export function revealSearchMatch(view: EditorView, reveal: SearchReveal): boolean {
  const matches = scanLines(view, compileSearchPattern(reveal.query, reveal.matchCase, reveal.wholeWord));
  if (matches.length === 0) {
    if (view.state.field(revealField).size > 0) view.dispatch({ effects: setReveal.of(Decoration.none) });
    return false;
  }
  const at = chooseMatch(matches, reveal);
  const target = matches[at];
  view.dispatch({
    effects: [
      setReveal.of(Decoration.set(matches.map((m, i) => (i === at ? current : plain).range(m.start, m.end)))),
      EditorView.scrollIntoView(target.start, { y: "center" }),
    ],
    selection: EditorSelection.cursor(target.start),
  });
  view.focus();
  return true;
}
