// Thin orchestrator for the domain store layer (see docs/frontend-architecture.md).
// Holds NO state of its own — it only composes the per-domain modules so the
// project-open / project-clear flows have a single entry point instead of a
// hand-rolled fan-out duplicated across App.svelte.

import { refreshStructure, refreshResearchStructure, clearStructure } from "@/lib/stores/structure";
import { refreshLoreEntries, clearLore } from "@/lib/stores/lore";
import { refreshPromptEntries, clearPrompts } from "@/lib/stores/prompts";
import { refreshPlotTemplates, clearPlotTemplates } from "@/lib/stores/plotTemplates";
import { refreshPlotlines, clearPlotlines } from "@/lib/stores/plotlines";
import { refreshCards, clearCards } from "@/lib/stores/plotCards";
import { clearPlotBoard } from "@/lib/stores/plotBoard";
import { refreshMutationSetEntries, clearMutationSets } from "@/lib/stores/mutationSets";
import { refreshSchema, clearSchema } from "@/lib/stores/schema";
import { refreshReferenceIndex, clearReferenceIndex } from "@/lib/stores/references";
import { refreshTagNodes, clearTagNodes } from "@/lib/stores/tagNodes";
import { refreshTodos, refreshEmbeddedTodos, clearTodos } from "@/lib/stores/todos";
import { clearValidation } from "@/lib/stores/validation";
import { clearChats } from "@/lib/stores/chats";
import { clearAssistants } from "@/lib/stores/assistants";
import { aiSpend } from "@/lib/stores/aiSpend.svelte";

// Load the project-scoped server state in parallel. Mirrors exactly the slices
// the open paths fetched serially (structure/research/lore/prompts/schema/
// tags/todos); chats, cost, assistants and project color are hydrated by
// openProjectWorkspace on its own cadence. Callers run this inside App's run()
// wrapper so HTTP errors still surface; schema's App-local authoring fallback
// runs after this resolves (the store refresh itself carries no UI state).
export async function loadProjectData(): Promise<void> {
  await Promise.all([
    refreshStructure(),
    refreshResearchStructure(),
    refreshLoreEntries(),
    refreshPromptEntries(),
    refreshPlotTemplates(),
    refreshPlotlines(),
    refreshCards(),
    refreshMutationSetEntries(),
    refreshSchema(),
    refreshReferenceIndex(),
    refreshTagNodes(),
    refreshTodos(),
    refreshEmbeddedTodos(),
  ]);
}

// Reset every domain slice to empty. For a future close-to-no-project flow;
// opening another project overwrites in place, so this is not on the open path.
export function clearProjectData(): void {
  clearStructure();
  clearLore();
  clearPrompts();
  clearPlotTemplates();
  clearPlotlines();
  clearCards();
  clearPlotBoard();
  clearMutationSets();
  clearSchema();
  clearReferenceIndex();
  // Not a plain clear (review fix): the tag roster is machine-global
  // (ADR-0082 slice 1) — machine-layer tags remain valid with no project
  // open, same as the assistant roster (`clearAssistants` below has no such
  // re-refresh yet, but tags need one because `loadMachineSettings` hydrates
  // this store even before this flow runs). Fire-and-forget: a full clear
  // then a fresh GET, not awaited — this function is synchronous like its
  // siblings, and the roster is empty for one tick either way.
  clearTagNodes();
  void refreshTagNodes();
  clearTodos();
  clearValidation();
  clearChats();
  clearAssistants();
  aiSpend.reset();
}
