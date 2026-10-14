import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ api: {} }));

import { createWizard } from "@/lib/stores/createWizard.svelte";

// #2467: first-run escape hatch to the Open Project Folder picker.
describe("createWizard first-run open-existing", () => {
  it("firstRun is true with no projects folder, false with one", () => {
    createWizard.defaultProjectsFolder = "";
    createWizard.start();
    expect(createWizard.firstRun).toBe(true);
    createWizard.close();
    createWizard.defaultProjectsFolder = "C:/projects";
    createWizard.start();
    expect(createWizard.firstRun).toBe(false);
    createWizard.close();
  });

  it("openExistingInstead closes the wizard and calls the host", () => {
    const onOpenExisting = vi.fn();
    createWizard.onOpenExisting = onOpenExisting;
    createWizard.defaultProjectsFolder = "";
    createWizard.start();
    createWizard.openExistingInstead();
    expect(createWizard.open).toBe(false);
    expect(onOpenExisting).toHaveBeenCalledTimes(1);
  });
});
