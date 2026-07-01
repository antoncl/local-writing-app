// Custom TipTap marks used by ProseBodyView.
//
// - AISuggestion / TodoAnchor are self-contained (no project data needed).
// - CharacterMark needs to resolve a lore entry's display colour + title at
//   render time, so it's built via a factory that takes those resolvers — the
//   component keeps ownership of the reactive lore/schema lookups and passes
//   them in (same pattern as ImplicitContextHighlight's matcher option).
import { Mark, mergeAttributes, Node } from "@tiptap/core";

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

export interface MutationMarkResolvers {
  /** Human label for the pill, e.g. "Honor → Captain". Read at render time so
   *  the pill stays live against the reactive lore/schema stores. */
  labelForMarker: (entityId: string, field: string, value: string, op?: string) => string;
}

// Compact pill glyph for a collection op (#58): add prefixes +, remove −.
function opGlyph(op: string): string {
  if (op === "add") return "+";
  if (op === "remove") return "−";
  return "";
}

/**
 * Build the mid-scene lore-mutation pill (#33). Unlike CharacterMark it wraps no
 * prose — a mutation is a *point* ("the change happens here"), so it's an inline
 * atom Node, not a Mark. It round-trips to a self-contained scene-body comment
 * `<!-- mutate:entity=..;field=..;value=..;id=.. -->` (see lib/utils/markdown).
 * The label resolver is read at renderHTML time (mirrors CharacterMark).
 */
export function createMutationMark({ labelForMarker }: MutationMarkResolvers) {
  return Node.create({
    name: "mutation",
    inline: true,
    group: "inline",
    atom: true,
    selectable: true,
    addAttributes() {
      return {
        entity: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-mutation-entity"),
          renderHTML: (attributes) =>
            attributes.entity ? { "data-mutation-entity": String(attributes.entity) } : {},
        },
        field: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-mutation-field"),
          renderHTML: (attributes) =>
            attributes.field ? { "data-mutation-field": String(attributes.field) } : {},
        },
        op: {
          default: "replace",
          parseHTML: (element) => element.getAttribute("data-mutation-op") || "replace",
          renderHTML: (attributes) =>
            attributes.op && attributes.op !== "replace"
              ? { "data-mutation-op": String(attributes.op) }
              : {},
        },
        value: {
          default: "",
          parseHTML: (element) => element.getAttribute("data-mutation-value") ?? "",
          renderHTML: (attributes) => ({ "data-mutation-value": String(attributes.value ?? "") }),
        },
        name: {
          default: "",
          parseHTML: (element) => element.getAttribute("data-mutation-name") ?? "",
          renderHTML: (attributes) =>
            attributes.name ? { "data-mutation-name": String(attributes.name) } : {},
        },
        group: {
          default: "",
          parseHTML: (element) => element.getAttribute("data-mutation-group") ?? "",
          renderHTML: (attributes) =>
            attributes.group ? { "data-mutation-group": String(attributes.group) } : {},
        },
        markerId: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-mutation-id"),
          renderHTML: (attributes) =>
            attributes.markerId ? { "data-mutation-id": String(attributes.markerId) } : {},
        },
      };
    },
    parseHTML() {
      return [{ tag: "span[data-mutation-entity]" }];
    },
    renderHTML({ node, HTMLAttributes }) {
      const value = String(node.attrs.value ?? "");
      const op = String(node.attrs.op ?? "replace");
      const name = String(node.attrs.name ?? "");
      // Full label goes in the tooltip; the inline pill stays compact so prose
      // reads cleanly — it just marks "the change happens here". A collection op
      // shows its +/− glyph; a named change prefers the name.
      const full = labelForMarker(
        String(node.attrs.entity ?? ""),
        String(node.attrs.field ?? ""),
        value,
        op,
      );
      const glyph = opGlyph(op);
      const body = name || (glyph ? `${glyph}${value}` : value);
      const compact = body ? `⤳ ${body}` : "⤳";
      return ["span", mergeAttributes(HTMLAttributes, { class: "mutation-pill", title: full }), compact];
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
