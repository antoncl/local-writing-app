// Create-project wizard step sequencing and the per-step consistency gate
// (#318 / design-doc §4). Pure and dependency-free so it can be unit-tested —
// the frontend has no component-test infra, so the wizard's control flow lives
// here rather than inside the Svelte view.
//
// Steps 1–2 shipped in slice 2; slice 3 (#547) inserted "ai" between "location"
// and the final Create action. Slice 4 (#552) appends "review" | "describe"
// after it, moving Create onto the last step ("describe").

import { rootContainsProject } from "@/lib/utils/openExistingProject";

export type WizardStepId =
  | "start"
  | "open_root"
  | "root"
  | "location"
  | "ai"
  | "review"
  | "describe";

export type StepDef = { id: WizardStepId; label: string };

const ALL_STEPS: StepDef[] = [
  { id: "start", label: "Welcome" },
  { id: "open_root", label: "Open project" },
  { id: "root", label: "Root folder" },
  { id: "location", label: "Location" },
  { id: "ai", label: "AI" },
  { id: "review", label: "Book settings" },
  { id: "describe", label: "Description" },
];

// The root-folder step is machine substrate (#429): it exists only on first
// run, when no default projects folder is configured yet. Once one is set every
// creation starts at "Location".
//
// The same first-run condition adds a "start" (Welcome) step ahead of it (#2467):
// create a project or open an existing one. Choosing Open swaps the rest of the
// flow for the single "open_root" step (pick the projects folder, then open).
export function activeSteps(needsRootFolder: boolean, openingExisting = false): StepDef[] {
  if (openingExisting) {
    return ALL_STEPS.filter((step) => step.id === "start" || step.id === "open_root");
  }
  return ALL_STEPS.filter(
    (step) => step.id !== "open_root" && ((step.id !== "root" && step.id !== "start") || needsRootFolder),
  );
}

export function indexOfStep(steps: StepDef[], id: WizardStepId): number {
  return steps.findIndex((step) => step.id === id);
}

// The fields a step reads to decide whether it is internally consistent. One
// flat snapshot rather than the live controller so the gate stays pure.
export type WizardSnapshot = {
  rootFolderDraft: string;
  title: string;
  pickedFolder: string;
  // The existing project being opened (#2467), "" outside the open flow.
  openProjectPath: string;
};

// The consistency gate (design-doc §4): a step cannot be advanced past until its
// own inputs are valid, so an inconsistent step is never carried forward.
// Inheritance has no gate — ticking zero ancestors is a legal (flat) project —
// so "location" is complete once it has a title and a folder to build under.
export function stepComplete(id: WizardStepId, snapshot: WizardSnapshot): boolean {
  switch (id) {
    case "start":
      // Advances only through its two choices, never a generic Next.
      return false;
    case "open_root":
      return (
        snapshot.rootFolderDraft.trim().length > 0 &&
        rootContainsProject(snapshot.rootFolderDraft, snapshot.openProjectPath)
      );
    case "root":
      return snapshot.rootFolderDraft.trim().length > 0;
    case "location":
      return snapshot.title.trim().length > 0 && snapshot.pickedFolder.trim().length > 0;
    case "ai":
      // The policy slider always holds a value (Off is a legal terminal state),
      // so the AI step is never inconsistent — like inheritance, it has no gate.
      return true;
    case "review":
      // The review pane shows the resolved field picture; every field either
      // inherits or carries a default, so there is nothing to leave invalid.
      return true;
    case "describe":
      // The description is skippable (§5) — an empty blurb is a legal project.
      return true;
  }
}
