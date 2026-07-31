import { beforeEach, describe, expect, it, vi } from "vitest";

// §7 of #746: where the wizard's AI-step policy lands depends on the run.
// On FIRST run (no machine root yet) it establishes the APP-WIDE default and the
// first project inherits it (per-project policy left unstated). On a SUBSEQUENT
// run it is a per-project choice on the new project. These tests drive the real
// stepper to submit() and assert the routing. The review step reads the backend,
// so mock the HTTP client to the two calls navigation makes.
const { prospectiveProjectNode, prospectiveAncestorCandidates } = vi.hoisted(() => ({
  prospectiveProjectNode: vi.fn(),
  prospectiveAncestorCandidates: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  api: { prospectiveProjectNode, prospectiveAncestorCandidates },
}));

import { createWizard } from "@/lib/stores/createWizard.svelte";

async function driveToSubmit() {
  // Advance to the final step regardless of which steps this run shows, then
  // submit. Bounded so a routing regression can't spin forever.
  for (let i = 0; i < 8 && !createWizard.isFinalStep; i++) await createWizard.next();
  await createWizard.submit();
}

let onCreateProject: ReturnType<typeof vi.fn>;
let onSaveAppPolicy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  prospectiveProjectNode.mockReset().mockResolvedValue({
    metadata_schema: { fields: [] },
    metadata: {},
    field_sources: {},
  });
  prospectiveAncestorCandidates.mockReset().mockResolvedValue([]);
  createWizard.close();
  onCreateProject = vi.fn().mockResolvedValue(undefined);
  onSaveAppPolicy = vi.fn().mockResolvedValue(undefined);
  createWizard.onCreateProject = onCreateProject;
  createWizard.onSaveAppPolicy = onSaveAppPolicy;
  createWizard.onError = () => {};
  // The first-run root save flips the machine root, collapsing the root step.
  createWizard.onSaveRootFolder = async () => {
    createWizard.defaultProjectsFolder = "C:/root";
  };
});

describe("createWizard.submit — AI policy routing (#746 §7)", () => {
  it("first run: a concrete policy becomes the app-wide default, project left to inherit", async () => {
    createWizard.defaultProjectsFolder = ""; // no root yet ⇒ first run
    createWizard.start();
    createWizard.rootFolderDraft = "C:/root";
    createWizard.title = "First Book";
    createWizard.pickedFolder = "C:/root";
    createWizard.setAiPolicy("cloud-allowed");

    await driveToSubmit();

    expect(onSaveAppPolicy).toHaveBeenCalledExactlyOnceWith("cloud-allowed");
    // The new project states nothing — it inherits the app default just set.
    const [, , , aiPolicyArg] = onCreateProject.mock.calls[0];
    expect(aiPolicyArg).toBeUndefined();
  });

  it("subsequent run: a concrete policy is applied per-project, not app-wide", async () => {
    createWizard.defaultProjectsFolder = "C:/root"; // root already set ⇒ not first run
    createWizard.start();
    createWizard.title = "Second Book";
    createWizard.pickedFolder = "C:/root";
    createWizard.setAiPolicy("cloud-allowed");

    await driveToSubmit();

    expect(onSaveAppPolicy).not.toHaveBeenCalled();
    const [, , , aiPolicyArg] = onCreateProject.mock.calls[0];
    expect(aiPolicyArg).toBe("cloud-allowed");
  });

  it("first run with inherit stated writes no app policy — inherit is absence", async () => {
    createWizard.defaultProjectsFolder = ""; // first run
    createWizard.start();
    createWizard.rootFolderDraft = "C:/root";
    createWizard.title = "Quiet Book";
    createWizard.pickedFolder = "C:/root";
    // Leave the default "inherit": nothing concrete to persist anywhere.

    await driveToSubmit();

    expect(onSaveAppPolicy).not.toHaveBeenCalled();
    const [, , , aiPolicyArg] = onCreateProject.mock.calls[0];
    expect(aiPolicyArg).toBeUndefined();
  });
});
