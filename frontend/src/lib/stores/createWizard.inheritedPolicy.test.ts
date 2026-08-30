import { beforeEach, describe, expect, it, vi } from "vitest";

// #1672: entering the AI step resolves the policy the prospective project would
// inherit (value + provenance) so the slider's inherit note can name it. Mock the
// three navigation calls (mirrors validation.test.ts) — the new one is
// prospectiveAiPolicy.
const { prospectiveProjectNode, prospectiveAncestorCandidates, prospectiveAiPolicy } = vi.hoisted(
  () => ({
    prospectiveProjectNode: vi.fn(),
    prospectiveAncestorCandidates: vi.fn(),
    prospectiveAiPolicy: vi.fn(),
  }),
);
vi.mock("@/lib/api", () => ({
  api: { prospectiveProjectNode, prospectiveAncestorCandidates, prospectiveAiPolicy },
}));

import { createWizard } from "@/lib/stores/createWizard.svelte";

beforeEach(() => {
  prospectiveProjectNode
    .mockReset()
    .mockResolvedValue({ metadata_schema: { fields: [] }, metadata: {}, field_sources: {} });
  prospectiveAncestorCandidates.mockReset().mockResolvedValue([]);
  prospectiveAiPolicy.mockReset().mockResolvedValue({ policy: "cloud-allowed", source: "Universe" });
  createWizard.close();
  createWizard.onCreateProject = vi.fn().mockResolvedValue(undefined);
  createWizard.onSaveAppPolicy = vi.fn().mockResolvedValue(undefined);
  createWizard.onError = () => {};
});

describe("createWizard inherited AI policy (#1672)", () => {
  it("resolves the inherited policy + source on entering the AI step", async () => {
    createWizard.defaultProjectsFolder = "C:/root"; // returning user ⇒ starts on location
    createWizard.start();
    createWizard.title = "Book";
    createWizard.inherits = ["C:/root/universe"]; // a ticked ancestor

    await createWizard.next(); // location → ai
    expect(createWizard.currentStep.id).toBe("ai");

    await vi.waitFor(() => expect(createWizard.inheritedPolicy?.policy).toBe("cloud-allowed"));
    expect(createWizard.inheritedPolicy?.source).toBe("Universe");
    expect(prospectiveAiPolicy).toHaveBeenCalledWith(expect.any(String), ["C:/root/universe"]);
  });

  it("skips the fetch (nothing to inherit) when no ancestor is ticked", async () => {
    createWizard.defaultProjectsFolder = "C:/root";
    createWizard.start();
    createWizard.title = "Book";
    createWizard.inherits = [];

    await createWizard.next(); // location → ai
    expect(createWizard.currentStep.id).toBe("ai");
    expect(prospectiveAiPolicy).not.toHaveBeenCalled();
    expect(createWizard.inheritedPolicy).toBeNull();
  });

  it("degrades to null if the resolve fails (note falls back to generic copy)", async () => {
    prospectiveAiPolicy.mockRejectedValue(new Error("network"));
    createWizard.defaultProjectsFolder = "C:/root";
    createWizard.start();
    createWizard.title = "Book";
    createWizard.inherits = ["C:/root/universe"];

    await createWizard.next(); // location → ai
    await vi.waitFor(() => expect(prospectiveAiPolicy).toHaveBeenCalled());
    expect(createWizard.inheritedPolicy).toBeNull();
  });
});
