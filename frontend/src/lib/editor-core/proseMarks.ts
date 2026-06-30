// Custom TipTap marks used by ProseBodyView.
//
// - AISuggestion / TodoAnchor are self-contained (no project data needed).
// - CharacterMark needs to resolve a lore entry's display colour + title at
//   render time, so it's built via a factory that takes those resolvers — the
//   component keeps ownership of the reactive lore/schema lookups and passes
//   them in (same pattern as ImplicitContextHighlight's matcher option).
import { Mark, mergeAttributes } from "@tiptap/core";

export const AISuggestion = Mark.create({
  name: "aiSuggestion",
  inclusive: false,
  excludes: "",
  addAttributes() {
    return {
      suggestionId: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-ai-suggestion-id"),
        renderHTML: (attributes) => {
          if (!attributes.suggestionId) return {};
          return { "data-ai-suggestion-id": attributes.suggestionId };
        },
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-ai-suggestion-id]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { class: "ai-suggestion" }), 0];
  },
});

export interface CharacterMarkResolvers {
  /** Resolve a lore entry id to a CSS colour (hex or hsl). */
  colorForId: (id: string) => string;
  /** Resolve a lore entry id to a human-readable tooltip title. */
  titleForId: (id: string) => string;
}

/**
 * Build the per-character mark. The resolvers are read at renderHTML time, so
 * the component can hand in closures over its reactive `loreEntries` /
 * `metadataSchema` and colours/titles stay live.
 */
export function createCharacterMark({ colorForId, titleForId }: CharacterMarkResolvers) {
  return Mark.create({
    name: "character",
    inclusive: false,
    excludes: "",
    addAttributes() {
      return {
        characterId: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-character"),
          renderHTML: (attributes) => {
            if (!attributes.characterId) return {};
            const id = String(attributes.characterId);
            return {
              "data-character": id,
              title: titleForId(id),
              style: `--character-color: ${colorForId(id)}`,
            };
          },
        },
      };
    },
    parseHTML() {
      return [{ tag: "span[data-character]" }];
    },
    renderHTML({ HTMLAttributes }) {
      return ["span", mergeAttributes(HTMLAttributes, { class: "character-mark" }), 0];
    },
  });
}

export const TodoAnchor = Mark.create({
  name: "todoAnchor",
  inclusive: false,
  addAttributes() {
    return {
      anchorId: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-todo-id") ?? element.getAttribute("data-todo-anchor-id"),
        renderHTML: (attributes) => {
          if (!attributes.anchorId) return {};
          return { "data-todo-id": attributes.anchorId };
        },
      },
      status: {
        default: "open",
        parseHTML: (element) => (element.getAttribute("data-todo-status") === "done" ? "done" : "open"),
        renderHTML: (attributes) => ({ "data-todo-status": attributes.status === "done" ? "done" : "open" }),
      },
      note: {
        default: "",
        parseHTML: (element) => element.getAttribute("data-todo-note") ?? "",
        renderHTML: (attributes) => ({ "data-todo-note": attributes.note ?? "" }),
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-todo-id]" }, { tag: "span[data-todo-anchor-id]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { class: "todo-anchor" }), 0];
  },
});
