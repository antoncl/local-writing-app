// Openers for the registry regions that need no App-local state — they only
// touch importable singletons (workspaceLayout + a roster refresh), so they
// live here rather than in App.svelte (extracted at the file-size cap; the
// openers that route through App's run()/error banner, like the plot board
// and import flows, stay in App).

import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { chatSessions } from "@/lib/stores/chatSessions.svelte";
import { refreshAssistantEntries } from "@/lib/stores/assistants";

export function openPromptsPane(): void {
  workspaceLayout.ensureVisible("prompts");
}

export function openPlotTemplatesPane(): void {
  workspaceLayout.ensureVisible("plotTemplates");
}

export function openMutationsPane(): void {
  workspaceLayout.ensureVisible("mutations");
}

export function openGuidePane(): void {
  workspaceLayout.ensureVisible("guide");
}

export function openAiSpendPane(): void {
  // No refresh here: the pane's own mount/project effect fetches, and a
  // second call from the opener would double-fetch on first open.
  workspaceLayout.ensureVisible("aiSpend");
}

export function openAssistantsPane(): void {
  void refreshAssistantEntries();
  workspaceLayout.ensureVisible("assistants");
}

export function openChatsPane(): void {
  void chatSessions.refresh();
  workspaceLayout.ensureVisible("chats");
}
