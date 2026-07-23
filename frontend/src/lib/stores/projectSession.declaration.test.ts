import { beforeEach, describe, expect, it, vi } from "vitest";

// Mock the HTTP client and the store fan-out so we control exactly when the
// PATCH and the reload settle — these tests are about the ordering and the
// in-flight guard, not the network. Same shape as references.test.ts.
const { updateProjectSettings } = vi.hoisted(() => ({ updateProjectSettings: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { updateProjectSettings } }));

const { loadProjectData } = vi.hoisted(() => ({ loadProjectData: vi.fn() }));
vi.mock("@/lib/stores/index", () => ({ loadProjectData }));

import { projectSession } from "@/lib/stores/projectSession.svelte";
import type { ProjectInfo } from "@/lib/types";

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

// Drains the macrotask queue, so anything still pending afterwards is pending
// for a real reason rather than because we sampled a microtask too early.
const flush = () => new Promise((r) => setTimeout(r, 0));

const PROJECT = { title: "On Basilisk Station", root_path: "/w/obs" } as ProjectInfo;

describe("setDeclaration (#426)", () => {
  let updated: ProjectInfo[];
  let statuses: string[];

  beforeEach(() => {
    updateProjectSettings.mockReset();
    loadProjectData.mockReset();
    loadProjectData.mockResolvedValue(undefined);
    updated = [];
    statuses = [];
    projectSession.declarationSaving = false;
    // The host hooks App injects. `run` is App's error sink; the real one
    // swallows the throw and returns false, which is what the failure test
    // depends on.
    projectSession.run = async (action) => {
      try {
        await action();
        return true;
      } catch {
        return false;
      }
    };
    projectSession.setStatus = (message) => statuses.push(message);
    projectSession.onProjectUpdated = (project) => updated.push(project);
    projectSession.onProjectDataLoaded = () => {};
  });

  it("sends the declaration, folds the fresh project in, and reloads the stores", async () => {
    // The reload is the half that is easy to drop: the declaration decides
    // which projects the merged schema, node index, tag registry and lore
    // roster are assembled from, so the response alone leaves them stale.
    updateProjectSettings.mockResolvedValue(PROJECT);

    await projectSession.setDeclaration(["/w/honorverse"]);

    expect(updateProjectSettings).toHaveBeenCalledWith({ inherits: ["/w/honorverse"] });
    expect(updated).toEqual([PROJECT]);
    expect(loadProjectData).toHaveBeenCalledTimes(1);
  });

  it("refuses a second save while one is in flight", async () => {
    // The double-click race. Each request is derived from the enumeration on
    // screen, so a second one issued mid-flight computes from the enumeration
    // the first is about to replace — and silently undoes it. Without the
    // guard this test sees two PATCHes, the second of which drops layer one.
    const inflight = deferred<ProjectInfo>();
    updateProjectSettings.mockReturnValueOnce(inflight.promise);

    const first = projectSession.setDeclaration(["/w/honorverse"]);
    const second = await projectSession.setDeclaration(["/w/honor-harrington"]);

    expect(second).toBe(false);
    expect(updateProjectSettings).toHaveBeenCalledTimes(1);

    inflight.resolve(PROJECT);
    await first;
  });

  it("clears the in-flight flag once the save settles", async () => {
    updateProjectSettings.mockResolvedValue(PROJECT);

    await projectSession.setDeclaration([]);

    expect(projectSession.declarationSaving).toBe(false);
  });

  it("clears the in-flight flag when the save is rejected", async () => {
    // A 422 (a declared folder that is not an ancestor project) must not leave
    // the checkboxes disabled forever — that would strand the pane after the
    // one failure the author is most likely to hit.
    updateProjectSettings.mockRejectedValue(new Error("422"));

    const ok = await projectSession.setDeclaration(["/w/elsewhere"]);

    expect(ok).toBe(false);
    expect(projectSession.declarationSaving).toBe(false);
    // Nothing was folded in and no reload ran, so the pane still renders the
    // declaration that is actually on disk.
    expect(updated).toEqual([]);
    expect(loadProjectData).not.toHaveBeenCalled();
  });

  it("keeps refusing saves while the RELOAD is still running", async () => {
    // The reload is the slow half — it re-pulls every project-scoped store.
    // Releasing the guard when the PATCH resolves would reopen the race for
    // that whole span, which is most of the wall clock.
    //
    // Asserted as behaviour (a second save is still refused) rather than by
    // reading the flag after N microtasks: the flag version of this test
    // PASSED against a mutant that dropped the `await` on the reload, because
    // it just happened to sample the flag a tick too early. `flush` drains the
    // macrotask queue, so the only thing that can still be holding the guard
    // is the genuinely-pending reload.
    const patch = deferred<ProjectInfo>();
    const reload = deferred<void>();
    updateProjectSettings.mockReturnValueOnce(patch.promise);
    loadProjectData.mockReturnValueOnce(reload.promise);

    const save = projectSession.setDeclaration(["/w/honorverse"]);
    patch.resolve(PROJECT);
    await flush();

    expect(loadProjectData).toHaveBeenCalledTimes(1);
    expect(await projectSession.setDeclaration(["/w/honor-harrington"])).toBe(false);
    expect(updateProjectSettings).toHaveBeenCalledTimes(1);

    reload.resolve();
    await save;
    expect(projectSession.declarationSaving).toBe(false);
  });

  it("says the declaration is empty rather than counting zero levels", async () => {
    updateProjectSettings.mockResolvedValue(PROJECT);

    await projectSession.setDeclaration([]);

    expect(statuses).toEqual(["Inherits from nothing"]);
  });

  it("counts one level in the singular", async () => {
    updateProjectSettings.mockResolvedValue(PROJECT);

    await projectSession.setDeclaration(["/w/honorverse"]);

    expect(statuses).toEqual(["Inherits from 1 level"]);
  });
});
