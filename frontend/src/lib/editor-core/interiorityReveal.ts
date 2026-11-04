// TipTap extension: roleplay beats in the editor (ADR-0070, Amendment 1).
//
// A beat is the range between an open and a close marker atom (`beats.ts`).
// This extension draws everything that depends on the pairing, from one walk
// per document change:
//   • the who-said-what underline, an inline decoration over the range between
//     a pair (decision 2), so a beat may span paragraphs;
//   • the marker's own state, as a node decoration on each atom: its
//     character's colour, whether it is broken (no partner, decision 8), and for
//     a close marker whether its interiority is revealed. The close marker's node
//     view (`beatCloseView`) reads that and shows or hides its editor;
//   • the host's shell toggle reveals all / collapses all via a transaction meta.
//
// Reveal state is a Set of close-marker positions, mapped through each
// transaction so it follows the beat.

import { Extension } from "@tiptap/core";
import { Plugin, PluginKey, type EditorState, type Transaction } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";
import type { Node as PMNode } from "@tiptap/pm/model";

import { beatPluginKey, scanBeats, type BeatPluginState, type BeatScan } from "./beats";

// The interiority glyph — the stroked "eye" locked from the ADR-0070 mockup
// (see design-language.md lexicon). One glyph, one meaning: the same mark is the
// per-beat handle and the host's shell toggle.
export const INTERIORITY_EYE_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
  'aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/>' +
  '<circle cx="12" cy="12" r="3"/></svg>';

export type InteriorityRevealOptions = {
  /** Resolve a character lore id to its display colour, so the underline, the
   *  markers and the revealed box share one per-character tint. Returns "" to
   *  fall back to the neutral token. */
  colorForId: (id: string) => string;
  /** Resolve a character lore id to its title, for the underline's tooltip. */
  titleForId: (id: string) => string;
};

/** What a marker's node decoration tells its node view. */
export type BeatMarkerSpec = { characterId: string; revealed: boolean; broken: boolean };

type InteriorityState = BeatPluginState & {
  decorations: DecorationSet;
  /** Close-marker positions currently revealed. */
  revealed: Set<number>;
  /** Whether the doc holds any beat at all — drives the host's shell toggle. */
  hasBeats: boolean;
};

// One key for the plugin and for `beatScanOf`, so every reader of the pairing
// (the slash menu, the run guard, split) shares this plugin's scan.
const pluginKey = beatPluginKey as unknown as PluginKey<InteriorityState>;

// Metas the host / handles dispatch to change reveal state.
const TOGGLE_ONE = "interiority-toggle-one"; // payload: close-marker position
const REVEAL = "interiority-reveal"; // payload: close-marker positions in the new doc
const REVEAL_ALL = "interiority-reveal-all";
const COLLAPSE_ALL = "interiority-collapse-all";

/** Meta keys for driving reveal state — exported for the node view, commands and tests. */
export const INTERIORITY_META = {
  toggleOne: TOGGLE_ONE,
  reveal: REVEAL,
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

/** The current decoration set — exported for tests. */
export function interiorityDecorations(state: EditorState): DecorationSet {
  return pluginKey.getState(state)?.decorations ?? DecorationSet.empty;
}

/** Shell toggle: any open → collapse all; none open → reveal all. */
export function toggleAllInteriority(view: EditorView): void {
  const anyOpen = interiorityAnyRevealed(view.state);
  view.dispatch(view.state.tr.setMeta(anyOpen ? COLLAPSE_ALL : REVEAL_ALL, true));
  view.focus();
}

// ProseMirror compares node decorations by their attrs only, so the state a
// node view must react to rides in an attribute as well as in the spec.
function markerDeco(pos: number, spec: BeatMarkerSpec, attrs: Record<string, string> = {}): Decoration {
  const state = `${spec.characterId}|${spec.revealed ? "open" : "closed"}|${spec.broken ? "broken" : "ok"}`;
  return Decoration.node(pos, pos + 1, { ...attrs, "data-beat-state": state }, { beatMarker: spec });
}

function buildDecorations(
  doc: PMNode,
  scan: BeatScan,
  revealed: Set<number>,
  options: InteriorityRevealOptions,
): DecorationSet {
  const decos: Decoration[] = [];
  for (const beat of scan.beats) {
    const color = options.colorForId(beat.characterId);
    const style = color ? `--character-color: ${color}` : "";
    const title = options.titleForId(beat.characterId);
    if (beat.close > beat.open + 1) {
      decos.push(Decoration.inline(beat.open + 1, beat.close, { class: "character-mark", style, title }));
    }
    decos.push(
      markerDeco(beat.open, { characterId: beat.characterId, revealed: false, broken: false }, {
        style,
        title: `${title}: beat starts`,
      }),
    );
    decos.push(
      markerDeco(beat.close, {
        characterId: beat.characterId,
        revealed: revealed.has(beat.close),
        broken: false,
      }),
    );
  }
  for (const pos of scan.orphans) {
    decos.push(
      markerDeco(pos, { characterId: "", revealed: false, broken: true }, {
        class: "beat-marker-broken",
        title: "This beat marker has no partner, so it attributes nothing. Delete it, or add its partner.",
      }),
    );
  }
  return DecorationSet.create(doc, decos);
}

/** The ProseMirror plugin behind the extension — exported so it can be driven
 *  headless in tests. */
export function createInteriorityPlugin(options: InteriorityRevealOptions): Plugin<InteriorityState> {
  return new Plugin<InteriorityState>({
    key: pluginKey,
    state: {
      init: (_config, state) => {
        const scan = scanBeats(state.doc);
        const revealed = new Set<number>();
        return {
          scan,
          decorations: buildDecorations(state.doc, scan, revealed, options),
          revealed,
          hasBeats: scan.beats.length > 0,
        };
      },
      apply: (tr: Transaction, old: InteriorityState, _oldState, newState) => {
        const toggle = tr.getMeta(TOGGLE_ONE) as number | undefined;
        const reveal = tr.getMeta(REVEAL) as number[] | undefined;
        const wantRevealAll = Boolean(tr.getMeta(REVEAL_ALL));
        const wantCollapseAll = Boolean(tr.getMeta(COLLAPSE_ALL));
        const changed = typeof toggle === "number" || Boolean(reveal) || wantRevealAll || wantCollapseAll;

        // Nothing relevant happened (e.g. a bare selection change).
        if (!tr.docChanged && !changed) return old;

        const scan = scanBeats(newState.doc);
        const closes = new Set(scan.beats.map((b) => b.close));

        // Map reveal anchors through the edit; an insertion right before a
        // close marker moves the marker, so associate forward.
        let revealed = old.revealed;
        if (tr.docChanged) {
          const mapped = new Set<number>();
          for (const pos of old.revealed) mapped.add(tr.mapping.map(pos, 1));
          revealed = mapped;
        }
        if (typeof toggle === "number") {
          revealed = new Set(revealed);
          if (revealed.has(toggle)) revealed.delete(toggle);
          else revealed.add(toggle);
        }
        if (reveal) revealed = new Set([...revealed, ...reveal]);
        if (wantRevealAll) revealed = new Set(closes);
        if (wantCollapseAll) revealed = new Set();

        // Drop anchors that no longer land on a paired close marker.
        if (revealed.size) {
          const pruned = new Set<number>();
          for (const pos of revealed) if (closes.has(pos)) pruned.add(pos);
          revealed = pruned;
        }

        return {
          scan,
          decorations: buildDecorations(newState.doc, scan, revealed, options),
          revealed,
          hasBeats: scan.beats.length > 0,
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
    return { colorForId: () => "", titleForId: () => "" };
  },
  addProseMirrorPlugins() {
    return [
      createInteriorityPlugin({
        colorForId: (id: string) => this.options.colorForId(id),
        titleForId: (id: string) => this.options.titleForId(id),
      }),
    ];
  },
});
