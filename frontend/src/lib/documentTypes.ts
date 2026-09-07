// Editable-document discriminator wire types. Extracted from types.ts to keep
// that barrel under the file-size cap; re-exported from `@/lib/types` so it
// stays the single import surface.

import type { Scene } from "./manuscriptTypes";
import type { LoreEntry, ResearchNote } from "./loreTypes";
import type { PromptEntry } from "./promptTypes";
import type { AssistantEntry } from "./assistantTypes";
import type { ViewNode } from "./viewTypes";
import type { TagEntry } from "./tagTypes";
import type { PlotTemplate } from "./plotTemplateTypes";
import type { CardEntry, PlotlineEntry } from "./plotCardTypes";

export type EditableDocument = Scene | LoreEntry | PromptEntry | AssistantEntry | ResearchNote | ViewNode | PlotTemplate | CardEntry | PlotlineEntry | TagEntry;

// Document-kind discriminator: schema kinds plus synthetic editor shapes (chat / snippet / structure_node / plot_card / plotline).
export type DocumentKind =
  | "manuscript"
  | "lore"
  | "prompt"
  | "snippet"
  | "assistant"
  | "research"
  | "chat"
  | "project"
  | "structure_node"
  | "plot_template"
  | "plot_card"
  | "plotline"
  | "view"
  | "tag";
