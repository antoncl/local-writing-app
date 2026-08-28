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
import { reportClientError } from "@/lib/errorLog";
import type {
  AssistantEntrySummary,
  CardSummary,
  LoreEntrySummary,
  MetadataSchema,
  NodePickerRef,
  StructureDocument,
  ViewSource,
  ViewSpec,
} from "@/lib/types";

/** A selector ref carries an inline `selector` ViewSource (a tag, a saved view,
 * or a plotline); a concrete member ref — or a backend-expanded manuscript
 * container — does not. The presence of the spec IS the definition, so a new
 * selector shape (slice 6's plotline container) needs no change here: no
 * hardcoded kind list to extend (ADR-0074 slice 6). */
export function isSelectorRef(ref: NodePickerRef): boolean {
  return ref.selector != null;
}

/** The rosters + schema needed to evaluate a selector's ViewSource. One is built
 * per surface from whatever node data it has in scope; a kind with no roster
 * expands to nothing — graceful on the live-count path (a rosterless tag is
 * dropped), but at SEND time an absent roster is a should-never-happen that is
 * logged (#1553, `selectorExpansionAnomaly`), since it silently shrinks what the
 * AI sees. */
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

/** Why a selector CANNOT be materialized against this roster — a should-never-
 * happen that expansion otherwise swallows to `[]` — or null if it can. This
 * distinguishes an anomaly from a *legitimately* empty result (roster present,
 * spec matches nothing), which is not flagged:
 *  - the selector carries no inline spec (a bare `{view:id}` the picker should
 *    have resolved before storing); or
 *  - the surface built no roster for the selector's kind (an omitted input to
 *    `buildSelectorRoster` — a present-but-empty `[]` roster is fine).
 * Used to log the send-time silent-zero (#1553); NOT called on the live-count
 * path, which tolerates absent rosters by design (a rosterless tag is dropped). */
export function selectorExpansionAnomaly(ref: NodePickerRef, roster: SelectorRoster): string | null {
  const resolved = specForSelector(ref);
  if (resolved === null) return `selector "${ref.id}" carries no inline spec to evaluate`;
  if (roster.rostersByKind[resolved.kind] === undefined) {
    return `no roster for kind "${resolved.kind}" on this surface (selector "${ref.id}")`;
  }
  return null;
}

/** Replace every selector ref in `refs` with its current member refs, passing
 * concrete member/container refs through untouched. Deduped by kind+id. Concrete
 * refs are emitted before selector-expanded members regardless of pick order, so
 * an explicit ref always keeps its `target` flag over a selector member of the
 * same id (the dedup is order-independent). */
export function expandSelectorRefs(refs: NodePickerRef[], roster: SelectorRoster): NodePickerRef[] {
  const out: NodePickerRef[] = [];
  const seen = new Set<string>();
  const push = (r: NodePickerRef): void => {
    const key = `${r.kind}:${r.id}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push(r);
  };
  for (const ref of refs) if (!isSelectorRef(ref)) push(ref);
  for (const ref of refs) if (isSelectorRef(ref)) for (const m of membersForSelector(ref, roster)) push(m);
  return out;
}

// One report per distinct anomaly per session (see below). A debounced estimate
// re-expands on every keystroke, so a single broken selector must not flood
// `errors.log` — deduping on the message keeps it to one durable signal.
const reportedSelectorAnomalies = new Set<string>();

/** The wire seam: expand any selectors in an encoded context_pick value, leaving
 * a selector-free value untouched (the fast path — most picks carry none). The
 * result is the encoded member-only string the backend can resolve.
 *
 * A selector that cannot be expanded here (no roster for its kind, or no inline
 * spec) is a should-never-happen that would otherwise drop the pick silently and
 * send the AI fewer nodes than the user chose. Because the selector is stripped
 * before the request, the backend can't recover it — so it is logged to the
 * durable error log (#1553), not swallowed. Expansion still proceeds (the pick
 * contributes nothing, as before); the log is the added signal, not a new
 * failure mode. */
export function expandSelectorsInEncodedValue(encoded: string, roster: SelectorRoster): string {
  const refs = decodePickerValue(encoded);
  if (!refs.some(isSelectorRef)) return encoded;
  for (const ref of refs) {
    if (!isSelectorRef(ref)) continue;
    const anomaly = selectorExpansionAnomaly(ref, roster);
    if (anomaly && !reportedSelectorAnomalies.has(anomaly)) {
      reportedSelectorAnomalies.add(anomaly);
      reportClientError(new Error(anomaly), "context-pick selector expansion");
    }
  }
  return encodePickerValue(expandSelectorRefs(refs, roster));
}

/** Inputs a surface has in scope, from which a SelectorRoster is built. All
 * optional — a surface passes what it has; absent kinds expand to nothing. */
export interface SelectorRosterInputs {
  schema?: MetadataSchema | null;
  structure?: StructureDocument | null;
  loreEntries?: LoreEntrySummary[];
  assistantEntries?: AssistantEntrySummary[];
  // The `plot` roster is CARDS, not plotlines (ADR-0074 slice 6): a plotline is a
  // container whose selector expands to the cards whose `metadata.plotline` points
  // at it, so the members it evaluates over are the cards.
  cardEntries?: CardSummary[];
}

/** Build the per-surface roster once, reusing the same kind→roster adapters the
 * view panes use (`structureToEvalNodes`, and the *EntrySummary shapes that
 * satisfy EvalNode structurally). */
export function buildSelectorRoster(inputs: SelectorRosterInputs): SelectorRoster {
  const rostersByKind: Partial<Record<string, EvalNode[]>> = {};
  if (inputs.loreEntries) rostersByKind.lore = inputs.loreEntries as unknown as EvalNode[];
  if (inputs.assistantEntries) rostersByKind.assistant = inputs.assistantEntries as unknown as EvalNode[];
  if (inputs.cardEntries) rostersByKind.plot = inputs.cardEntries as unknown as EvalNode[];
  if (inputs.structure) rostersByKind.manuscript = structureToEvalNodes(inputs.structure);
  return { rostersByKind, schema: inputs.schema ?? null };
}
