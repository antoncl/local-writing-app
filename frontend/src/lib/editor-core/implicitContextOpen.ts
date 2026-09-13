// Following an implicit-context match to its entry (#1923): the one opener
// every host of the highlight extension passes as `openEntry`. The matcher is
// compiled from lore entries, so an entry id is a lore id and the entry opens
// as an editor tab, the way every other reference to a node does.
import { reportClientError } from "@/lib/errorLog";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";

export function openImplicitContextEntry(entryId: string): void {
  editorPanes.openLore(entryId).catch((cause: unknown) => reportClientError(cause, "open implicit-context entry"));
}
