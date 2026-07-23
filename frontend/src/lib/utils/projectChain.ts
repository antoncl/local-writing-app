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
