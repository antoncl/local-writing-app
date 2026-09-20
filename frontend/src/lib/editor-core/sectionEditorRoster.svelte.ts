// Section editor roster (#2043, extracted from BodySections.svelte): the
// bookkeeping shared by any host that stacks section editors under a
// keyboard-bridge registry — BodySections itself, and the plot board's
// PlotBeatSections (#2043 slice 3), which hosts the same repeating sections
// inside a board node instead of the NodeEditor body.
import { untrack } from "svelte";
import type { Editor } from "@tiptap/core";
import type { SectionRegistry } from "./sectionKeyboardBridge";

export type SectionEditorRoster = {
  /** 1-based document index of an editor id (0 is the free body); 0 when unknown. */
  sectionIndex: (editorId: string) => number;
  editorReady: (editorId: string, editor: Editor, phase: "ready" | "destroy") => void;
};

/** Call during component init (it owns a $effect). `orderedIds` is read reactively. */
export function createSectionEditorRoster(register: SectionRegistry, orderedIds: () => string[]): SectionEditorRoster {
  function sectionIndex(editorId: string): number {
    return orderedIds().indexOf(editorId) + 1;
  }

  // "ready" registers by index/editorId; "destroy" unregisters by the editor's
  // own IDENTITY (never by index/editorId) — a fast remount can register the
  // NEW instance at the same slot before the OLD one's cleanup runs, and an
  // index-keyed delete there would evict the live registration (#2009 follow-up).
  const mounted = new Map<string, Editor>();
  function editorReady(editorId: string, editor: Editor, phase: "ready" | "destroy"): void {
    if (phase === "ready") {
      mounted.set(editorId, editor);
      register.register(sectionIndex(editorId), editorId, editor);
    } else {
      mounted.delete(editorId);
      register.unregister(editor);
    }
  }

  // A section's document index is not fixed for the life of its editor: a
  // schema edit while the node is open (a long_text field added, reordered
  // or hidden) reshuffles `orderedIds`, so every mounted editor re-registers
  // under its current index — otherwise the bridge would still walk the
  // order the sections had when they mounted.
  // Keyed on the ORDER as a string, not the array: `orderedIds` also reads
  // list items (#2043), so it can be a fresh array on every metadata write —
  // every keystroke in any section — while the order itself rarely changes.
  const orderedKey = $derived(orderedIds().join("|"));
  $effect(() => {
    void orderedKey;
    untrack(() => {
      for (const [editorId, editor] of mounted) {
        register.unregister(editor);
        register.register(sectionIndex(editorId), editorId, editor);
      }
    });
  });

  return { sectionIndex, editorReady };
}
