import { beforeEach, describe, expect, it, vi } from "vitest";

// #1404: the first-run wizard skipped the LOCATION step (where the title is
// entered) after saving the root, so it could complete with an empty title and
// 422. These tests pin (a) root-save lands on "location", (b) the authoritative
// completion gate, and (c) the touched title error. The review step reads the
// backend, so mock the two calls navigation makes (mirrors submit.test.ts).
const { prospectiveProjectNode, prospectiveAncestorCandidates } = vi.hoisted(() => ({
  prospectiveProjectNode: vi.fn(),
  prospectiveAncestorCandidates: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  api: { prospectiveProjectNode, prospectiveAncestorCandidates },
}));

import { createWizard } from "@/lib/stores/createWizard.svelte";

beforeEach(() => {
  prospectiveProjectNode.mockReset().mockResolvedValue({
    metadata_schema: { fields: [] },
    metadata: {},
    field_sources: {},
  });
  prospectiveAncestorCandidates.mockReset().mockResolvedValue([]);
  createWizard.close();
  createWizard.onCreateProject = vi.fn().mockResolvedValue(undefined);
  createWizard.onSaveAppPolicy = vi.fn().mockResolvedValue(undefined);
  createWizard.onError = () => {};
  // The first-run root save flips the machine root, collapsing the root step.
  createWizard.onSaveRootFolder = async () => {
    createWizard.defaultProjectsFolder = "C:/root";
  };
});

describe("createWizard first-run navigation (#1404)", () => {
  it("saving the root folder lands on LOCATION, not skipping to AI", async () => {
    createWizard.defaultProjectsFolder = ""; // no root yet ⇒ first run
    createWizard.start();
    expect(createWizard.currentStep.id).toBe("root");
    createWizard.rootFolderDraft = "C:/root";

    await createWizard.next();

    // The title-collecting step must be shown — the regression skipped it.
    expect(createWizard.currentStep.id).toBe("location");
    expect(createWizard.title).toBe("");
  });
});

describe("createWizard completion gate (#1404)", () => {
  it("canComplete requires a set root, a title, and a folder", () => {
    createWizard.defaultProjectsFolder = "C:/root"; // root set ⇒ not first run
    createWizard.start();
    createWizard.pickedFolder = "C:/root";

    createWizard.title = "";
    expect(createWizard.canComplete).toBe(false);

    createWizard.title = "My Book";
    expect(createWizard.canComplete).toBe(true);

    createWizard.pickedFolder = "";
    expect(createWizard.canComplete).toBe(false);
  });
});

describe("createWizard title error (#1404)", () => {
  it("appears only once the field is touched and empty", () => {
    createWizard.defaultProjectsFolder = "C:/root";
    createWizard.start();

    expect(createWizard.titleError).toBe(""); // untouched ⇒ no nag
    createWizard.markTitleTouched();
    expect(createWizard.titleError).toBe("Project name is required.");
    createWizard.title = "My Book";
    expect(createWizard.titleError).toBe("");
  });
});
