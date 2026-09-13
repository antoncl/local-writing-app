// The code body's half of the search reveal (#1925) — the CodeMirror twin of
// editor-core's `SearchMatchHighlight`: the same pattern, the same match
// scan, the same classes, over a CodeMirror document. An edit or Escape
// clears the marks; a new reveal replaces them.
import { EditorSelection, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, keymap, type DecorationSet } from "@codemirror/view";
import {
  compileSearchPattern,
  findMatches,
  SEARCH_MATCH_CLASS,
  SEARCH_MATCH_CURRENT_CLASS,
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

/** Mark every match of the query and select the `ordinal`-th (the last, for
 *  an ordinal past the end); false — and nothing marked — when the document
 *  has no match. */
export function revealSearchMatch(view: EditorView, reveal: SearchReveal): boolean {
  const matches = findMatches(
    view.state.doc.toString(),
    compileSearchPattern(reveal.query, reveal.matchCase, reveal.wholeWord),
  );
  if (matches.length === 0) {
    view.dispatch({ effects: setReveal.of(Decoration.none) });
    return false;
  }
  const at = Math.min(Math.max(reveal.ordinal, 0), matches.length - 1);
  const target = matches[at];
  view.dispatch({
    effects: [
      setReveal.of(Decoration.set(matches.map((m, i) => (i === at ? current : plain).range(m.start, m.end)))),
      EditorView.scrollIntoView(target.start, { y: "center" }),
    ],
    selection: EditorSelection.range(target.start, target.end),
  });
  view.focus();
  return true;
}
