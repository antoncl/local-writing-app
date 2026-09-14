/** Search-match reveal in the prose editor (#1925).
 *
 *  Opening a search hit lands the writer on the match: every match of the
 *  query is marked in the opened editor and the clicked one is brought to the
 *  middle of the view with the caret at its start. The editor finds the
 *  matches itself, with the one pattern the backend (`_compile_query` in
 *  `search.py`) and the Search pane's excerpt marks build, and identifies the
 *  hit's match by its neighbourhood (`chooseMatch`), so no markdown offset
 *  ever has to be mapped to a ProseMirror position (the seam ADR-0085 left as
 *  its own decision). The marks are a way in, not a mode: an edit or Escape
 *  clears them, and a new reveal replaces them.
 *
 *  The code body has a CodeMirror twin (`widgets/codeSearchReveal.ts`) that
 *  shares the pattern, the match scan, the choice and the classes. */
import { Extension } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { escapeRegex } from "./implicitContextMatcher";

/** What a search hit's open carries into the editor. */
export type SearchReveal = {
  query: string;
  matchCase: boolean;
  wholeWord: boolean;
  /** The hit's excerpt: the text around the match on its line, as the
   *  corpus holds it — the match's neighbourhood, which identifies it. */
  excerpt: string;
  /** The hit's index among its node's body hits — the tie-breaker when two
   *  matches have the same neighbourhood. */
  ordinal: number;
};

/** A half-open character (or document-position) range. */
export type MatchRange = { start: number; end: number };

/** A match with the text around it — up to `CONTEXT_CHARS` each side, and
 *  never past the block (a line) it sits in. */
export type MatchContext = MatchRange & { before: string; after: string };

export const SEARCH_MATCH_CLASS = "search-match";
export const SEARCH_MATCH_CURRENT_CLASS = "search-match-current";

/** Longer than the backend's excerpt window on either side of the match. */
export const CONTEXT_CHARS = 80;

/** The search pattern, built the way the backend builds its (`_compile_query`
 *  in `search.py`): a literal query, `whole_word` as lookarounds rather than
 *  `\b` so a query that starts or ends in punctuation still matches. Word
 *  characters are Unicode's letters, digits and the underscore — what
 *  Python's `\w` matches — not JavaScript's ASCII `\w`, or the edges of an
 *  accented word would differ on the two sides of the wire. Every frontend
 *  mark of a match must come from this, or it marks occurrences the backend
 *  never found (ADR-0085 §3 options). */
export function compileSearchPattern(query: string, matchCase: boolean, wholeWord: boolean): RegExp {
  const escaped = escapeRegex(query);
  const source = wholeWord ? `(?<![\\p{L}\\p{N}_])${escaped}(?![\\p{L}\\p{N}_])` : escaped;
  return new RegExp(source, matchCase ? "gu" : "giu");
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

/** The matches of `pattern` in one line of text, each with its neighbourhood. */
export function findMatchesInContext(text: string, pattern: RegExp): MatchContext[] {
  return findMatches(text, pattern).map((match) => ({
    ...match,
    before: text.slice(Math.max(0, match.start - CONTEXT_CHARS), match.start),
    after: text.slice(match.end, match.end + CONTEXT_CHARS),
  }));
}

function commonSuffix(a: string, b: string): number {
  let n = 0;
  while (n < a.length && n < b.length && a[a.length - 1 - n] === b[b.length - 1 - n]) n += 1;
  return n;
}

function commonPrefix(a: string, b: string): number {
  let n = 0;
  while (n < a.length && n < b.length && a[n] === b[n]) n += 1;
  return n;
}

/** Which of the editor's matches the hit is.
 *
 *  The hit's ordinal among its node's body hits would be exact if the editor
 *  showed the corpus body as it is; it does not — a link's URL, a TODO or a
 *  mutation comment are text in the corpus and an attribute or a pill in the
 *  editor — so the counts can disagree and an ordinal can name the wrong
 *  occurrence. The match's neighbourhood survives the rendering: the hit's
 *  excerpt is the text around it on its line, and the chosen match is the
 *  one whose own surroundings agree with the excerpt the longest (the text
 *  before the match, read backwards, plus the text after it). The ordinal
 *  breaks a tie — two matches with the same neighbourhood, as in a repeated
 *  sentence. Returns -1 for no candidates. */
export function chooseMatch(candidates: MatchContext[], reveal: SearchReveal): number {
  if (candidates.length === 0) return -1;
  const pattern = compileSearchPattern(reveal.query, reveal.matchCase, reveal.wholeWord);
  const anchors = findMatchesInContext(reveal.excerpt, pattern);
  let best = -1;
  let bestScore = -1;
  let bestDistance = Infinity;
  candidates.forEach((candidate, index) => {
    let score = 0;
    for (const anchor of anchors) {
      score = Math.max(
        score,
        commonSuffix(anchor.before, candidate.before) + commonPrefix(anchor.after, candidate.after),
      );
    }
    const distance = Math.abs(index - reveal.ordinal);
    if (score > bestScore || (score === bestScore && distance < bestDistance)) {
      best = index;
      bestScore = score;
      bestDistance = distance;
    }
  });
  return best;
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

/** The document position of the character at a text offset. */
function posAt(segments: Segment[], offset: number): number {
  for (const seg of segments) {
    if (offset >= seg.at && offset < seg.at + seg.len) return seg.pos + (offset - seg.at);
  }
  throw new Error(`search reveal: offset ${offset} is outside the block`);
}

/** Every match of `pattern` in `doc`, as document-position ranges with their
 *  neighbourhoods, in document order. Textblock by textblock: a match never
 *  crosses a block. */
export function scanDoc(doc: PMNode, pattern: RegExp): MatchContext[] {
  const matches: MatchContext[] = [];
  doc.descendants((node, pos) => {
    if (!node.isTextblock) return true;
    const { text, segments } = blockText(node, pos);
    for (const match of findMatchesInContext(text, pattern)) {
      // The end is the position after the match's last character, so a
      // range never includes a nested node's boundary token.
      matches.push({ ...match, start: posAt(segments, match.start), end: posAt(segments, match.end - 1) + 1 });
    }
    return false;
  });
  return matches;
}

/** The plugin's state: the marks, `DecorationSet.empty` while nothing is revealed. */
const pluginKey = new PluginKey<DecorationSet>("search-match-highlight");

function decorate(doc: PMNode, matches: MatchRange[], current: number): DecorationSet {
  return DecorationSet.create(
    doc,
    matches.map((match, index) =>
      Decoration.inline(match.start, match.end, {
        class: index === current ? `${SEARCH_MATCH_CLASS} ${SEARCH_MATCH_CURRENT_CLASS}` : SEARCH_MATCH_CLASS,
      }),
    ),
  );
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    searchMatchHighlight: {
      /** Mark every match of the query and put the caret at the hit's; false
       *  — and nothing marked — when the document has no match. */
      revealSearchMatch: (reveal: SearchReveal) => ReturnType;
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
          const matches = scanDoc(state.doc, compileSearchPattern(reveal.query, reveal.matchCase, reveal.wholeWord));
          if (matches.length === 0) {
            tr.setMeta(pluginKey, DecorationSet.empty);
            return false;
          }
          const current = chooseMatch(matches, reveal);
          if (dispatch) {
            // The caret, not a selection: a reveal is a way in, and a selected
            // match would arm the next keystroke to replace it.
            tr.setMeta(pluginKey, decorate(state.doc, matches, current)).setSelection(
              TextSelection.create(tr.doc, matches[current].start),
            );
            view.focus();
          }
          return true;
        },
    };
  },

  addProseMirrorPlugins() {
    return [
      new Plugin<DecorationSet>({
        key: pluginKey,
        state: {
          init: () => DecorationSet.empty,
          apply: (tr, old) => {
            const next = tr.getMeta(pluginKey) as DecorationSet | undefined;
            if (next) return next;
            // An edit ends the reveal: the marks were a way in, not a mode.
            return tr.docChanged ? DecorationSet.empty : old;
          },
        },
        view: () => ({
          update: (view, previous) => {
            const now = pluginKey.getState(view.state);
            if (now === pluginKey.getState(previous) || now === DecorationSet.empty) return;
            // A new reveal: bring the current match to the middle of the view,
            // with its context around it — like the embedded-TODO highlight,
            // not ProseMirror's own edge-of-view scroll.
            view.dom.querySelector(`.${SEARCH_MATCH_CURRENT_CLASS}`)?.scrollIntoView?.({ block: "center" });
          },
        }),
        props: {
          decorations: (state) => pluginKey.getState(state) ?? DecorationSet.empty,
          handleKeyDown: (view, event) => {
            if (event.key !== "Escape" || pluginKey.getState(view.state) === DecorationSet.empty) return false;
            view.dispatch(view.state.tr.setMeta(pluginKey, DecorationSet.empty));
            return true;
          },
        },
      }),
    ];
  },
});
