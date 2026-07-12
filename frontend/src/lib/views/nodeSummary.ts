// A one-line, human-readable summary of a view-designer node's config, shown on
// the COMPACT (unselected) node body so the resting canvas reads at a glance —
// selecting a node expands it to the full editor (ADR-0038 §A, #220). Pure over
// (kind, cfg) + a few schema resolvers, so it unit-tests without the SvelteFlow
// canvas (which can't be driven in the headless preview — banked gotcha).

import type { GraphNodeKind, ViewNodeData } from "./viewGraph";
import type { ViewFieldPredicate, ViewSort } from "@/lib/types";

export type SummaryResolvers = {
  // Display name for a metadata field key (falls back to the key).
  fieldName: (key: string) => string;
  // Display name for an entry_type FQN (falls back to the FQN).
  entryTypeName: (fqn: string) => string;
  // Title for a saved-view node id (falls back to the id).
  savedViewTitle: (id: string) => string;
};

// Empty-slot placeholders — a compact node shows what it still needs, never a
// blank line, mirroring the expanded editor's "— pick … —" options.
const PLACEHOLDER: Partial<Record<GraphNodeKind, string>> = {
  type: "— any type —",
  descendants_of: "— any type —",
  tagged: "— tag —",
  field: "— field —",
  view_ref: "— saved view —",
  nest: "— link field —",
  field_of: "— follow field —",
};

const OP_LABEL: Record<ViewFieldPredicate["op"], string> = {
  overlap: "any of",
  disjoint: "none of",
  set: "is set",
  unset: "is empty",
};

// A predicate value slot → short text. `{var}` (a promoted formal) shows the
// parameter's label; arrays join; everything else stringifies. Reference ids
// stay raw here (resolving them needs the full rosters) — the expanded editor
// renders the real widget; the compact line is a glance aid.
function valueText(value: unknown, paramLabel?: string): string {
  if (value == null || value === "") return "";
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if ("var" in obj) return `⟨${paramLabel || String(obj.var)}⟩`;
    if ("field_of" in obj) return "⟨projection⟩";
    if (Array.isArray(value)) return value.map(String).join(", ");
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

function fieldSummary(cfg: ViewNodeData, r: SummaryResolvers): string {
  const pred = cfg.field;
  if (!pred?.key) return PLACEHOLDER.field!;
  const name = r.fieldName(pred.key);
  if (pred.op === "set" || pred.op === "unset") return `${name} ${OP_LABEL[pred.op]}`;
  const val = valueText(pred.value, cfg.field_param?.label);
  return val ? `${name} ${OP_LABEL[pred.op]} ${val}` : `${name} ${OP_LABEL[pred.op]}`;
}

// The predicate a Filter narrows on — reuses the leaf summaries by filter_kind.
function filterInner(cfg: ViewNodeData, r: SummaryResolvers): string {
  switch (cfg.filter_kind) {
    case "type":
      return cfg.type ? r.entryTypeName(cfg.type) : PLACEHOLDER.type!;
    case "descendants_of":
      return cfg.descendants_of ? `${r.entryTypeName(cfg.descendants_of)} +sub` : PLACEHOLDER.type!;
    case "tagged":
      return cfg.tagged ? `#${cfg.tagged}` : PLACEHOLDER.tagged!;
    case "field":
    default:
      return fieldSummary(cfg, r);
  }
}

function sortSummary(sort: ViewSort | null | undefined, r: SummaryResolvers): string {
  const parts: string[] = [];
  // Depth-cap the `then` walk (matches the evaluator's sortKeyChain guard) so a
  // malformed cyclic chain can't hang the render.
  let s: ViewSort | null | undefined = sort;
  for (let i = 0; s && i < 16; s = s.then, i++) {
    if (s.by === "title") parts.push(`title ${s.dir === "desc" ? "↓" : "↑"}`);
    else if (s.by === "field") parts.push(`${r.fieldName(s.field_key ?? "")} ${s.dir === "desc" ? "↓" : "↑"}`);
    // by:"manual" contributes no key
  }
  return parts.length ? parts.join(", ") : "manual order";
}

export function nodeSummary(kind: GraphNodeKind, cfg: ViewNodeData, r: SummaryResolvers): string {
  switch (kind) {
    case "type":
      return cfg.type ? r.entryTypeName(cfg.type) : PLACEHOLDER.type!;
    case "descendants_of":
      return cfg.descendants_of ? `${r.entryTypeName(cfg.descendants_of)} +sub` : PLACEHOLDER.descendants_of!;
    case "tagged":
      return cfg.tagged ? `#${cfg.tagged}` : PLACEHOLDER.tagged!;
    case "field":
      return fieldSummary(cfg, r);
    case "filter": {
      const mode = cfg.filter_mode === "drop" ? "drop" : "keep";
      return `${mode} · ${filterInner(cfg, r)}`;
    }
    case "sorter":
      return sortSummary(cfg.sort, r);
    case "hand_picked": {
      const n = cfg.hand_picked?.length ?? 0;
      return n === 0 ? "none picked" : `${n} node${n === 1 ? "" : "s"}`;
    }
    case "view_ref":
      return cfg.view_ref ? r.savedViewTitle(cfg.view_ref) : PLACEHOLDER.view_ref!;
    case "nest":
      return cfg.match?.field ? r.fieldName(cfg.match.field) : PLACEHOLDER.nest!;
    case "field_of":
      return cfg.project_field ? `→ ${r.fieldName(cfg.project_field)}` : PLACEHOLDER.field_of!;
    // highlight (colour shown via the swatch), output (groups shown as ports),
    // self / all / set-algebra combinators — structural, no one-line value.
    default:
      return "";
  }
}
