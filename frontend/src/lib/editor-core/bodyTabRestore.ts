// Pure restore rule behind NodeEditor's body-tab memory (#2013). Extracted so
// it's unit-testable without mounting NodeEditor (not mountable under
// happy-dom): a remembered tab is only honoured if it still names a real tab
// on THIS node's current strip — a schema/entry-type change since the tab was
// last remembered can drop the field a list tab pointed at, and a "body"
// tab id is always valid (the strip may be empty — no tabs at all — and
// "body" is still the one body view NodeEditor always renders).
import type { BodyTab } from "@/lib/editor-core/bodyTabs";

export function restoredBodyTab(remembered: string | undefined, tabs: BodyTab[]): string {
  if (!remembered || remembered === "body") return "body";
  return tabs.some((tab) => tab.id === remembered) ? remembered : "body";
}
