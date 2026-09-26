// ADR-0095 §8 (decision 1's S1-race fix): the ONE decision behind NodeEditor's
// scrub-refresh effect — an entity switch (a genuinely different node opened)
// resets the scrub controller to base (`load`); a version bump for the SAME
// entity (a stop edit, a scene autosave, a set change elsewhere) re-anchors it
// in place instead (`reload`), never both for one trigger. Pure and
// side-effect-free so the decision is unit-testable off `$effect`/the
// controller itself — NodeEditor just acts on the answer.
export type ScrubRefreshAction = "load" | "reload" | "none";

export function scrubRefreshAction(prevEntityId: string | null, entityId: string | null): ScrubRefreshAction {
  if (entityId !== prevEntityId) return "load";
  if (entityId) return "reload";
  return "none";
}
