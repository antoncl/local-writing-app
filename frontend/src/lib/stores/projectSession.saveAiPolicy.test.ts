import { beforeEach, describe, expect, it, vi } from "vitest";

// saveAiPolicy is the single write path for the app-wide default (#746) — used
// by both the Settings control and the wizard's first-run step. Pin that it PUTs
// { ai_policy } to the MACHINE settings endpoint (not the per-project one) and
// re-syncs the local view. Mock the HTTP client; the dialog/wizard tests stop
// above this method, so without this the payload is unverified.
const { updateMachineSettings } = vi.hoisted(() => ({ updateMachineSettings: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { updateMachineSettings } }));

import { projectSession } from "@/lib/stores/projectSession.svelte";
import type { MachineSettingsView } from "@/lib/types";

beforeEach(() => {
  updateMachineSettings.mockReset();
});

describe("projectSession.saveAiPolicy (#746)", () => {
  it("PUTs { ai_policy } to machine settings and re-syncs the view", async () => {
    const view = { ai_policy: "cloud-allowed" } as unknown as MachineSettingsView;
    updateMachineSettings.mockResolvedValue(view);

    const ok = await projectSession.saveAiPolicy("cloud-allowed");

    expect(updateMachineSettings).toHaveBeenCalledExactlyOnceWith({ ai_policy: "cloud-allowed" });
    expect(projectSession.machineSettings).toBe(view);
    expect(ok).toBe(true);
  });
});
