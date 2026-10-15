// @vitest-environment happy-dom
// Quote links (#2498): the chat subject's scene text follows the open scene's
// live draft, so a quote edited away stops linking.
import { beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({
  panes: [] as { id: string; document: { type: string; id: string }; draftMarkdown: string }[],
}));
vi.mock("@/lib/stores/editorPanes.svelte", () => ({ editorPanes: fake }));
vi.mock("@/lib/utils/treeHelpers", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  findNodeBySceneId: (_root: unknown, id: string) => (id === "scene_1" ? { id } : null),
}));

import { QuoteSourceController } from "./quoteSource.svelte";
import type { StructureDocument } from "@/lib/types";

const structure = { root: {} } as unknown as StructureDocument;

beforeEach(() => {
  fake.panes = [{ id: "editor_1", document: { type: "manuscript", id: "scene_1" }, draftMarkdown: "The lantern was still burning." }];
});

describe("QuoteSourceController", () => {
  it("reads the open scene's live draft, and a later edit replaces it", async () => {
    const qs = new QuoteSourceController();
    await qs.refresh("scene_1", structure);
    expect(qs.sceneId).toBe("scene_1");
    expect(qs.plain).toContain("The lantern was still burning.");
    expect(qs.liveDraft("scene_1")).toBe("The lantern was still burning.");

    fake.panes[0].draftMarkdown = "The lantern had gone out.";
    vi.useFakeTimers();
    try {
      qs.schedule("scene_1", structure, 50);
      await vi.advanceTimersByTimeAsync(60);
    } finally {
      vi.useRealTimers();
    }
    await vi.waitFor(() => expect(qs.plain).toContain("The lantern had gone out."));
    expect(qs.plain).not.toContain("still burning");
  });

  it("a subject that isn't a scene has no source", async () => {
    const qs = new QuoteSourceController();
    await qs.refresh("lore_1", structure);
    expect(qs.sceneId).toBeNull();
    expect(qs.plain).toBeNull();
  });
});
