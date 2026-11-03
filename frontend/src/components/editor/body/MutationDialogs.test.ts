// @vitest-environment happy-dom
// #73: `/mutate close` resolves its picker at the cursor, so the dialog host
// must flush the scene first (the offset is current-text, the index is saved)
// and hand the position through to the picker's live read.
import { afterEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render } from "@/lib/test/component";
import MutationDialogs from "./MutationDialogs.svelte";
import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import type { LoreEntrySummary } from "@/lib/types";

describe("MutationDialogs openClose", () => {
  afterEach(() => vi.restoreAllMocks());

  it("flushes the scene, then reads the live set at the given position", async () => {
    const order: string[] = [];
    vi.spyOn(editorPanes, "flushSceneIfDirty").mockImplementation(async () => {
      order.push("flush");
    });
    const live = vi.spyOn(api, "getLiveEntityMutations").mockImplementation(async () => {
      order.push("read");
      return { items: [] };
    });
    const { component } = render(MutationDialogs, {
      props: {
        getEditor: () => null,
        sceneId: "scene1",
        isScene: true,
        loreEntries: [{ id: "mira", title: "Mira", entry_type: "lore:character", metadata: {} } as unknown as LoreEntrySummary],
        schema: null,
      },
    });
    await (component as unknown as { openClose: (p: string, pos?: number) => Promise<void> }).openClose("mira", 42);
    await tick();
    await tick();
    expect(live).toHaveBeenCalledWith("mira", "scene1", 42);
    expect(order).toEqual(["flush", "read"]);
  });
});
