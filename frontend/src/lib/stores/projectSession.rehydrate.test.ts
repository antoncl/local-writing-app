import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// First-run onboarding (#1400): on boot, once machine settings load and the
// last-project reopen resolves, a genuine fresh install (no project reopened +
// unset root) must land in the create wizard, not a blank welcome screen. Mock
// the HTTP client and the fan-outs `loadMachineSettings` triggers so the test is
// about the rehydrate ordering/guards, not the network. Same shape as
// projectSession.startWizard.test.ts.
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

describe("projectSession.rehydrate — first-run onboarding (#1400)", () => {
  beforeEach(() => {
    getMachineSettings.mockReset();
    refreshAssistantEntries.mockReset().mockResolvedValue(undefined);
    refreshTagNodes.mockReset().mockResolvedValue(undefined);
    createWizard.close();
    createWizard.defaultProjectsFolder = "";
    // The singleton persists across tests; reset the field the offline guard reads.
    projectSession.machineSettings = null;
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens the wizard on a fresh install (nothing reopened, root unset)", async () => {
    getMachineSettings.mockResolvedValue(settings(""));
    vi.spyOn(projectSession, "readLastProject").mockReturnValue(null);

    await projectSession.rehydrate();

    expect(createWizard.needsRootFolder).toBe(true);
    expect(createWizard.open).toBe(true);
    // loadMachineSettings hydrates the machine-global tag roster alongside
    // the assistant one (review fix F4) — pin the fan-out itself, not just
    // its downstream effect.
    expect(refreshTagNodes).toHaveBeenCalled();
  });

  it("does not open the wizard for a returning user (root already set)", async () => {
    getMachineSettings.mockResolvedValue(settings("C:/Users/anton/Documents"));
    vi.spyOn(projectSession, "readLastProject").mockReturnValue(null);

    await projectSession.rehydrate();

    expect(createWizard.needsRootFolder).toBe(false);
    expect(createWizard.open).toBe(false);
  });

  it("does not open the wizard when the last project reopened", async () => {
    // Root unset is contrived here (a real last project implies a root); the
    // point is that a reopened project suppresses the first-run wizard.
    getMachineSettings.mockResolvedValue(settings(""));
    vi.spyOn(projectSession, "readLastProject").mockReturnValue("C:/proj");
    vi.spyOn(projectSession, "openProjectAt").mockResolvedValue(true);

    await projectSession.rehydrate();

    expect(createWizard.open).toBe(false);
  });

  it("does not force the wizard when settings failed to load (offline boot)", async () => {
    getMachineSettings.mockRejectedValue(new Error("offline"));
    vi.spyOn(projectSession, "readLastProject").mockReturnValue(null);

    await projectSession.rehydrate();

    // machineSettings stayed null → first-run couldn't be confirmed → no forced
    // wizard (whose folder step needs the backend anyway).
    expect(createWizard.open).toBe(false);
  });
});
