// The designer palette (ADR-0038 §B), extracted from ViewBodyView (size cap).
//
// The algebra has two roles: a SOURCE injects a node set, an OPERATION
// transforms one. The bare predicate leaves (`type / descendants_of / tagged /
// field`) are fully retired (#271/#284) — `All → Filter` composes the identical
// lowering through one UI path, and post-ADR-0036 `All` is a real kind universe,
// so nothing is lost. A predicate now lives ONLY inside a first-class `{filter}`;
// `specToGraph` drops any bare predicate leaf on open (there is no node for it),
// and no default or user view carries one. Each chip carries the kind's ViewGlyph
// (the same mark as the node header, §240), so it needs no per-item colour cue.
import { defaultFilterKind, type GraphNodeKind, type ViewNodeData } from "@/lib/views/viewGraph";

export type PalItem = { kind: GraphNodeKind; label: string };

export const PALETTE: { label: string; items: PalItem[] }[] = [
  {
    label: "Sources",
    items: [
      { kind: "all", label: "All" },
      { kind: "hand_picked", label: "Hand-picked" },
    ],
  },
  {
    label: "Operations",
    items: [
      { kind: "filter", label: "Filter" },
      { kind: "field_of", label: "Field of" },
      { kind: "union", label: "Union" },
      { kind: "intersect", label: "Intersect" },
      { kind: "difference", label: "Difference" },
      { kind: "complement", label: "Complement" },
      { kind: "nest", label: "Nest" },
      { kind: "sorter", label: "Sort" },
      { kind: "highlight", label: "Highlight" },
    ],
  },
];

export function defaultCfg(k: GraphNodeKind, hasTypeChoice: boolean): ViewNodeData {
  if (k === "filter") return { filter_mode: "keep", filter_kind: defaultFilterKind(hasTypeChoice) };
  if (k === "sorter") return { sort: { by: "field", field_key: "title", dir: "asc" } };
  if (k === "nest") return { match: { field: "", direction: "child_to_parent", by: "ref" } };
  return {};
}
