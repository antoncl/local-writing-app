// TipTap extension: the roleplay-interiority reveal affordance (ADR-0070 S2).
//
// Each roleplay "beat" — a maximal run of the `character` mark — hides a private
// `internal` payload (written by S1). This extension surfaces it in the editor:
//   • a small eye handle (widget decoration) hugs each beat's end;
//   • activating a handle reveals THAT beat's interiority inline as a distinct
//     tinted, editable block; edits write back to the beat's `internal` mark
//     attribute on blur (author authority, ADR-0046) and ride the S1 markdown
//     round-trip untouched;
//   • the host's shell toggle reveals-all / collapses-all via a transaction meta.
//
// Modelled on ImplicitContextHighlight: a ProseMirror plugin holds a
// DecorationSet rebuilt per transaction. Reveal state is a Set of beat anchor
// positions, mapped through each transaction so it follows edits.

import { Extension } from "@tiptap/core";
import { Plugin, PluginKey, type EditorState, type Transaction } from "prosemirror-state";
import { Decoration, DecorationSet, type EditorView } from "prosemirror-view";
import type { Node as PMNode, MarkType } from "prosemirror-model";

const HANDLE_CLASS = "interiority-handle";
const BLOCK_CLASS = "interiority-block";
const MARK_NAME = "character";

// The interiority glyph — the stroked "eye" locked from the ADR-0070 mockup
// (see design-language.md lexicon). One glyph, one meaning: the same mark is the
// per-beat handle here and the host's shell toggle.
export const INTERIORITY_EYE_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
  'aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/>' +
  '<circle cx="12" cy="12" r="3"/></svg>';

export type InteriorityRevealOptions = {
  /** Resolve a character lore id to its display colour, so the handle and the
   *  revealed block carry the same per-character tint as the beat's underline.
   *  Returns "" to fall back to the neutral token. */
  colorForId: (id: string) => string;
};

type Beat = { id: string; from: number; to: number; internal: string };

type InteriorityState = {
  decorations: DecorationSet;
  /** Beat anchor positions (each beat's end) currently revealed. Mapped
   *  through every transaction so reveal state follows the beat as it moves. */
  revealed: Set<number>;
  /** Whether the doc holds any beat at all — drives the host's shell toggle. */
  hasBeats: boolean;
};

const EMPTY: InteriorityState = {
  decorations: DecorationSet.empty,
  revealed: new Set(),
  hasBeats: false,
};

const pluginKey = new PluginKey<InteriorityState>("interiority-reveal");

// Metas the host / handles dispatch to change reveal state without a doc edit.
const TOGGLE_ONE = "interiority-toggle-one"; // payload: anchor position (number)
const REVEAL_ALL = "interiority-reveal-all";
const COLLAPSE_ALL = "interiority-collapse-all";

/** Meta keys for driving reveal state — exported for tests / advanced hosts. */
export const INTERIORITY_META = {
  toggleOne: TOGGLE_ONE,
  revealAll: REVEAL_ALL,
  collapseAll: COLLAPSE_ALL,
} as const;

/** Does the current buffer contain at least one roleplay beat? */
export function interiorityHasBeats(state: EditorState): boolean {
  return pluginKey.getState(state)?.hasBeats ?? false;
}

/** Is any beat's interiority currently revealed? (shell-toggle pressed state) */
export function interiorityAnyRevealed(state: EditorState): boolean {
  return (pluginKey.getState(state)?.revealed.size ?? 0) > 0;
}

/** The current decoration set — exported for tests to count handles/blocks. */
export function interiorityDecorations(state: EditorState): DecorationSet {
  return pluginKey.getState(state)?.decorations ?? DecorationSet.empty;
}

/** Shell toggle: any open → collapse all; none open → reveal all. */
export function toggleAllInteriority(view: EditorView): void {
  const anyOpen = interiorityAnyRevealed(view.state);
  view.dispatch(view.state.tr.setMeta(anyOpen ? COLLAPSE_ALL : REVEAL_ALL, true));
  view.focus();
}

function markTypeOf(doc: PMNode): MarkType | null {
  return doc.type.schema.marks[MARK_NAME] ?? null;
}

/** Walk the doc, coalescing contiguous same-character text into beats. A beat
 *  spans multiple text nodes (e.g. emphasis inside it); position-contiguity
 *  plus a shared id define one beat, and any gap (narration, block boundary,
 *  a different character) starts a new one. Exported for tests. */
export function findBeats(doc: PMNode, markType: MarkType): Beat[] {
  const beats: Beat[] = [];
  let cur: Beat | null = null;
  doc.descendants((node, pos) => {
    if (!node.isText) return;
    const mark = node.marks.find((m) => m.type === markType);
    const id = mark ? String(mark.attrs.characterId ?? "") : "";
    if (!id) return;
    const from = pos;
    const to = pos + node.nodeSize;
    const internal = String(mark?.attrs.internal ?? "");
    if (cur && cur.id === id && cur.to === from) {
      cur.to = to;
      if (internal && !cur.internal) cur.internal = internal;
    } else {
      if (cur) beats.push(cur);
      cur = { id, from, to, internal };
    }
  });
  if (cur) beats.push(cur);
  return beats;
}

/** Replace a beat's `internal` mark attribute over its current range. Re-derives
 *  the range from the live position (`getPos`, the block's anchor at the beat's
 *  end) so it stays correct after edits. Called on textarea blur, so losing the
 *  widget's focus on the rebuild is fine. */
function writeBackInternal(view: EditorView, getPos: () => number | undefined, next: string): void {
  const markType = markTypeOf(view.state.doc);
  if (!markType) return;
  const pos = getPos();
  if (pos == null) return;
  const beats = findBeats(view.state.doc, markType);
  // The block is anchored at the beat's end; match on that, falling back to a
  // beat that contains the position.
  const beat = beats.find((b) => b.to === pos) ?? beats.find((b) => pos > b.from && pos <= b.to);
  if (!beat) return;
  if (beat.internal === next) return;
  const mark = markType.create({ characterId: beat.id, internal: next });
  const tr = view.state.tr
    .removeMark(beat.from, beat.to, markType)
    .addMark(beat.from, beat.to, mark);
  view.dispatch(tr);
}

function buildHandle(
  view: EditorView,
  getPos: () => number | undefined,
  open: boolean,
  color: string,
): HTMLElement {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = HANDLE_CLASS;
  if (color) btn.style.setProperty("--character-color", color);
  btn.innerHTML = INTERIORITY_EYE_SVG;
  btn.setAttribute("aria-expanded", String(open));
  btn.setAttribute("aria-label", open ? "Hide interiority for this beat" : "Reveal interiority for this beat");
  btn.title = "Interiority";
  btn.addEventListener("mousedown", (e) => e.preventDefault()); // keep editor selection
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    const pos = getPos();
    if (pos == null) return;
    view.dispatch(view.state.tr.setMeta(TOGGLE_ONE, pos));
  });
  return btn;
}

function buildBlock(
  view: EditorView,
  getPos: () => number | undefined,
  internal: string,
  color: string,
): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = BLOCK_CLASS;
  if (color) wrap.style.setProperty("--character-color", color);
  wrap.contentEditable = "false"; // the widget is outside the doc model

  const area = document.createElement("textarea");
  area.className = `${BLOCK_CLASS}-text`;
  area.value = internal;
  area.rows = Math.max(1, internal.split("\n").length);
  area.placeholder = "This character's private interiority…";
  area.spellcheck = true;
  // Grow with content; keep editor selection out of the way while typing.
  const autosize = () => {
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight}px`;
  };
  area.addEventListener("input", autosize);
  area.addEventListener("mousedown", (e) => e.stopPropagation());
  area.addEventListener("blur", () => writeBackInternal(view, getPos, area.value));
  wrap.appendChild(area);
  // Measure after mount.
  window.requestAnimationFrame(autosize);
  return wrap;
}

function buildDecorations(
  doc: PMNode,
  beats: Beat[],
  revealed: Set<number>,
  colorForId: (id: string) => string,
): DecorationSet {
  const decos: Decoration[] = [];
  for (const beat of beats) {
    const open = revealed.has(beat.to);
    const color = colorForId(beat.id);
    // The eye handle hugs the beat's end; side -1 keeps it bound to the beat.
    decos.push(
      Decoration.widget(beat.to, (view, getPos) => buildHandle(view, getPos, open, color), {
        // Position in the key: a character has many beats, so id alone collides.
        key: `interiority-handle-${beat.id}-${beat.to}-${open}`,
        side: -1,
        ignoreSelection: true,
      }),
    );
    if (open) {
      // Anchor the block at the beat's end (side 1 → just after the handle), so
      // its live position maps back to this beat on write-back.
      decos.push(
        Decoration.widget(beat.to, (view, getPos) => buildBlock(view, getPos, beat.internal, color), {
          // Stable key (independent of the text) so PM reuses the textarea DOM
          // across unrelated transactions and never steals focus mid-edit.
          key: `interiority-block-${beat.id}-${beat.to}`,
          side: 1,
          ignoreSelection: true,
        }),
      );
    }
  }
  return DecorationSet.create(doc, decos);
}

/** The ProseMirror plugin behind the extension — exported so it can be driven
 *  headless in tests (build an EditorState with a character-mark schema and this
 *  plugin, then dispatch INTERIORITY_META transactions). */
export function createInteriorityPlugin(colorForId: (id: string) => string): Plugin<InteriorityState> {
  return new Plugin<InteriorityState>({
    key: pluginKey,
    state: {
          init: (_config, state) => {
            const markType = markTypeOf(state.doc);
            if (!markType) return EMPTY;
            const revealed = new Set<number>();
            const beats = findBeats(state.doc, markType);
            return {
              decorations: buildDecorations(state.doc, beats, revealed, colorForId),
              revealed,
              hasBeats: beats.length > 0,
            };
          },
          apply: (tr: Transaction, old: InteriorityState, _oldState, newState) => {
            const markType = markTypeOf(newState.doc);
            if (!markType) return EMPTY;

            const toggle = tr.getMeta(TOGGLE_ONE) as number | undefined;
            const wantRevealAll = Boolean(tr.getMeta(REVEAL_ALL));
            const wantCollapseAll = Boolean(tr.getMeta(COLLAPSE_ALL));
            const changed = typeof toggle === "number" || wantRevealAll || wantCollapseAll;

            // Nothing relevant happened (e.g. a bare selection change) — keep
            // the set and its decorations without walking the doc.
            if (!tr.docChanged && !changed) return old;

            // One doc walk per rebuild, shared by reveal-all, prune, and build.
            const beats = findBeats(newState.doc, markType);
            const ends = new Set(beats.map((b) => b.to));

            // Map reveal anchors through the edit so they follow their beats.
            let revealed = old.revealed;
            if (tr.docChanged) {
              const mapped = new Set<number>();
              for (const pos of old.revealed) mapped.add(tr.mapping.map(pos, -1));
              revealed = mapped;
            }
            if (typeof toggle === "number") {
              revealed = new Set(revealed);
              if (revealed.has(toggle)) revealed.delete(toggle);
              else revealed.add(toggle);
            }
            if (wantRevealAll) revealed = new Set(ends);
            if (wantCollapseAll) revealed = new Set();

            // Drop anchors that no longer land on a beat end (beat deleted/edited).
            if (revealed.size) {
              const pruned = new Set<number>();
              for (const pos of revealed) if (ends.has(pos)) pruned.add(pos);
              revealed = pruned;
            }

            return {
              decorations: buildDecorations(newState.doc, beats, revealed, colorForId),
              revealed,
              hasBeats: beats.length > 0,
            };
          },
        },
    props: {
      decorations(state) {
        return pluginKey.getState(state)?.decorations ?? DecorationSet.empty;
      },
    },
  });
}

export const InteriorityReveal = Extension.create<InteriorityRevealOptions>({
  name: "interiorityReveal",
  addOptions() {
    return { colorForId: () => "" };
  },
  addProseMirrorPlugins() {
    return [createInteriorityPlugin((id: string) => this.options.colorForId(id))];
  },
});
