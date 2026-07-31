import type { AncestorCandidate, ProjectChainLayer } from "@/lib/types";

/**
 * A crumb's inheritance state — the `is_project` × `inherited` cross the
 * backend now ships on each chain layer (#417 slice 4). Drives how the bar
 * renders it: `declared` solid, `available` dimmed, `stale` flagged.
 */
export type ChainCrumbState = "declared" | "available" | "stale";

/** One hop in the breadcrumb. */
export type ChainCrumb = {
  path: string;
  label: string;
  state: ChainCrumbState;
  /**
   * Whether selecting it opens that project. A `declared`/`available` crumb is
   * a real project and navigates; a `stale` crumb is a folder whose
   * `project.yaml` is gone, so there is nothing to open — it is shown as a
   * flagged, non-navigable marker whose repair lives in the declaration editor.
   */
  navigable: boolean;
};

function crumbState(layer: ProjectChainLayer): ChainCrumbState {
  if (layer.is_project) return layer.inherited ? "declared" : "available";
  return "stale"; // a non-project layer only reaches the chain when inherited
}

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
  return (chain ?? [])
    .filter((layer) => !layer.is_root)
    .map((layer) => ({
      path: layer.path,
      label: layer.label,
      state: crumbState(layer),
      navigable: layer.is_project,
    }));
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
    if (row.is_project) {
      return {
        path: row.path,
        label,
        detail: named,
        state: row.inherited ? "declared" : "available",
        checked: row.inherited,
        toggleable: true,
      };
    }
    return {
      path: row.path,
      label,
      // Matches what `declared_ancestor_warnings` says about each case, so the
      // row and the validation report do not describe the same folder in two
      // different vocabularies.
      detail: row.inherited
        ? "Declared, but no longer a project — it contributes nothing."
        : "Not a project — nothing to inherit.",
      state: row.inherited ? "stale" : "folder",
      checked: row.inherited,
      toggleable: row.inherited,
    };
  });
}

/**
 * Would the declaration editor have anything to act on for this project (#427)?
 *
 * The gate on the empty-chain note's "set up…" remedy. Offering the link when
 * the editor opens onto nothing tickable is the same defect the note removes —
 * an affordance that promises something it does not have — so it is withheld in
 * exactly the cases `declarationRows` produces no actionable row:
 *
 * - **outside the machine root, or none set (#429)** — the enumeration is
 *   empty, so there are no rows at all;
 * - **a top-level project** directly inside the projects folder — its only
 *   enumerated ancestor is that root folder, which is not a project and renders
 *   as a permanently-disabled row.
 *
 * Derived FROM `declarationRows` rather than re-deriving "is_project means
 * declarable" inline, so the breadcrumb and the editor cannot disagree about
 * what is actionable. `toggleable` — not `is_project` — is the right test: a
 * declared ancestor that stopped being a project (#431's stale case) is not a
 * project yet is still repairable by unticking, and the editor offers exactly
 * that, so the remedy should point there too.
 */
export function canDeclareInheritance(ancestors: AncestorCandidate[] | undefined): boolean {
  return declarationRows(ancestors).some((row) => row.toggleable);
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
