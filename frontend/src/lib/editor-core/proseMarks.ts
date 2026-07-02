// Custom TipTap marks used by ProseBodyView.
//
// - AISuggestion / TodoAnchor are self-contained (no project data needed).
// - CharacterMark needs to resolve a lore entry's display colour + title at
//   render time, so it's built via a factory that takes those resolvers — the
//   component keeps ownership of the reactive lore/schema lookups and passes
//   them in (same pattern as ImplicitContextHighlight's matcher option).
import { Mark, mergeAttributes, Node } from "@tiptap/core";

import { unitRows } from "./mutationNodes";

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
 * atom Node, not a Mark. Since #69 (ADR-0016) one pill is one mutation UNIT:
 * entity + optional name + N field rows carried in the `rows` attr (JSON in the
 * DOM), each row keeping its own id/lifetime. It round-trips to the single-line
 * comment for one row, the multi-line carrier for more (see lib/utils/markdown).
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
        rows: {
          default: [],
          parseHTML: (element) => {
            const raw = element.getAttribute("data-mutation-rows");
            if (raw) {
              try {
                const parsed = JSON.parse(raw);
                if (Array.isArray(parsed)) return parsed;
              } catch {
                // fall through to the legacy single-field shape
              }
            }
            // Pasted HTML from a pre-#69 session carries one field per span.
            const field = element.getAttribute("data-mutation-field");
            if (!field) return [];
            return [
              {
                id: element.getAttribute("data-mutation-id") ?? "",
                field,
                op: element.getAttribute("data-mutation-op") || "replace",
                value: element.getAttribute("data-mutation-value") ?? "",
              },
            ];
          },
          renderHTML: (attributes) => ({
            "data-mutation-rows": JSON.stringify(
              Array.isArray(attributes.rows) ? attributes.rows : [],
            ),
          }),
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
      const entity = String(node.attrs.entity ?? "");
      const name = String(node.attrs.name ?? "");
      const rows = unitRows(node.attrs);
      // Full per-row labels go in the tooltip; the inline pill stays compact so
      // prose reads cleanly. One row shows its +/−glyph+value (or the name); a
      // multi-row unit shows its name with a ·N count, else "N changes" — the
      // pill IS the unit's frame (#70).
      const full = rows
        .map((row) => labelForMarker(entity, row.field, row.value, row.op))
        .join("\n");
      let body: string;
      if (rows.length > 1) {
        body = name ? `${name} ·${rows.length}` : `${rows.length} changes`;
      } else {
        const row = rows[0];
        const glyph = row ? opGlyph(row.op) : "";
        body = name || (row ? (glyph ? `${glyph}${row.value}` : row.value) : "");
      }
      const compact = body ? `⤳ ${body}` : "⤳";
      return ["span", mergeAttributes(HTMLAttributes, { class: "mutation-pill", title: full }), compact];
    },
  });
}

export interface MutationCloseResolvers {
  /** Human label for the record a close ends (its name / auto-label), resolved
   *  live so the pill tracks edits to the referenced start marker. */
  labelForClose: (ref: string) => string;
}

/**
 * Build the interval-close pill (#59). A point node that round-trips to
 * `<!-- mutate:close;ref=..;id=.. -->` — it ends the record `ref` at this prose
 * position (live iff start ≤ pos < close). Rendered as a distinct "closes X" pill.
 */
export function createMutationCloseMark({ labelForClose }: MutationCloseResolvers) {
  return Node.create({
    name: "mutationClose",
    inline: true,
    group: "inline",
    atom: true,
    selectable: true,
    addAttributes() {
      return {
        ref: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-mutation-close-ref"),
          renderHTML: (attributes) =>
            attributes.ref ? { "data-mutation-close-ref": String(attributes.ref) } : {},
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
      return [{ tag: "span[data-mutation-close-ref]" }];
    },
    renderHTML({ node, HTMLAttributes }) {
      const label = labelForClose(String(node.attrs.ref ?? ""));
      const full = label ? `Closes ${label}` : "Closes a mutation";
      const compact = label ? `⤳✕ ${label}` : "⤳✕";
      return [
        "span",
        mergeAttributes(HTMLAttributes, { class: "mutation-pill mutation-pill-close", title: full }),
        compact,
      ];
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
