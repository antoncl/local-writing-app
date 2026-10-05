// The status line after a roleplay finalize (#2435): says, in plain words, what
// the rewrite didn't carry itself. Empty when nothing needed rescuing.

import type { FinalizeSceneResponse } from "@/lib/types";

export function finalizeNotice(result: Pick<FinalizeSceneResponse, "appended_changes" | "moved_todos">): string {
  const parts: string[] = [];
  const changes = result.appended_changes.length;
  if (changes > 0) {
    parts.push(
      `${changes} ${changes === 1 ? "change" : "changes"} the rewrite didn't place ${changes === 1 ? "was" : "were"} added at the end.`,
    );
  }
  const todos = result.moved_todos;
  if (todos > 0) {
    parts.push(`${todos} to-do${todos === 1 ? "" : "s"} moved to the scene's to-do list.`);
  }
  return parts.length ? `Finalized. ${parts.join(" ")}` : "";
}
