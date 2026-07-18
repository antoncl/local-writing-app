// A one-line, human-readable summary of a view-designer node's config, shown on
// the COMPACT (unselected) node body so the resting canvas reads at a glance —
// selecting a node expands it to the full editor (ADR-0038 §A, #220). Pure over
// (kind, cfg) + a few schema resolvers, so it unit-tests without the SvelteFlow
// canvas (which can't be driven in the headless preview — banked gotcha).

import type { GraphNodeKind, PredicateKind, ViewNodeData } from "./viewGraph";
import type { ViewFieldPredicate, ViewLeafValue, ViewSort } from "@/lib/types";

export type SummaryResolvers = {
  // Display name for a metadata field key (falls back to the key).
  fieldName: (key: string) => string;
  // Display name for an entry_type FQN (falls back to the FQN).
  entryTypeName: (fqn: string) => string;
};

// Empty-slot placeholders — a compact node shows what it still needs, never a
// blank line, mirroring the expanded editor's "— pick … —" options. Keyed by node
// kind (nest/field_of) OR a Filter predicate slot (type/descendants_of/tagged/
// field — `PredicateKind`, no longer standalone node kinds; #271/#284).
const PLACEHOLDER: Partial<Record<GraphNodeKind | PredicateKind, string>> = {
  type: "— any type —",
  descendants_of: "— any type —",
  tagged: "— tag —",
  field: "— field —",
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
  const val = valueText(pred.value, cfg.param?.label);
  return val ? `${name} ${OP_LABEL[pred.op]} ${val}` : `${name} ${OP_LABEL[pred.op]}`;
}

// A leaf slot value → glance text. A promoted `{var}` shows ⟨param label⟩ (via
// valueText); a bare string resolves through the slot's formatter. Empty ⇒ the
// slot's placeholder.
function leafText(
  value: ViewLeafValue | undefined,
  paramLabel: string | undefined,
  fmt: (s: string) => string,
  placeholder: string,
): string {
  if (value == null || value === "") return placeholder;
  if (typeof value === "object") return valueText(value, paramLabel);
  return fmt(value);
}

// The predicate a Filter narrows on — reuses the leaf summaries by filter_kind.
function filterInner(cfg: ViewNodeData, r: SummaryResolvers): string {
  switch (cfg.filter_kind) {
    case "type":
      return leafText(cfg.type, cfg.param?.label, r.entryTypeName, PLACEHOLDER.type!);
    case "descendants_of":
      return leafText(cfg.descendants_of, cfg.param?.label, (s) => `${r.entryTypeName(s)} +sub`, PLACEHOLDER.type!);
    case "tagged":
      return leafText(cfg.tagged, cfg.param?.label, (s) => `#${s}`, PLACEHOLDER.tagged!);
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
