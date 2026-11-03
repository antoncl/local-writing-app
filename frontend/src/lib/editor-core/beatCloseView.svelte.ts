// The close marker's node view (ADR-0070 Amendment 1, decision 4): the eye
// handle, and — while revealed — the beat's interiority in the same long-text
// editor metadata fields use, so the proofreading lens checks it (ADR-0102
// Amendment 3).
//
// An edit changes only this atom's `internal` attribute, and `update` takes the
// new value in place, so ProseMirror never rebuilds this DOM: the editor stays
// live while it is open, a writing assistant's fix lands in it, and the eye
// click is never lost to a redraw. Pairing, colour and reveal state arrive as
// the node decoration `interiorityReveal` puts on the marker.
import { mount, unmount } from "svelte";
import type { Node as PMNode } from "@tiptap/pm/model";
import type { Decoration, EditorView, NodeView } from "@tiptap/pm/view";

import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";
import { BEAT_CLOSE } from "./beats";
import { INTERIORITY_EYE_SVG, INTERIORITY_META, type BeatMarkerSpec } from "./interiorityReveal";

export type BeatCloseViewOptions = {
  /** A character lore id → its colour, so the handle and box match the underline. */
  colorForId: (id: string) => string;
  /** The scene the interiority is proofread and ignored against; null = not proofread. */
  proofreadNodeId: () => string | null;
};

type ViewProps = {
  node: PMNode;
  view: EditorView;
  getPos: () => number | undefined;
  decorations: readonly Decoration[];
};

function markerSpec(decorations: readonly Decoration[]): BeatMarkerSpec | null {
  for (const deco of decorations) {
    const spec = (deco.spec as { beatMarker?: BeatMarkerSpec }).beatMarker;
    if (spec) return spec;
  }
  return null;
}

export function createBeatCloseView(props: ViewProps, options: BeatCloseViewOptions): NodeView {
  const { view, getPos } = props;
  const dom = document.createElement("span");
  dom.className = "beat-close";
  dom.setAttribute("data-character-close", "");

  const handle = document.createElement("button");
  handle.type = "button";
  handle.className = "interiority-handle";
  handle.innerHTML = INTERIORITY_EYE_SVG;
  handle.title = "Interiority";
  handle.addEventListener("mousedown", (e) => e.preventDefault()); // keep the editor selection
  handle.addEventListener("click", (e) => {
    e.preventDefault();
    const pos = getPos();
    if (pos == null) return;
    view.dispatch(view.state.tr.setMeta(INTERIORITY_META.toggleOne, pos));
  });
  dom.appendChild(handle);

  const editorProps = $state({
    value: String(props.node.attrs.internal ?? ""),
    ariaLabel: "Interiority for this beat",
    proofreadNodeId: options.proofreadNodeId(),
    onChange: (next: string) => {
      const pos = getPos();
      if (pos == null) return;
      const current = view.state.doc.nodeAt(pos);
      if (!current || current.type.name !== BEAT_CLOSE || current.attrs.internal === next) return;
      view.dispatch(view.state.tr.setNodeMarkup(pos, undefined, { ...current.attrs, internal: next }));
    },
  });

  let block: HTMLElement | null = null;
  let mounted: Record<string, unknown> | null = null;

  function reveal(open: boolean): void {
    if (open && !block) {
      block = document.createElement("span");
      block.className = "interiority-block";
      editorProps.proofreadNodeId = options.proofreadNodeId();
      mounted = mount(MetadataLongTextEditor, { target: block, props: editorProps });
      dom.appendChild(block);
    } else if (!open && block) {
      // Every keystroke already reached the atom, so closing loses nothing.
      if (mounted) void unmount(mounted);
      mounted = null;
      block.remove();
      block = null;
    }
  }

  function apply(decorations: readonly Decoration[]): void {
    const spec = markerSpec(decorations);
    const color = spec?.characterId ? options.colorForId(spec.characterId) : "";
    if (color) dom.style.setProperty("--character-color", color);
    else dom.style.removeProperty("--character-color");
    const broken = !spec || spec.broken;
    dom.classList.toggle("beat-marker-broken", broken);
    const open = Boolean(spec?.revealed) && !broken;
    handle.setAttribute("aria-expanded", String(open));
    handle.setAttribute(
      "aria-label",
      broken
        ? "This beat end has no beat start"
        : open
          ? "Hide interiority for this beat"
          : "Reveal interiority for this beat",
    );
    handle.title = broken ? "This beat end has no beat start. Delete it, or add a start." : "Interiority";
    reveal(open);
  }

  apply(props.decorations);

  return {
    dom,
    update(node, decorations) {
      if (node.type.name !== BEAT_CLOSE) return false;
      const internal = String(node.attrs.internal ?? "");
      // An echo of our own edit is ignored by the editor's local-value guard;
      // anything else (undo, a split's copy) loads into it.
      if (editorProps.value !== internal) editorProps.value = internal;
      apply(decorations);
      return true;
    },
    // Everything inside the box belongs to the nested editor; the handle runs
    // its own listeners.
    stopEvent(event) {
      const target = event.target as globalThis.Node | null;
      return Boolean(target && (handle.contains(target) || block?.contains(target)));
    },
    ignoreMutation: () => true,
    destroy() {
      if (mounted) void unmount(mounted);
      mounted = null;
    },
  };
}
