// The open paths' fan-out order (#1881): `openProjectAt` / `createProjectAt`
// clear the domain stores (`clearProjectData`) right after the workspace reset
// and BEFORE `loadProjectData`, in the same tick — so project A's lists,
// rosters and totals are never on offer under project B's title while B's
// answers are in flight. Before #1881 `clearProjectData` had no caller at all.
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  openProject: vi.fn(),
  createProject: vi.fn(),
  getMachineSettings: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api }));

const fanOut = vi.hoisted(() => ({ loadProjectData: vi.fn(), clearProjectData: vi.fn() }));
vi.mock("@/lib/stores/index", () => fanOut);

import { projectSession } from "@/lib/stores/projectSession.svelte";
import type { ProjectInfo } from "@/lib/types";

const PROJECT_B = { title: "Book Two", root_path: "/w/book-two" } as ProjectInfo;

describe("project open fan-out order (#1881)", () => {
  const onOpenWorkspace = vi.fn();

  beforeEach(() => {
    api.openProject.mockReset().mockResolvedValue(PROJECT_B);
    api.createProject.mockReset().mockResolvedValue(PROJECT_B);
    api.getMachineSettings.mockReset().mockResolvedValue({ recent_projects: [] });
    fanOut.loadProjectData.mockReset().mockResolvedValue(undefined);
    fanOut.clearProjectData.mockReset();
    onOpenWorkspace.mockReset();
    projectSession.onOpenWorkspace = onOpenWorkspace;
    projectSession.onProjectDataLoaded = () => {};
    projectSession.setStatus = () => {};
  });

  function order(mock: { mock: { invocationCallOrder: number[] } }): number {
    return mock.mock.invocationCallOrder[0];
  }

  it("openProjectAt resets the workspace, clears the domain stores, then loads", async () => {
    expect(await projectSession.openProjectAt("/w/book-two")).toBe(true);

    expect(onOpenWorkspace).toHaveBeenCalledTimes(1);
    expect(fanOut.clearProjectData).toHaveBeenCalledTimes(1);
    expect(fanOut.loadProjectData).toHaveBeenCalledTimes(1);
    // App's pane/layout reset first, then the domain clear, then the load.
    expect(order(onOpenWorkspace)).toBeLessThan(order(fanOut.clearProjectData));
    expect(order(fanOut.clearProjectData)).toBeLessThan(order(fanOut.loadProjectData));
  });

  it("createProjectAt clears before it loads too", async () => {
    await projectSession.createProjectAt("/w/book-two", "Book Two", []);

    expect(fanOut.clearProjectData).toHaveBeenCalledTimes(1);
    expect(fanOut.loadProjectData).toHaveBeenCalledTimes(1);
    expect(order(onOpenWorkspace)).toBeLessThan(order(fanOut.clearProjectData));
    expect(order(fanOut.clearProjectData)).toBeLessThan(order(fanOut.loadProjectData));
  });
});
