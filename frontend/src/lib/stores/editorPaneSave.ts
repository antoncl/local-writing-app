// Post-save refresh dispatch, extracted from editorPanes' #performSave to keep
// that file under the 1500-line guard (the editorPaneDelete.ts precedent — pane
// lifecycle flow lives in siblings). A save can have changed a rebuildable index
// or a server-mirrored roster that other surfaces project over; this refreshes
// only the ones the saved document's kind can actually affect.

import { refreshStructure, refreshResearchStructure } from "@/lib/stores/structure";
import { refreshLoreEntries } from "@/lib/stores/lore";
import { refreshPromptEntries } from "@/lib/stores/prompts";
import { refreshPlotTemplates } from "@/lib/stores/plotTemplates";
import { refreshTemplateInstances } from "@/lib/stores/templateInstances";
import { refreshPlotBoard } from "@/lib/stores/plotBoard";
import { refreshPlotlines } from "@/lib/stores/plotlines";
import { refreshAssistantEntries } from "@/lib/stores/assistants";
import { refreshTodos, refreshEmbeddedTodos } from "@/lib/stores/todos";
import { bodyHasMutationMarkers, mutationsVersion } from "@/lib/stores/mutationsVersion.svelte";

// The one thing the dispatch needs back from the controller: the project node's
// title write-back (the top bar + pane reflect a rename). Passed as a narrow host
// so this stays a free function rather than a method that keeps the file large.
export type SaveRefreshHost = {
  onProjectNodeSaved(title: string): void;
};

export type SaveRefreshArgs = {
  documentKind: string;
  savedTitle: string;
  // The pre-save body and the current draft — a scene save that touched a mutation
  // marker (in either) invalidates the mutations index.
  baselineBody: string;
  draftMarkdown: string;
};

export async function refreshAfterSave(host: SaveRefreshHost, args: SaveRefreshArgs): Promise<void> {
  const { documentKind } = args;
  if (documentKind === "lore") {
    await refreshLoreEntries();
  } else if (documentKind === "research") {
    // save_research_note already syncs the title into the research tree
    // server-side; refresh so the pane reflects it.
    await refreshResearchStructure();
  } else if (documentKind === "prompt") {
    await refreshPromptEntries();
  } else if (documentKind === "plot_template") {
    await refreshPlotTemplates();
  } else if (documentKind === "plot_card") {
    // Reflect a card edit (plotline / scene / synopsis) on the board if it is
    // open. In-flight-guarded, so it is cheap when the board is closed.
    await refreshPlotBoard();
  } else if (documentKind === "plotline") {
    // A rename / recolour changes both the card-colour axis on the board and the
    // roster the ReferencePicker's `plot` source draws from (#742).
    await refreshPlotBoard();
    await refreshPlotlines();
  } else if (documentKind === "plot_template_instance") {
    // A rename / beat edit changes the arc roster the palette shows.
    await refreshTemplateInstances();
  } else if (documentKind === "assistant") {
    await refreshAssistantEntries();
  } else if (documentKind === "project") {
    // Title may have changed; reflect it on the top bar and pane.
    host.onProjectNodeSaved(args.savedTitle);
  } else {
    await refreshStructure();
    await refreshTodos();
    // Embedded (in-prose) todos are a rebuildable index over scene bodies;
    // a scene save may add/remove/edit markers, so re-scan (GH #45).
    if (documentKind === "scene" || documentKind === "structure_node") {
      await refreshEmbeddedTodos();
      // Mutations are likewise an index over scene bodies (#63, ADR-0014):
      // a save that touches a marker-bearing scene (before or after the
      // edit — covers add, remove, edit, and offset shifts) invalidates
      // every open mutations reader.
      if (bodyHasMutationMarkers(args.baselineBody) || bodyHasMutationMarkers(args.draftMarkdown)) {
        mutationsVersion.bump();
      }
    }
  }
}
