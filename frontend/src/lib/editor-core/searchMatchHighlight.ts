/** Search-match reveal in the prose editor (#1925).
 *
 *  Opening a search hit lands the writer on the match: every match of the
 *  query is marked in the opened editor and the clicked one — the N-th match
 *  in the node — is selected and scrolled into view. The editor finds the
 *  matches itself, with the one pattern the backend (`_compile_query` in
 *  `search.py`) and the Search pane's excerpt marks build, so no markdown
 *  offset ever has to be mapped to a ProseMirror position (the seam ADR-0085
 *  left as its own decision). The marks are a way in, not a mode: an edit or
 *  Escape clears them, and a new reveal replaces them.
 *
 *  The code body has a CodeMirror twin (`widgets/codeSearchReveal.ts`) that
 *  shares the pattern, the match scan and the classes. */
import { Extension } from "@tiptap/core";
import type { Node as PMNode } from "prosemirror-model";
import { Plugin, PluginKey, TextSelection, type EditorState } from "prosemirror-state";
import { Decoration, DecorationSet } from "prosemirror-view";

/** What a search hit's open carries into the editor. */
export type SearchReveal = {
  query: string;
  matchCase: boolean;
  wholeWord: boolean;
  /** Which match in the node — the hit's index among the node's body hits. */
  ordinal: number;
};

/** A half-open character (or document-position) range. */
export type MatchRange = { start: number; end: number };

export const SEARCH_MATCH_CLASS = "search-match";
export const SEARCH_MATCH_CURRENT_CLASS = "search-match-current";

/** The search pattern, built the way the backend builds its (`_compile_query`
 *  in `search.py`): a literal query, `whole_word` as lookarounds rather than
 *  `\b` so a query that starts or ends in punctuation still matches. Every
 *  frontend mark of a match must come from this, or it marks occurrences the
 *  backend never found (ADR-0085 §3 options). */
export function compileSearchPattern(query: string, matchCase: boolean, wholeWord: boolean): RegExp {
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const source = wholeWord ? `(?<!\\w)${escaped}(?!\\w)` : escaped;
  return new RegExp(source, matchCase ? "g" : "gi");
}

/** Every non-empty match of `pattern` in `text`, in order. */
export function findMatches(text: string, pattern: RegExp): MatchRange[] {
  const out: MatchRange[] = [];
  pattern.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) {
    if (match[0].length === 0) {
      pattern.lastIndex += 1;
      continue;
    }
    out.push({ start: match.index, end: match.index + match[0].length });
  }
  return out;
}

/** One run of characters in a textblock's text and where it sits in the doc. */
type Segment = { at: number; len: number; pos: number };

/** The text of one textblock as the writer reads it, with the map back to
 *  document positions: a text node contributes its text (so a match may
 *  cross a formatting boundary), an inline leaf — a mutation pill, a hard
 *  break — one placeholder character (so a match never spans one), and an
 *  inline node with content only its content. */
function blockText(block: PMNode, blockPos: number): { text: string; segments: Segment[] } {
  let text = "";
  const segments: Segment[] = [];
  const walk = (parent: PMNode, contentStart: number): void => {
    parent.forEach((child, offset) => {
      const pos = contentStart + offset;
      if (child.isText) {
        const run = child.text ?? "";
        segments.push({ at: text.length, len: run.length, pos });
        text += run;
      } else if (child.isLeaf) {
        segments.push({ at: text.length, len: 1, pos });
        text += "￼";
      } else {
        walk(child, pos + 1);
      }
    });
  };
  walk(block, blockPos + 1);
  return { text, segments };
}

/** The document position of a text offset — a start offset resolves inside
 *  the segment it opens, an end offset inside the one it closes, so a range
 *  never includes a nested node's boundary token. */
function posAt(segments: Segment[], offset: number, edge: "start" | "end"): number {
  for (const seg of segments) {
    const inside =
      edge === "start" ? offset >= seg.at && offset < seg.at + seg.len : offset > seg.at && offset <= seg.at + seg.len;
    if (inside) return seg.pos + (offset - seg.at);
  }
  throw new Error(`search reveal: offset ${offset} is outside the block`);
}

/** Every match of `pattern` in `doc`, as document-position ranges, in
 *  document order. Textblock by textblock: a match never crosses a block. */
export function scanDoc(doc: PMNode, pattern: RegExp): MatchRange[] {
  const ranges: MatchRange[] = [];
  doc.descendants((node, pos) => {
    if (!node.isTextblock) return true;
    const { text, segments } = blockText(node, pos);
    for (const match of findMatches(text, pattern)) {
      ranges.push({ start: posAt(segments, match.start, "start"), end: posAt(segments, match.end, "end") });
    }
    return false;
  });
  return ranges;
}

type RevealState = { active: boolean; decorations: DecorationSet };

const EMPTY: RevealState = { active: false, decorations: DecorationSet.empty };

const pluginKey = new PluginKey<RevealState>("search-match-highlight");

function decorate(doc: PMNode, ranges: MatchRange[], current: number): DecorationSet {
  return DecorationSet.create(
    doc,
    ranges.map((range, index) =>
      Decoration.inline(range.start, range.end, {
        class: index === current ? `${SEARCH_MATCH_CLASS} ${SEARCH_MATCH_CURRENT_CLASS}` : SEARCH_MATCH_CLASS,
      }),
    ),
  );
}

/** Whether a reveal is showing in `state`. */
export function searchRevealActive(state: EditorState): boolean {
  return pluginKey.getState(state)?.active ?? false;
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    searchMatchHighlight: {
      /** Mark every match of the query and select the `ordinal`-th; false —
       *  and nothing marked — when the document has no match. */
      revealSearchMatch: (reveal: SearchReveal) => ReturnType;
      clearSearchReveal: () => ReturnType;
    };
  }
}

export const SearchMatchHighlight = Extension.create({
  name: "searchMatchHighlight",

  addCommands() {
    return {
      revealSearchMatch:
        (reveal) =>
        ({ state, tr, dispatch, view }) => {
          const ranges = scanDoc(state.doc, compileSearchPattern(reveal.query, reveal.matchCase, reveal.wholeWord));
          if (ranges.length === 0) {
            tr.setMeta(pluginKey, EMPTY);
            return false;
          }
          // The corpus and the document can disagree on the count (markdown
          // syntax the editor renders rather than shows): the last match is
          // the nearest answer to an ordinal past the end.
          const current = Math.min(Math.max(reveal.ordinal, 0), ranges.length - 1);
          if (dispatch) {
            tr.setMeta(pluginKey, { active: true, decorations: decorate(state.doc, ranges, current) }).setSelection(
              TextSelection.create(tr.doc, ranges[current].start, ranges[current].end),
            );
            view.focus();
          }
          return true;
        },
      clearSearchReveal:
        () =>
        ({ tr }) => {
          tr.setMeta(pluginKey, EMPTY);
          return true;
        },
    };
  },

  addProseMirrorPlugins() {
    return [
      new Plugin<RevealState>({
        key: pluginKey,
        state: {
          init: () => EMPTY,
          apply: (tr, old) => {
            const next = tr.getMeta(pluginKey) as RevealState | undefined;
            if (next) return next;
            // An edit ends the reveal: the marks were a way in, not a mode.
            return tr.docChanged ? EMPTY : old;
          },
        },
        view: () => ({
          update: (view, previous) => {
            const now = pluginKey.getState(view.state);
            if (!now?.active || now === pluginKey.getState(previous)) return;
            // A new reveal: bring the current match to the middle of the view,
            // with its context around it — like the embedded-TODO highlight,
            // not ProseMirror's own edge-of-view scroll.
            view.dom.querySelector(`.${SEARCH_MATCH_CURRENT_CLASS}`)?.scrollIntoView?.({ block: "center" });
          },
        }),
        props: {
          decorations: (state) => pluginKey.getState(state)?.decorations ?? DecorationSet.empty,
          handleKeyDown: (view, event) => {
            if (event.key !== "Escape" || !pluginKey.getState(view.state)?.active) return false;
            view.dispatch(view.state.tr.setMeta(pluginKey, EMPTY));
            return true;
          },
        },
      }),
    ];
  },
});
