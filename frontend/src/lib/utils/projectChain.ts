import type { AncestorCandidate, ProjectChainLayer } from "@/lib/types";

/**
 * The one place the `is_project` × `inherited` cross is named (#417 slice 4).
 * Both the breadcrumb (`declaredChain`) and the declaration editor
 * (`declarationRows`) read the same two backend booleans, so they must agree on
 * what a folder IS — deriving the cross twice is exactly the walker-vs-frontend
 * drift #432 deleted, and both consumers live in this one file. (`DeclarationRowState`
 * is declared lower; TS type aliases hoist.)
 */
export function inheritanceState(isProject: boolean, inherited: boolean): DeclarationRowState {
  if (isProject) return inherited ? "declared" : "available";
  return inherited ? "stale" : "folder";
}

/**
 * A crumb's inheritance state (#417 slice 4). The bar can only ever show three
 * of `inheritanceState`'s four cells: a pure `folder` has no inheritance state,
 * so the backend omits it and `declaredChain` drops one defensively if it ever
 * leaks through. `declared` renders solid, `available` dimmed, `stale` flagged.
 */
export type ChainCrumbState = Exclude<DeclarationRowState, "folder">;

/** One hop in the breadcrumb. */
export type ChainCrumb = {
  path: string;
  label: string;
  // `state` decides navigability too, so there is no separate `navigable` field
  // (#763.3): a `declared`/`available` crumb is a real project and opens; a
  // `stale` crumb's `project.yaml` is gone, so there is nothing to open — the
  // component branches on `state === "stale"` directly, which is all a
  // `navigable` boolean ever encoded (`navigable === state !== "stale"`).
  state: ChainCrumbState;
};

/**
 * The chain, outermost first, as breadcrumb hops (#311, #432; #417 slice 4).
 *
 * **Reads the resolved chain; derives nothing but presentation.** Labels are
 * the walker's own (#432 deleted the frontend transcript that filtered
 * `ancestors` and re-labelled `title || name`, because it disagreed with the
 * walker over the machine-root "Base Folder" case). This maps to crumbs and
 * drops the root layer, which the bar renders as the project switcher rather
 * than as a crumb.
 *
 * The one behaviour change is the reversal of #431. #431 rendered only the
 * declared layers, contiguously, so a legal gap (a project declaring a
 * grandparent and skipping its parent) was invisible. The bar now doubles as
 * the inheritance-state display, so the backend carries the skipped ancestors,
 * and each crumb gets a `state`: `available` (an ancestor project not inherited
 * — the skipped layer, dimmed) and `stale` (a declared ancestor whose manifest
 * is gone — flagged) join `declared`. Making the gap visible where the author
 * who set it up would notice it is the point; a pure organisational folder,
 * which has no inheritance state to show, the backend still omits.
 */
export function declaredChain(chain: ProjectChainLayer[] | undefined): ChainCrumb[] {
  const crumbs: ChainCrumb[] = [];
  for (const layer of chain ?? []) {
    if (layer.is_root) continue;
    const state = inheritanceState(layer.is_project, layer.inherited);
    // The backend omits a pure organisational folder from the chain; if one
    // ever leaks through, drop it here rather than mislabel it `stale` (fail
    // safe, not fail loud). This also narrows `state` to `ChainCrumbState`.
    if (state === "folder") continue;
    crumbs.push({ path: layer.path, label: layer.label, state });
  }
  return crumbs;
}

/**
 * Does the open project inherit from nothing at all (#427)?
 *
 * Distinguishes the two ways `declaredChain` returns nothing, which the bar
 * has to render differently:
 *
 * - **no project open** — the chain is absent or empty, and the bar has no
 *   subject to say anything about;
 * - **a flat project** — the chain holds the open project and nothing else.
 *
 * Since #417 slice 4 the second means the project has **no ancestor projects at
 * all** (it sits directly inside the machine root, or outside it): there is
 * nothing to render even dimmed. A project that merely declares no ancestors
 * but has one above it is no longer "nothing" — that ancestor now shows as an
 * `available` crumb, which is the whole point of the reversal. The note is
 * reserved for the genuinely-empty case.
 *
 * The flat case used to render as blank space, which left the switcher button
 * beside it reading as a one-item breadcrumb — the mechanism behind the
 * misclick in #427. It gets a stated note instead.
 */
export function inheritsNothing(chain: ProjectChainLayer[] | undefined): boolean {
  const layers = chain ?? [];
  // "A project is open but has no crumbs" — i.e. every layer is the root. This
  // is the same predicate `declaredChain` filters on (`!is_root`), inlined to
  // avoid building the two throwaway arrays just to read their length.
  return layers.length > 0 && layers.every((layer) => layer.is_root);
}

/**
 * What the declaration editor does with one enumerated ancestor (#426).
 *
 * The three states are the enumeration's own model — `is_project` crossed with
 * `inherited` — plus the fourth cell of that cross, which is the one the
 * backend warns about rather than dropping:
 *
 * - `declared` — a layer this project inherits from. Untick to remove it.
 * - `available` — an ancestor project it could inherit from. Tick to add it.
 * - `folder` — an organisational folder with no `project.yaml`. Shown and
 *   disabled: there is nothing to layer. Omitting it would leave a hole in the
 *   list that reads as a defect rather than as information.
 * - `stale` — declared, but no longer a project. Ticked and flagged, because
 *   the author ticked something and is getting silence. Unticking is the
 *   repair; re-ticking is not offered, and after the untick the row simply
 *   becomes a `folder`.
 */
export type DeclarationRowState = "declared" | "available" | "folder" | "stale";

/** One row in the declaration editor. */
export type DeclarationRow = {
  path: string;
  label: string;
  /** Why this row cannot be ticked, or the folder name when it adds anything. */
  detail: string | null;
  state: DeclarationRowState;
  checked: boolean;
  /** `folder` is the only state with no gesture — there is nothing to declare. */
  toggleable: boolean;
};

/**
 * The whole enumeration as editor rows, outermost first (#426).
 *
 * Unlike `declaredChain` this filters nothing: the point of the editor is to
 * offer the rows the breadcrumb hides. Order is the backend's, which is
 * outermost-first, so the list reads down towards the open project.
 */
export function declarationRows(ancestors: AncestorCandidate[] | undefined): DeclarationRow[] {
  return (ancestors ?? []).map((row) => {
    const label = row.title?.trim() || row.name;
    const named = label !== row.name ? row.name : null;
    const state = inheritanceState(row.is_project, row.inherited);
    return {
      path: row.path,
      label,
      // The `stale`/`folder` details match what `declared_ancestor_warnings`
      // says about each case, so the row and the validation report do not
      // describe the same folder in two different vocabularies; a project row
      // shows its folder name only when the title differs.
      detail:
        state === "stale"
          ? "Declared, but no longer a project — it contributes nothing."
          : state === "folder"
            ? "Not a project — nothing to inherit."
            : named,
      state,
      checked: row.inherited,
      // A pure `folder` is the only state with no gesture; declared/available
      // tick to add/remove and `stale`'s untick is the repair.
      toggleable: state !== "folder",
    };
  });
}

/**
 * The declaration to send after ticking or unticking `path` (#426).
 *
 * Absolute paths: `_validated_declaration` accepts either form and stores the
 * project-relative one, so the frontend never has to know the stored shape.
 *
 * Derived from the enumeration rather than from a local draft, which also makes
 * it the repair for a declared entry that is not an ancestor at all — the other
 * warning `declared_ancestor_warnings` produces. Such an entry is not in
 * `ancestors` (it is outside the walk), the backend already ignores it, and
 * rewriting the list from what is enumerated drops it.
 */
export function toggledDeclaration(
  ancestors: AncestorCandidate[] | undefined,
  path: string,
): string[] {
  const rows = ancestors ?? [];
  const remove = rows.some((row) => row.path === path && row.inherited);
  return rows
    .filter((row) => (row.path === path ? !remove : row.inherited))
    .map((row) => row.path);
}
