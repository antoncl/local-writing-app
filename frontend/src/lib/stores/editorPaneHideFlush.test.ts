// @vitest-environment happy-dom
// Flush-on-close (#369). Closing the tab used to silently discard up to the
// whole autosave-idle window of typing — nothing flushed a dirty pane on the
// way out. These cover the two halves of the fix: the keepalive hint that lets
// an in-flight save survive the page tearing down, and the wrapper App binds to
// `pagehide` / `visibilitychange: hidden` that flushes every dirty pane.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setKeepaliveSaves } from "@/lib/api";
import { flushDirtyPanesOnHide } from "./editorPaneSave";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import type { Scene } from "@/lib/types";

const SCENE: Scene = {
  id: "scene_1",
  title: "Chapter One",
  body: "on disk",
  revision: "r1",
  entry_type: "manuscript:scene",
  status: "draft",
  metadata: {},
  computed_metadata: {},
} as Scene;

// A minimal ok Response whose json() yields a saved scene; enough for `request`.
function okScene() {
  return {
    ok: true,
    json: async () => ({ ...SCENE, body: "edited body", revision: "r2" }),
  };
}

describe("keepalive save hint (#369)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okScene()));
  });
  afterEach(() => {
    setKeepaliveSaves(false);
    vi.unstubAllGlobals();
  });

  it("marks a save request keepalive while active, so an in-flight PUT survives unload", async () => {
    setKeepaliveSaves(true);
    await api.saveScene(SCENE, "edited body");
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.keepalive).toBe(true);
  });

  it("does not mark save requests keepalive by default", async () => {
    await api.saveScene(SCENE, "edited body");
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.keepalive).toBeFalsy();
  });
});

function seedDirtyScenePane(): void {
  editorPanes.panes = [
    {
      ...createEmptyEditorPane("pane_1"),
      document: { type: "manuscript" as const, id: SCENE.id },
      scene: SCENE,
      draftTitle: SCENE.title,
      draftMarkdown: "edited body",
      draftStatus: SCENE.status,
      draftEntryType: SCENE.entry_type,
      dirty: true,
    },
  ];
}

function stubSceneRefreshes(): void {
  // The refreshes a scene save fans out to (#performSave + refreshAfterSave).
  vi.spyOn(api, "getStructure").mockResolvedValue({ nodes: [] } as never);
  vi.spyOn(api, "getTodos").mockResolvedValue({ items: [] } as never);
  vi.spyOn(api, "getEmbeddedTodos").mockResolvedValue({ items: [] } as never);
  vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} } as never);
}

describe("flushDirtyPanesOnHide — through the real controller (#369)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
  });
  afterEach(() => {
    setKeepaliveSaves(false);
    editorPanes.dispose();
    editorPanes.reset();
  });

  it("persists a dirty pane's edits on the way out", async () => {
    seedDirtyScenePane();
    stubSceneRefreshes();
    const save = vi
      .spyOn(api, "saveScene")
      .mockResolvedValue({ ...SCENE, body: "edited body", revision: "r2" });

    await flushDirtyPanesOnHide(editorPanes);

    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0][1]).toBe("edited body");
    expect(editorPanes.panes.find((p) => p.id === "pane_1")?.dirty).toBe(false);
  });

  it("keepalive-marks the pagehide flush but leaves the visibility flush normal", async () => {
    // The split that matters (#369): keepalive (with its ~64KB cap) only for the
    // terminal pagehide; a normal, uncapped save on visibilitychange while the
    // page is still alive. A store whose flush issues one real save lets us read
    // back the keepalive bit the flag set for it.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okScene()));
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    const seen: Array<boolean | undefined> = [];
    const store = {
      flushDirtyPanes: vi.fn(async () => {
        await api.saveScene(SCENE, "b");
        seen.push(fetchMock.mock.calls.at(-1)![1].keepalive);
        return true;
      }),
    };

    await flushDirtyPanesOnHide(store, { keepalive: true }); // pagehide
    await flushDirtyPanesOnHide(store); // visibilitychange

    expect(seen).toEqual([true, false]);
    vi.unstubAllGlobals();
  });

  it("swallows a failed flush and always clears the keepalive flag", async () => {
    // A pagehide flush whose save rejects (e.g. the tab died mid-save). The
    // wrapper must not turn that into an unhandled rejection, and its `finally`
    // must leave the flag off so a later normal request is not silently keepalive.
    const store = { flushDirtyPanes: vi.fn().mockRejectedValue(new Error("gone")) };
    await expect(flushDirtyPanesOnHide(store, { keepalive: true })).resolves.toBeUndefined();

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okScene()));
    await api.saveScene(SCENE, "b");
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.keepalive).toBeFalsy();
    vi.unstubAllGlobals();
  });
});
