// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync } from "svelte";
import { api } from "@/lib/api";
import { createSceneEffectiveMatcher } from "./sceneEffectiveMatcher.svelte";
import type { LoreEntrySummary } from "@/lib/types";

// #2352: typing into a scene's summary fired GET /effective-names on every
// keystroke — the accessor read `scene?.id`, subscribing to the whole scene
// object, which a metadata edit replaces (same id) on each keystroke. The fetch
// must follow the VALUES it needs, not the object identity around them.
describe("createSceneEffectiveMatcher (#2352)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("fetches on a scene switch, never when the scene object is replaced with the same id", async () => {
    const fetches = vi.spyOn(api, "getSceneEffectiveNames").mockResolvedValue({});
    let scene = $state<{ id: string; metadata: Record<string, string> }>({ id: "scene_1", metadata: {} });
    const entries: LoreEntrySummary[] = [];

    const stop = $effect.root(() => {
      createSceneEffectiveMatcher({
        sceneId: () => scene?.id ?? null,
        entries: () => entries,
        schema: () => null,
      });
    });
    flushSync();
    expect(fetches).toHaveBeenCalledTimes(1);

    // Ten "keystrokes" in the summary: a new scene object each time, same id.
    for (const ch of "hello worl") {
      scene = { id: "scene_1", metadata: { summary: (scene.metadata.summary ?? "") + ch } };
      flushSync();
    }
    expect(fetches).toHaveBeenCalledTimes(1);

    // A real scene switch still refetches.
    scene = { id: "scene_2", metadata: {} };
    flushSync();
    expect(fetches).toHaveBeenCalledTimes(2);
    expect(fetches).toHaveBeenLastCalledWith("scene_2");
    stop();
  });
});
