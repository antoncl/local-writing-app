// Thin orchestrator for the domain store layer (see docs/frontend-architecture.md).
// Holds NO state of its own — it only composes the per-domain modules so the
// project-open / project-clear flows have a single entry point instead of a
// hand-rolled fan-out duplicated across App.svelte.

import { refreshStructure, refreshResearchStructure, clearStructure } from "@/lib/stores/structure";
import { refreshLoreEntries, clearLore } from "@/lib/stores/lore";
import { refreshPromptEntries, clearPrompts } from "@/lib/stores/prompts";
import { refreshSchema, clearSchema } from "@/lib/stores/schema";
import { refreshKnownTags, clearKnownTags } from "@/lib/stores/tags";
import { refreshTodos, refreshEmbeddedTodos, clearTodos } from "@/lib/stores/todos";
import { clearValidation } from "@/lib/stores/validation";
import { clearChats } from "@/lib/stores/chats";
import { clearAssistants } from "@/lib/stores/assistants";

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
    refreshSchema(),
    refreshKnownTags(),
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
  clearSchema();
  clearKnownTags();
  clearTodos();
  clearValidation();
  clearChats();
  clearAssistants();
}
