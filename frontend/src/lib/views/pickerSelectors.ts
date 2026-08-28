// ADR-0074 slice 5 — invocation-time expansion of context-picker SELECTORS.
//
// A picked tag or saved view is stored as ONE live selector ref (a NodePickerRef
// with kind "tag"/"view" carrying a `selector` ViewSource). At invocation the
// selector expands to its CURRENT members by evaluating the ViewSource against
// the kind's roster — so a member added later is included without re-picking
// (the "live" semantics). This runs frontend-side because view evaluation is
// frontend-only (ADR-0025 / Amendment 1); the backend never sees a selector,
// only the concrete member refs it expands to.
//
// The seam: each picker surface (chat, dialog, preview) calls
// `expandSelectorsInEncodedValue` on a context_pick value right after
// `coerceInputValue`, before the API call. `coerceInputValue` itself stays pure
// (roster-blind) — see lib/utils/promptInputs.ts.

import { decodePickerValue, encodePickerValue } from "@/lib/utils/promptInputs";
import { evaluateView, type EvalNode } from "@/lib/views/evaluateView";
import { structureToEvalNodes } from "@/lib/views/structureNodes";
import type {
  AssistantEntrySummary,
  LoreEntrySummary,
  MetadataSchema,
  NodePickerRef,
  PlotlineSummary,
  StructureDocument,
  ViewSource,
  ViewSpec,
} from "@/lib/types";

/** A selector ref (kind "tag"/"view") carries a `selector`; a member ref does not. */
export function isSelectorRef(ref: NodePickerRef): boolean {
  return ref.kind === "tag" || ref.kind === "view";
}

/** The rosters + schema needed to evaluate a selector's ViewSource. One is built
 * per surface from whatever node data it has in scope; a kind with no roster
 * simply expands to nothing (graceful — a stale/unavailable selector is empty,
 * never an error). */
export interface SelectorRoster {
  rostersByKind: Partial<Record<string, EvalNode[]>>;
  schema?: MetadataSchema | null;
}

/** Resolve a selector ref to the ViewSpec to evaluate and the kind whose roster
 * it runs against. Slice 5 stores the resolved spec inline (`{kind, expr}`), so
 * this is a direct read; a bare `{view:id}` ref (no inline spec) can't be
 * resolved here without a loaded view and yields null. */
function specForSelector(ref: NodePickerRef): { spec: ViewSpec; kind: string } | null {
  const sel = ref.selector as ViewSource | undefined;
  if (!sel || typeof sel !== "object") return null;
  if ("kind" in sel && typeof sel.kind === "string") {
    return { spec: sel, kind: sel.kind };
  }
  // A bare ViewRef ({view:id}) with no inline spec — not resolvable without the
  // view loaded. The picker bakes the spec in, so this is the defensive branch.
  return null;
}

/** An evaluated node → the member NodePickerRef the pick set carries. A scene's
 * canonical id is its `ref_id` (scene_id); other kinds use `id`. */
function memberRef(node: EvalNode, kind: string): NodePickerRef {
  return {
    id: node.ref_id ?? node.id,
    kind: kind as NodePickerRef["kind"],
    title: node.title,
    entry_type: node.entry_type,
  };
}

/** The live members a selector currently resolves to — the evaluated, deduped
 * node list mapped to member refs. Empty when the spec can't be resolved or the
 * kind has no roster. */
export function membersForSelector(ref: NodePickerRef, roster: SelectorRoster): NodePickerRef[] {
  const resolved = specForSelector(ref);
  if (resolved === null) return [];
  const nodes = roster.rostersByKind[resolved.kind] ?? [];
  const result = evaluateView(resolved.spec, nodes, { schema: roster.schema ?? null });
  return result.nodes.map((n) => memberRef(n, resolved.kind));
}

/** Replace every selector ref in `refs` with its current member refs, passing
 * concrete member/container refs through untouched. Deduped by kind+id, first
 * occurrence wins (so an explicit ref keeps its `target` flag over a selector
 * member of the same id). */
export function expandSelectorRefs(refs: NodePickerRef[], roster: SelectorRoster): NodePickerRef[] {
  const out: NodePickerRef[] = [];
  const seen = new Set<string>();
  const push = (r: NodePickerRef): void => {
    const key = `${r.kind}:${r.id}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push(r);
  };
  for (const ref of refs) {
    if (isSelectorRef(ref)) {
      for (const m of membersForSelector(ref, roster)) push(m);
    } else {
      push(ref);
    }
  }
  return out;
}

/** The wire seam: expand any selectors in an encoded context_pick value, leaving
 * a selector-free value untouched (the fast path — most picks carry none). The
 * result is the encoded member-only string the backend can resolve. */
export function expandSelectorsInEncodedValue(encoded: string, roster: SelectorRoster): string {
  const refs = decodePickerValue(encoded);
  if (!refs.some(isSelectorRef)) return encoded;
  return encodePickerValue(expandSelectorRefs(refs, roster));
}

/** Inputs a surface has in scope, from which a SelectorRoster is built. All
 * optional — a surface passes what it has; absent kinds expand to nothing. */
export interface SelectorRosterInputs {
  schema?: MetadataSchema | null;
  structure?: StructureDocument | null;
  loreEntries?: LoreEntrySummary[];
  assistantEntries?: AssistantEntrySummary[];
  plotEntries?: PlotlineSummary[];
}

/** Build the per-surface roster once, reusing the same kind→roster adapters the
 * view panes use (`structureToEvalNodes`, and the *EntrySummary shapes that
 * satisfy EvalNode structurally). */
export function buildSelectorRoster(inputs: SelectorRosterInputs): SelectorRoster {
  const rostersByKind: Partial<Record<string, EvalNode[]>> = {};
  if (inputs.loreEntries) rostersByKind.lore = inputs.loreEntries as unknown as EvalNode[];
  if (inputs.assistantEntries) rostersByKind.assistant = inputs.assistantEntries as unknown as EvalNode[];
  if (inputs.plotEntries) rostersByKind.plot = inputs.plotEntries as unknown as EvalNode[];
  if (inputs.structure) rostersByKind.manuscript = structureToEvalNodes(inputs.structure);
  return { rostersByKind, schema: inputs.schema ?? null };
}
