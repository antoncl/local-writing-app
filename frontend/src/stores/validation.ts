// Validation domain store — the latest project-validation/repair result shown
// in the Project pane's validation panel. Produced by the validate/repair
// handlers (and refreshed as a side effect of schema mutations). Server-mirrored
// slice extracted from App.svelte for the #14 state layer; `writable` for
// legacy-safe reads (see docs/frontend-architecture.md).

import { writable } from "svelte/store";
import type { ProjectValidation } from "../types";

export const validationStore = writable<ProjectValidation | null>(null);

export function setValidation(result: ProjectValidation | null): void {
  validationStore.set(result);
}

export function clearValidation(): void {
  validationStore.set(null);
}
