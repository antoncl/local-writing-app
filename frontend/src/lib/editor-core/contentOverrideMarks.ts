// The title/body override marks (#2184 slice 3, ADR-0039 Amendment 4 §9),
// split out of NodeEditor (#2473). Title/body have no rail row, so their
// "overridden here" tell renders beside the thing it marks — after the title
// input and on the Body tab label. Lore only (§5): a prompt's title and body
// change only by cloning, never by override. Pure — a function of the document.
import type { DocumentKind, EditableDocument } from "@/lib/types";

export interface ContentOverrideMark {
  chipText: string;
  tooltip: string;
  ariaLabel: string;
}

export interface ContentOverrideMarks {
  // The layer the override shadows ("inherited" when the document names none).
  sourceLabel: string;
  title: ContentOverrideMark | null;
  body: ContentOverrideMark | null;
}

// `canReset` is the gate the rail's reset marks use (`MetadataPanel`'s
// `canResetOverride`): a reset handler is wired AND the pane is not read-only
// — and, ADR-0095 §8, not at a scrub stop either (a title/body override reset
// edits base/override state, never a mutation set).
export function contentOverrideMarks(
  scene: EditableDocument | null | undefined,
  documentKind: DocumentKind,
  canReset: boolean,
): ContentOverrideMarks {
  const overriddenContent =
    documentKind === "lore" && scene && "overridden_content" in scene
      ? ((scene as unknown as { overridden_content?: string[] }).overridden_content ?? [])
      : [];
  const inheritedTitle =
    documentKind === "lore" && scene && "inherited_title" in scene
      ? ((scene as unknown as { inherited_title?: string | null }).inherited_title ?? null)
      : null;
  const sourceLabel = scene?.source_layer_label ?? "inherited";
  return {
    sourceLabel,
    title:
      canReset && overriddenContent.includes("title")
        ? {
            chipText: `Reset to ${sourceLabel}`,
            tooltip:
              inheritedTitle != null
                ? `Overridden here — ${sourceLabel}'s title is "${inheritedTitle}".`
                : `Overridden here — ${sourceLabel}'s title.`,
            ariaLabel: `Reset the title to ${sourceLabel}'s`,
          }
        : null,
    body:
      canReset && overriddenContent.includes("body")
        ? {
            chipText: `Reset to ${sourceLabel}…`,
            tooltip: `Overridden here — the body you see is this layer's, not ${sourceLabel}'s.`,
            ariaLabel: `Reset the body to ${sourceLabel}'s`,
          }
        : null,
  };
}
