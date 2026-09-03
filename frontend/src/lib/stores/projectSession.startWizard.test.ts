import { beforeEach, describe, expect, it, vi } from "vitest";

// The wizard must read FRESH machine settings when it opens (#556), so its
// `needsRootFolder` reflects the current backend state rather than a value
// cached at app init. Mock the HTTP client and the two fan-outs
// `loadMachineSettings` triggers so the test is about the read-then-open
// ordering, not the network. Same shape as projectSession.declaration.test.ts.
const { getMachineSettings } = vi.hoisted(() => ({ getMachineSettings: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { getMachineSettings } }));

const { refreshAssistantEntries } = vi.hoisted(() => ({ refreshAssistantEntries: vi.fn() }));
vi.mock("@/lib/stores/assistants", () => ({ refreshAssistantEntries }));

// Machine-global tag roster (ADR-0082 slice 1): `loadMachineSettings` hydrates
// it alongside the assistant roster (review fix F4) — mocked out the same way.
const { refreshTagNodes } = vi.hoisted(() => ({ refreshTagNodes: vi.fn() }));
vi.mock("@/lib/stores/tagNodes", () => ({ refreshTagNodes }));

vi.mock("@/lib/utils/colors", () => ({ setPalette: vi.fn() }));

import { createWizard } from "@/lib/stores/createWizard.svelte";
import { projectSession } from "@/lib/stores/projectSession.svelte";
import type { MachineSettingsView } from "@/lib/types";

const settings = (folder: string): MachineSettingsView =>
  ({
    default_projects_folder: folder,
    recent_projects: [],
    palette: [],
    providers: {},
  }) as unknown as MachineSettingsView;

describe("startCreateWizard (#556)", () => {
  beforeEach(() => {
    getMachineSettings.mockReset();
    refreshAssistantEntries.mockReset().mockResolvedValue(undefined);
    refreshTagNodes.mockReset().mockResolvedValue(undefined);
    createWizard.close();
    // Simulate a stale-empty cache from app init: without the fresh read this
    // is what would (wrongly) show the first-run root step.
    createWizard.defaultProjectsFolder = "";
  });

  it("reads fresh machine settings before opening, so needsRootFolder is not stale", async () => {
    getMachineSettings.mockResolvedValue(settings("C:/Users/anton/Documents"));

    await projectSession.startCreateWizard();

    expect(getMachineSettings).toHaveBeenCalledTimes(1);
    expect(createWizard.defaultProjectsFolder).toBe("C:/Users/anton/Documents");
    // The configured root is now visible, so the first-run root step is skipped
    // instead of reappearing and letting the author overwrite the real root.
    expect(createWizard.needsRootFolder).toBe(false);
    expect(createWizard.open).toBe(true);
  });

  it("shows the root step only when the root is genuinely unset", async () => {
    getMachineSettings.mockResolvedValue(settings(""));

    await projectSession.startCreateWizard();

    expect(createWizard.needsRootFolder).toBe(true);
    expect(createWizard.open).toBe(true);
  });

  it("still opens when the settings fetch fails (offline), keeping the last value", async () => {
    createWizard.defaultProjectsFolder = "C:/prev";
    getMachineSettings.mockRejectedValue(new Error("offline"));

    await projectSession.startCreateWizard();

    // loadMachineSettings swallows the error; the wizard still opens on the
    // last-known value — no worse than the previous behaviour.
    expect(createWizard.open).toBe(true);
    expect(createWizard.defaultProjectsFolder).toBe("C:/prev");
  });
});
