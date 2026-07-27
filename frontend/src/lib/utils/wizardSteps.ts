// Create-project wizard step sequencing and the per-step consistency gate
// (#318 / design-doc §4). Pure and dependency-free so it can be unit-tested —
// the frontend has no component-test infra, so the wizard's control flow lives
// here rather than inside the Svelte view.
//
// This slice ships steps 1–2; later slices insert "ai" | "review" | "describe"
// between "location" and the final Create action.

export type WizardStepId = "root" | "location";

export type StepDef = { id: WizardStepId; label: string };

const ALL_STEPS: StepDef[] = [
  { id: "root", label: "Root folder" },
  { id: "location", label: "Location" },
];

// The root-folder step is machine substrate (#429): it exists only on first
// run, when no default projects folder is configured yet. Once one is set every
// creation starts at "Location".
export function activeSteps(needsRootFolder: boolean): StepDef[] {
  return ALL_STEPS.filter((step) => step.id !== "root" || needsRootFolder);
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
};

// The consistency gate (design-doc §4): a step cannot be advanced past until its
// own inputs are valid, so an inconsistent step is never carried forward.
// Inheritance has no gate — ticking zero ancestors is a legal (flat) project —
// so "location" is complete once it has a title and a folder to build under.
export function stepComplete(id: WizardStepId, snapshot: WizardSnapshot): boolean {
  switch (id) {
    case "root":
      return snapshot.rootFolderDraft.trim().length > 0;
    case "location":
      return snapshot.title.trim().length > 0 && snapshot.pickedFolder.trim().length > 0;
  }
}
