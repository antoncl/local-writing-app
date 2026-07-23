import type { AncestorCandidate, ProjectChainLayer } from "@/lib/types";

/** One hop in the breadcrumb: somewhere the author can open. */
export type ChainCrumb = {
  path: string;
  label: string;
};

/**
 * The declared chain, outermost first, as breadcrumb hops (#311, #432).
 *
 * **Reads the resolved chain; derives nothing.** This used to filter
 * `ProjectInfo.ancestors` on `inherited && is_project` and label each hop
 * `title || name` — a transcription of `_project_layer_folders` and
 * `_layer_label_for_folder`, i.e. a second implementation of a traversal the
 * backend walker already owns. The two disagreed: the walker labels a
 * titleless outermost layer that is the machine root **"Base Folder"**, and
 * this labelled the same folder by its directory name, so the schema-layers
 * view and the breadcrumb could name one layer two ways in the same session.
 * `ProjectInfo.chain` now ships the walker's own answer.
 *
 * The only thing left here is presentation: drop the root layer. The chain
 * includes the open project as its innermost entry, and the bar renders that
 * as the project switcher rather than as a crumb.
 *
 * Gaps stay legal upstream (a project may declare a grandparent and not its
 * parent), so this is a path through the ancestry rather than a walk of
 * consecutive folders. #431 settled that the bar does NOT mark the gap: the
 * undeclared middle folder is not in `chain` (the backend yields only
 * `is_project and inherited` layers), so there is nothing here to hide or to
 * flag — the honest treatment of a deliberate, legal gap is to render the
 * declared layers contiguously, which is all this can do.
 */
export function declaredChain(chain: ProjectChainLayer[] | undefined): ChainCrumb[] {
  return (chain ?? [])
    .filter((layer) => !layer.is_root)
    .map((layer) => ({ path: layer.path, label: layer.label }));
}

/**
 * Does the open project inherit from nothing at all (#427)?
 *
 * Distinguishes the two ways `declaredChain` returns nothing, which the bar
 * has to render differently:
 *
 * - **no project open** — the chain is absent or empty, and the bar has no
 *   subject to say anything about;
 * - **a flat project** — the chain holds the open project and nothing else,
 *   because it declares no ancestors (ADR-0039 Amendment 1: absent means
 *   inherits nothing).
 *
 * The second used to render as blank space, which left the switcher button
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
