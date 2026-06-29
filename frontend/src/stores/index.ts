// Thin orchestrator for the domain store layer (see docs/frontend-architecture.md).
// Holds NO state of its own — it only composes the per-domain modules so the
// project-open / project-clear flows have a single entry point instead of a
// hand-rolled fan-out duplicated across App.svelte.

import { refreshStructure, refreshResearchStructure, clearStructure } from "./structure";
import { refreshLoreEntries, clearLore } from "./lore";
import { refreshPromptEntries, clearPrompts } from "./prompts";
import { refreshSchema, clearSchema } from "./schema";
import { refreshKnownTags, clearKnownTags } from "./tags";
import { refreshTodos, clearTodos } from "./todos";
import { clearValidation } from "./validation";
import { clearChats } from "./chats";
import { clearAssistants } from "./assistants";

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
