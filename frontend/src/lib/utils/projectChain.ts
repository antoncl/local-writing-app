import type { AncestorCandidate } from "@/lib/types";

/** One hop in the breadcrumb: somewhere the author can open. */
export type ChainCrumb = {
  path: string;
  label: string;
};

/**
 * The declared chain, outermost first, as breadcrumb hops (#311).
 *
 * `ProjectInfo.ancestors` is the **whole** enumeration by design — every folder
 * between the configured base and the open project, flagged rather than
 * filtered, because #318's wizard needs the undeclared rows in order to offer
 * them and a non-project folder must be visible and marked rather than absent.
 * The breadcrumb is the other consumer, and it wants the opposite: only the
 * levels this project actually inherits from, because those are the only ones
 * that are part of what is being built here.
 *
 * Both flags are required, not just `inherited`. A declared entry that stopped
 * being a project keeps its declaration — the backend survives it with a
 * warning rather than dropping it silently — so `inherited` alone would put a
 * row in the path with no title to render and nothing to open.
 *
 * Gaps are legal upstream (a project may declare a grandparent and not its
 * parent), so this is a path through the ancestry, not necessarily a walk of
 * consecutive folders. That is the declaration being honoured, not a defect.
 */
export function declaredChain(ancestors: AncestorCandidate[] | undefined): ChainCrumb[] {
  return (ancestors ?? [])
    .filter((row) => row.inherited && row.is_project)
    .map((row) => ({ path: row.path, label: row.title?.trim() || row.name }));
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
