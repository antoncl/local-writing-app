// Openers for the registry regions that need no App-local state — they only
// touch importable singletons (workspaceLayout + a roster refresh), so they
// live here rather than in App.svelte (extracted at the file-size cap; the
// openers that route through App's run()/error banner, like the plot board
// and import flows, stay in App).

import { workspaceLayout } from "@/lib/stores/workspaceLayout.svelte";
import { chatSessions } from "@/lib/stores/chatSessions.svelte";
import { refreshAssistantEntries } from "@/lib/stores/assistants";
import { aiSpend } from "@/lib/stores/aiSpend.svelte";

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
  // First open: the pane's mount effect fetches (refreshing here too would
  // double-fetch). Re-open of an already-mounted pane — workspace tabs stay
  // mounted, so the effect won't re-run — refreshes here so the numbers
  // include everything since the pane was last looked at.
  if (aiSpend.summary || aiSpend.error) void aiSpend.refresh();
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
