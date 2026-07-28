import { beforeEach, describe, expect, it, vi } from "vitest";

// #423: removing a stale recents entry rewrites the whole list through the
// machine-settings PUT (the backend has no dedicated remove endpoint). Mock the
// HTTP client and the two fan-outs projectSession imports at module load, so the
// test is about the filter-then-persist behaviour, not the network.
const { updateMachineSettings } = vi.hoisted(() => ({ updateMachineSettings: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { updateMachineSettings } }));
vi.mock("@/lib/stores/assistants", () => ({ refreshAssistantEntries: vi.fn() }));
vi.mock("@/lib/utils/colors", () => ({ setPalette: vi.fn() }));

import { projectSession } from "@/lib/stores/projectSession.svelte";
import type { MachineSettingsView, RecentProject } from "@/lib/types";

const recent = (path: string, title: string): RecentProject => ({
  path,
  title,
  opened_at: "2026-01-01T00:00:00Z",
  within_root: true,
});

const view = (recents: RecentProject[]): MachineSettingsView =>
  ({ recent_projects: recents, palette: [], providers: {} }) as unknown as MachineSettingsView;

describe("removeRecentProject (#423)", () => {
  beforeEach(() => {
    updateMachineSettings.mockReset();
    projectSession.recentProjects = [recent("/a", "A"), recent("/b", "B"), recent("/c", "C")];
  });

  it("PUTs the list minus the removed path and adopts the server's rewritten list", async () => {
    const remaining = [recent("/a", "A"), recent("/c", "C")];
    updateMachineSettings.mockResolvedValue(view(remaining));

    await projectSession.removeRecentProject("/b");

    expect(updateMachineSettings).toHaveBeenCalledTimes(1);
    expect(updateMachineSettings).toHaveBeenCalledWith({ recent_projects: remaining });
    // State comes from the response, not from the optimistic local filter.
    expect(projectSession.recentProjects).toEqual(remaining);
  });

  it("clears the last entry (an empty list is a valid rewrite)", async () => {
    projectSession.recentProjects = [recent("/only", "Only")];
    updateMachineSettings.mockResolvedValue(view([]));

    await projectSession.removeRecentProject("/only");

    expect(updateMachineSettings).toHaveBeenCalledWith({ recent_projects: [] });
    expect(projectSession.recentProjects).toEqual([]);
  });

  it("removing an unknown path is a no-op rewrite of the current list", async () => {
    const current = [recent("/a", "A"), recent("/b", "B"), recent("/c", "C")];
    updateMachineSettings.mockResolvedValue(view(current));

    await projectSession.removeRecentProject("/does-not-exist");

    expect(updateMachineSettings).toHaveBeenCalledWith({ recent_projects: current });
  });

  it("serializes a burst of removes so none is lost (#423 review)", async () => {
    // Server echoes whatever list it is sent, so the only thing that decides the
    // outcome is which list each remove computed from.
    updateMachineSettings.mockImplementation((update) =>
      Promise.resolve(view(update.recent_projects ?? [])),
    );

    // Two removes fired without awaiting between them — a burst of × clicks.
    const first = projectSession.removeRecentProject("/b");
    const second = projectSession.removeRecentProject("/c");
    await Promise.all([first, second]);

    // Both removals survive. Without serialization the second read the stale
    // pre-removal list and the later response resurrected /b or /c.
    expect(projectSession.recentProjects.map((r) => r.path)).toEqual(["/a"]);
    // The second PUT was computed AFTER the first landed — it saw [/a,/c].
    expect(updateMachineSettings).toHaveBeenNthCalledWith(2, {
      recent_projects: [recent("/a", "A")],
    });
  });
});
