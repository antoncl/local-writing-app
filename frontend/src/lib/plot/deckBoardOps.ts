// The recorded deck gestures behind the board's deck menus (ADR-0097 §7, §8) — rename, realize
// as a container, detach, delete, and where a deck's "New card" puts the card. The board
// (PlotEditor) hands in its undo recorder, the live projection and an error sink, and wires
// these to the deck box's menu and the realized container box's menu alike.

import type { PlaceTo } from "@/lib/api/plot";
import type { PlotUndoRecorder } from "@/lib/plot/plotCommands";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { deleteDeck } from "@/lib/stores/decks";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import type { PlotBoardProjection } from "@/lib/types";

/** Where a deck's "New card" creates the card: planned in the deck's container when it is
 *  realized (its cards live there now), else in the deck. */
export function newCardTarget(projection: PlotBoardProjection | null, deckId: string): PlaceTo {
  const container = projection?.decks.find((d) => d.id === deckId)?.realized_container;
  return container ? { planned_in: container, planned_after: null } : { deck: deckId };
}

export function deckBoardOps(
  recorder: PlotUndoRecorder,
  getProjection: () => PlotBoardProjection | null,
  setError: (message: string) => void,
) {
  const attempt = async (op: () => Promise<void>, failure: string): Promise<void> => {
    try {
      await op();
    } catch (e) {
      setError(e instanceof Error ? e.message : failure);
    }
  };

  return {
    // Rename from the box: the displayed title — the container's while the deck is realized.
    rename: (id: string, title: string): Promise<void> =>
      attempt(() => recorder.deckTextEdit(id, "rename deck", { title }), "Could not rename the deck."),

    // "Realize as <level>": a refusal (the level list allows none here) surfaces in the banner.
    realize: (id: string): Promise<void> => attempt(() => recorder.realizeDeck(id), "Could not realize the deck."),

    detach: (id: string): Promise<void> => attempt(() => recorder.detachDeck(id), "Could not detach the deck."),

    // Delete a deck — only the deck: its cards go loose and its child decks to the top level (a
    // realized deck's container stays in the manuscript). Confirmed when it holds anything;
    // recorded, so Ctrl+Z recreates it and puts them back.
    remove(id: string): void {
      const projection = getProjection();
      const deck = projection?.decks.find((d) => d.id === id);
      const holdsSomething =
        (projection?.cards ?? []).some((c) => c.deck === id) || (projection?.decks ?? []).some((d) => d.parent === id);
      const run = async (): Promise<void> => {
        await recorder.deleteDeck(id, () => deleteDeck(id));
        // Close a NodeEditor pane open on this deck ("Open"): the node is gone.
        const openPane = editorPanes.panes.find((p) => p.document?.id === id);
        if (openPane) editorPanes.tearDown(openPane.id);
      };
      if (!holdsSomething && !deck?.realized_container) {
        void run();
        return;
      }
      confirmService.request({
        title: "Delete deck",
        message: `Delete deck ${deck?.title ? `“${deck.title}”` : "this deck"}? ${
          deck?.realized_container
            ? "The chapter stays in the manuscript, with its cards; its child decks move out."
            : "Its cards and decks move out; nothing else is deleted."
        }`,
        confirmLabel: "Delete deck",
        destructive: true,
        onConfirm: run,
      });
    },
  };
}
