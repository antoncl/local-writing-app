import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the HTTP client and the store fan-out: these tests are about when the
// lists are re-pulled and the in-flight guard, not the network. Same shape as
// projectSession.declaration.test.ts.
const { refreshProjectFromDisk } = vi.hoisted(() => ({ refreshProjectFromDisk: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { refreshProjectFromDisk } }));

const { loadProjectData } = vi.hoisted(() => ({ loadProjectData: vi.fn() }));
vi.mock("@/lib/stores/index", () => ({ loadProjectData }));

const { closeRemovedNodes } = vi.hoisted(() => ({ closeRemovedNodes: vi.fn() }));
vi.mock("@/lib/stores/editorPanes.svelte", () => ({ editorPanes: { closeRemovedNodes } }));

import { projectSession } from "@/lib/stores/projectSession.svelte";

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("refreshFromDisk (#2170)", () => {
  let dataLoaded: number;

  beforeEach(() => {
    refreshProjectFromDisk.mockReset();
    loadProjectData.mockReset();
    loadProjectData.mockResolvedValue(undefined);
    closeRemovedNodes.mockReset();
    dataLoaded = 0;
    projectSession.run = async (action) => {
      try {
        await action();
        return true;
      } catch {
        return false;
      }
    };
    projectSession.onProjectDataLoaded = () => {
      dataLoaded += 1;
    };
  });

  it("re-pulls the lists when the backend reports an outside change", async () => {
    refreshProjectFromDisk.mockResolvedValue({ changed: true, removed: [] });

    await projectSession.refreshFromDisk();

    expect(loadProjectData).toHaveBeenCalledTimes(1);
    expect(dataLoaded).toBe(1);
  });

  it("closes the panes of nodes deleted outside the app", async () => {
    refreshProjectFromDisk.mockResolvedValue({ changed: true, removed: ["lore_gone"] });

    await projectSession.refreshFromDisk();

    expect(closeRemovedNodes).toHaveBeenCalledWith(["lore_gone"]);
    expect(loadProjectData).toHaveBeenCalledTimes(1);
  });

  it("leaves the lists alone when nothing moved", async () => {
    // Every window focus lands here; re-pulling fourteen lists each time would
    // be the cost this answer exists to avoid.
    refreshProjectFromDisk.mockResolvedValue({ changed: false, removed: [] });

    await projectSession.refreshFromDisk();

    expect(loadProjectData).not.toHaveBeenCalled();
  });

  it("collapses the focus + visibilitychange pair into one request", async () => {
    const inflight = deferred<{ changed: boolean; removed: string[] }>();
    refreshProjectFromDisk.mockReturnValueOnce(inflight.promise);

    const first = projectSession.refreshFromDisk();
    await projectSession.refreshFromDisk();
    expect(refreshProjectFromDisk).toHaveBeenCalledTimes(1);

    inflight.resolve({ changed: false, removed: [] });
    await first;
  });

  it("accepts the next return once a failed refresh settles", async () => {
    refreshProjectFromDisk.mockRejectedValueOnce(new Error("offline"));
    await projectSession.refreshFromDisk();

    refreshProjectFromDisk.mockResolvedValueOnce({ changed: true, removed: [] });
    await projectSession.refreshFromDisk();

    expect(refreshProjectFromDisk).toHaveBeenCalledTimes(2);
    expect(loadProjectData).toHaveBeenCalledTimes(1);
  });
});
