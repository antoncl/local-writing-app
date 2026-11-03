// The two roleplay beat markers (ADR-0070 Amendment 1). Both are inline atoms,
// as mutation anchors are (ADR-0095): the open marker names the character, the
// close marker carries the beat's private interiority, stored once. They
// round-trip to `<!-- character:id=X -->` and `<!-- /character;internal=… -->`
// (lib/utils/markdown).
//
// Neither node knows its partner. The pairing, the underline between a pair,
// the colour and the broken state all come from `interiorityReveal`, which hands
// each marker a node decoration; the close marker's node view reads its
// reveal state from the same decoration.
import { mergeAttributes, Node } from "@tiptap/core";
import type { EditorView } from "@tiptap/pm/view";

import { BEAT_CLOSE, BEAT_OPEN, splitBeat } from "./beats";
import { INTERIORITY_META } from "./interiorityReveal";
import type { SlashCommand } from "./slashMenu";
import { createBeatCloseView, type BeatCloseViewOptions } from "./beatCloseView.svelte";

export const BeatOpenMarker = Node.create({
  name: BEAT_OPEN,
  inline: true,
  group: "inline",
  atom: true,
  selectable: true,
  addAttributes() {
    return {
      characterId: {
        default: "",
        parseHTML: (element) => element.getAttribute("data-character-open") ?? "",
        renderHTML: (attributes) => ({ "data-character-open": String(attributes.characterId ?? "") }),
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-character-open]" }];
  },
  renderHTML({ HTMLAttributes }) {
    // The text is for serialisation only (turndown drops an element with no
    // text); the node view draws the marker.
    return ["span", mergeAttributes(HTMLAttributes, { class: "beat-open" }), "⌜"];
  },
  addNodeView() {
    return ({ node }) => {
      const dom = document.createElement("span");
      dom.className = "beat-open";
      dom.setAttribute("data-character-open", String(node.attrs.characterId ?? ""));
      return {
        dom,
        update: (updated) => {
          if (updated.type.name !== BEAT_OPEN) return false;
          dom.setAttribute("data-character-open", String(updated.attrs.characterId ?? ""));
          return true;
        },
      };
    };
  },
});

export const BeatCloseMarker = Node.create<BeatCloseViewOptions>({
  name: BEAT_CLOSE,
  inline: true,
  group: "inline",
  atom: true,
  selectable: true,
  addOptions() {
    return { colorForId: () => "", proofreadNodeId: () => null };
  },
  addAttributes() {
    return {
      internal: {
        default: "",
        parseHTML: (element) => element.getAttribute("data-internal") ?? "",
        renderHTML: (attributes) =>
          attributes.internal ? { "data-internal": String(attributes.internal) } : {},
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-character-close]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { "data-character-close": "", class: "beat-close" }), "⌟"];
  },
  addNodeView() {
    return (props) => createBeatCloseView(props, this.options);
  },
});

/** Split the beat around the cursor (decision 6) and reveal both halves'
 *  interiority, so the author trims each copy to its half. A no-op outside a beat. */
export function splitBeatAtCursor(view: EditorView): void {
  const split = splitBeat(view.state, view.state.selection.from);
  if (!split) return;
  view.dispatch(split.tr.setMeta(INTERIORITY_META.reveal, split.closes));
  view.focus();
}

/** The `/roleplay split` slash command, offered only inside a beat. */
export function roleplaySplitCommand(characterTitle: string, run: () => void): SlashCommand {
  return {
    group: "AI",
    label: "Roleplay split",
    description: "Split this beat at the cursor.",
    hint: `End ${characterTitle}'s beat here and start a new one after it. Both halves keep a copy of the interiority, shown so you can trim each.`,
    autocompleteTo: "roleplay split",
    scope: "manuscript",
    run,
  };
}
