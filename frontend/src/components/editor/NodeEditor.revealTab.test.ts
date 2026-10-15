// @vitest-environment happy-dom
// #2500: a reveal into a scene's prose (a quote link, a search hit, …) first
// shows the Body tab — under another body tab the prose is mounted but hidden,
// so the highlight would land out of sight.
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { api } from "@/lib/api";
import { metadataSchemaStore } from "@/lib/stores/schema";
import NodeEditor from "./NodeEditor.svelte";

const SCENE = {
  id: "scene_1",
  kind: "manuscript",
  title: "Opening",
  body: "The cat sat on the mat.",
  status: "draft",
  entry_type: "manuscript:scene",
  metadata: {},
} as never;

// One collection field on the scene type earns it a second body tab.
const SCHEMA = {
  fields: { characters: { id: "characters", label: "Characters", type: "entity_ref_list" } },
  entry_types: { "manuscript:scene": { fields: ["characters"] } },
} as never;

beforeEach(() => {
  vi.spyOn(api, "aiListInvocations").mockResolvedValue({ invocations: [] } as never);
  vi.spyOn(api, "getSceneEffectiveNames").mockResolvedValue({});
  vi.spyOn(api, "listSnapshots").mockResolvedValue({ snapshots: [] } as never);
  metadataSchemaStore.set(SCHEMA);
});

afterEach(() => {
  metadataSchemaStore.set(null as never);
});

// The scene's effective-names fetch is debounced past the test body: keep the
// API mocks until the whole file is done (the network guard, #973).
afterAll(() => {
  vi.restoreAllMocks();
});

describe("NodeEditor - a reveal shows the Body tab (#2500)", () => {
  it("switches from another body tab to Body, then reveals", async () => {
    const utils = render(NodeEditor, { props: { scene: SCENE, documentKind: "manuscript" } as never });
    await vi.waitFor(() => expect(utils.container.querySelector(".ProseMirror")?.textContent).toContain("The cat sat"));
    const tab = (name: RegExp) => screen.getByRole("tab", { name });

    await fireEvent.click(tab(/characters/i));
    expect(tab(/characters/i).getAttribute("aria-selected")).toBe("true");

    (utils.component as unknown as { revealSearchMatch: (r: unknown) => void }).revealSearchMatch({
      query: "sat on the mat", matchCase: true, wholeWord: false, excerpt: "", ordinal: 0,
    });
    await vi.waitFor(() => expect(tab(/^Body/).getAttribute("aria-selected")).toBe("true"));
    await vi.waitFor(() =>
      expect(utils.container.querySelector(".search-match-current")?.textContent).toBe("sat on the mat"),
    );
  });
});
