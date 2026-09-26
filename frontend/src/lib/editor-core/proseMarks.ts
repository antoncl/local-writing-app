// Custom TipTap marks used by ProseBodyView.
//
// - AISuggestion / TodoAnchor are self-contained (no project data needed).
// - CharacterMark needs to resolve a lore entry's display colour + title at
//   render time, so it's built via a factory that takes those resolvers — the
//   component keeps ownership of the reactive lore/schema lookups and passes
//   them in (same pattern as ImplicitContextHighlight's matcher option).
import { Mark, mergeAttributes, Node } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";

import { formatAnchorPlaces, mutationSetLabel } from "./mutationNodes";
import {
  mutationSetByAnchorIdStore,
  mutationSetRosterLoadedStore,
  mutationSetsByIdStore,
} from "@/lib/stores/mutationSets";

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
        // The character's private interiority for this beat (ADR-0070) — hidden
        // inner state bound to the beat, carried through the markdown round-trip
        // (markdown.ts) and kept per-character-private by the backend
        // (character_turns). No reveal UI yet (S2); it just rides the mark.
        internal: {
          default: "",
          parseHTML: (element) => element.getAttribute("data-internal") ?? "",
          renderHTML: (attributes) =>
            attributes.internal ? { "data-internal": String(attributes.internal) } : {},
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

// ADR-0095 §1: a pill is a pure ANCHOR — `{ setId, anchorId }` — and its
// label reads the mutation-sets STORE live, via a ProseMirror NodeView
// rather than TipTap's plain `renderHTML` (which only re-runs when a node's
// OWN attrs change). A NodeView subscribes once at mount and updates its own
// text/title whenever the store changes, so editing a set relabels every
// pill that anchors it with no document transaction. `data-mutation-id`
// keeps carrying the id `revealMutationPill`/todo reveals key on — now the
// ANCHOR id (it used to be the marker id; same attribute, new meaning).

function renderAnchorPill(dom: HTMLElement, setId: string, anchorId: string, rosterLoaded: boolean): void {
  const entry = setId ? mutationSetsByIdStoreSnapshot?.get(setId) : undefined;
  const missing = rosterLoaded && setId !== "" && !entry;
  dom.classList.toggle("mutation-pill-missing", missing);
  if (missing) {
    dom.textContent = "⤳";
    dom.title = "This mutation set no longer exists. Delete the pill, or restore the set.";
    return;
  }
  const label = mutationSetLabel(entry);
  // ADR-0095 §6/§8: a linked set (more than one anchor) tells its place
  // count in the pill text, and the OTHER places (this anchor's own
  // excluded) in the tooltip.
  const anchors = entry?.anchors ?? [];
  if (anchors.length > 1) {
    dom.textContent = `⤳ ${label} · ${anchors.length} places`;
    const otherPlaces = formatAnchorPlaces(
      anchors.filter((a) => a.anchor_id !== anchorId).map((a) => a.scene_title),
    );
    dom.title = otherPlaces ? `${label} — also in ${otherPlaces}` : label;
    return;
  }
  dom.textContent = label ? `⤳ ${label}` : "⤳";
  dom.title = label;
}

// A plain module-level snapshot (kept current by one subscription shared by
// every pill instance) — cheaper than each NodeView re-deriving the Map from
// the store on every render, and avoids importing `get()` per node.
let mutationSetsByIdStoreSnapshot:
  | ReadonlyMap<
      string,
      {
        title: string;
        rows: { field: string; op: string; value: string }[];
        anchors: { anchor_id: string; scene_id: string; scene_title: string }[];
      }
    >
  | undefined;
mutationSetsByIdStore.subscribe((byId) => {
  mutationSetsByIdStoreSnapshot = byId;
});
let rosterLoadedSnapshot = false;
mutationSetRosterLoadedStore.subscribe((loaded) => {
  rosterLoadedSnapshot = loaded;
});

/**
 * Build the mid-scene mutation-anchor pill (#33, ADR-0095 §1). Unlike
 * CharacterMark it wraps no prose — a mutation is a *point* ("the change
 * takes effect here") — so it's an inline atom Node, not a Mark. It
 * round-trips to `<!-- mutate:set=SET;id=ANCHOR -->` (lib/utils/markdown).
 */
export const createMutationMark = () =>
  Node.create({
    name: "mutation",
    inline: true,
    group: "inline",
    atom: true,
    selectable: true,
    addAttributes() {
      return {
        setId: {
          default: "",
          parseHTML: (element) => element.getAttribute("data-mutation-set") ?? "",
          renderHTML: (attributes) =>
            attributes.setId ? { "data-mutation-set": String(attributes.setId) } : {},
        },
        anchorId: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-mutation-id"),
          renderHTML: (attributes) =>
            attributes.anchorId ? { "data-mutation-id": String(attributes.anchorId) } : {},
        },
      };
    },
    parseHTML() {
      return [{ tag: "span[data-mutation-id]:not([data-mutation-close-ref])" }];
    },
    renderHTML({ node, HTMLAttributes }) {
      // Static fallback (SSR-less here, but TipTap calls this once before a
      // NodeView takes over, and it's what `editor.getHTML()` serializes
      // from for the markdown round-trip) — matches the NodeView's own text.
      const setId = String(node.attrs.setId ?? "");
      const entry = setId ? mutationSetsByIdStoreSnapshot?.get(setId) : undefined;
      const label = mutationSetLabel(entry);
      return ["span", mergeAttributes(HTMLAttributes, { class: "mutation-pill" }), label ? `⤳ ${label}` : "⤳"];
    },
    addNodeView() {
      return ({ node }: { node: PMNode }) => {
        const dom = document.createElement("span");
        dom.className = "mutation-pill";
        let currentNode = node;
        const render = (n: PMNode) =>
          renderAnchorPill(dom, String(n.attrs.setId ?? ""), String(n.attrs.anchorId ?? ""), rosterLoadedSnapshot);
        if (node.attrs.anchorId) dom.setAttribute("data-mutation-id", String(node.attrs.anchorId));
        if (node.attrs.setId) dom.setAttribute("data-mutation-set", String(node.attrs.setId));
        // Subscribing calls back synchronously with the current value (svelte
        // store contract), so `currentNode` must already be initialized above.
        const unsubscribeSets = mutationSetsByIdStore.subscribe(() => render(currentNode));
        const unsubscribeLoaded = mutationSetRosterLoadedStore.subscribe(() => render(currentNode));
        return {
          dom,
          update: (updated: PMNode) => {
            if (updated.type.name !== "mutation") return false;
            currentNode = updated;
            if (updated.attrs.anchorId) dom.setAttribute("data-mutation-id", String(updated.attrs.anchorId));
            if (updated.attrs.setId) dom.setAttribute("data-mutation-set", String(updated.attrs.setId));
            else dom.removeAttribute("data-mutation-set");
            render(updated);
            return true;
          },
          destroy: () => {
            unsubscribeSets();
            unsubscribeLoaded();
          },
        };
      };
    },
  });

/**
 * Build the interval-close pill (#59, ADR-0095 §1). A point node that
 * round-trips to `<!-- mutate:close;ref=..[;row=..];id=.. -->` — it ends the
 * anchor `ref` (optionally just one row of its set) at this prose position.
 * Its label resolves `ref` through the mutation-sets store's anchor index,
 * live, the same as the start pill — not by searching the open doc.
 */
export const createMutationCloseMark = () =>
  Node.create({
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
        row: {
          default: "",
          parseHTML: (element) => element.getAttribute("data-mutation-close-row") ?? "",
          renderHTML: (attributes) =>
            attributes.row ? { "data-mutation-close-row": String(attributes.row) } : {},
        },
        closeId: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-mutation-id"),
          renderHTML: (attributes) =>
            attributes.closeId ? { "data-mutation-id": String(attributes.closeId) } : {},
        },
      };
    },
    parseHTML() {
      return [{ tag: "span[data-mutation-close-ref]" }];
    },
    renderHTML({ node, HTMLAttributes }) {
      const label = closeLabelFromStore(String(node.attrs.ref ?? ""));
      const full = label ? `Closes ${label}` : "Closes a mutation";
      // "mutation ends here": ti-arrow-bar-to-right (a single lexicon-sanctioned
      // annotation glyph) rather than the banned `⤳✕` compound (#304). The mark
      // round-trips to an HTML comment, so this string is display-only.
      const icon = ["i", { class: "ti ti-arrow-bar-to-right", "aria-hidden": "true" }];
      // Turndown treats an element with no TEXT content as blank and drops it
      // outright — before any custom rule runs (the icon alone doesn't count,
      // it's a font glyph, not text) — so the pill always carries at least a
      // fallback glyph as real text, never just the icon.
      return [
        "span",
        mergeAttributes(HTMLAttributes, { class: "mutation-pill mutation-pill-close", title: full }),
        icon,
        label || "⤳",
      ];
    },
  });

let mutationSetByAnchorIdSnapshot: ReadonlyMap<string, { title: string; rows: { field: string; op: string; value: string }[] }> | undefined;
mutationSetByAnchorIdStore.subscribe((byAnchor) => {
  mutationSetByAnchorIdSnapshot = byAnchor;
});

function closeLabelFromStore(ref: string): string {
  if (!ref) return "";
  return mutationSetLabel(mutationSetByAnchorIdSnapshot?.get(ref));
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
