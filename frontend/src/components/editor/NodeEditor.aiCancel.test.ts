// @vitest-environment happy-dom
// #2464: Esc in the prose editor cancels a running generation - and only then.
// Mounts the real NodeEditor > ProseBodyView chain and drives the controller.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@/lib/test/component";
import { api } from "@/lib/api";
import NodeEditor from "./NodeEditor.svelte";
import type { AiSuggestionController } from "@/lib/editor-core/aiSuggestion.svelte";

const controllers = vi.hoisted(() => [] as unknown[]);

vi.mock("@/lib/editor-core/aiSuggestion.svelte", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/editor-core/aiSuggestion.svelte")>();
  class Spied extends mod.AiSuggestionController {
    constructor(deps: ConstructorParameters<typeof mod.AiSuggestionController>[0]) {
      super(deps);
      controllers.push(this);
    }
  }
  return { ...mod, AiSuggestionController: Spied };
});

const SCENE = {
  id: "scene_1",
  kind: "manuscript",
  title: "Opening",
  body: "The cat sat on the mat.",
  status: "draft",
  entry_type: "",
  metadata: {},
} as never;

const controller = () => controllers[controllers.length - 1] as AiSuggestionController;

beforeEach(() => {
  vi.spyOn(api, "aiListInvocations").mockResolvedValue({ invocations: [] } as never);
  vi.spyOn(api, "getSceneEffectiveNames").mockResolvedValue({});
  vi.spyOn(api, "listSnapshots").mockResolvedValue({ snapshots: [] } as never);
});

afterEach(() => {
  controllers.length = 0;
  vi.restoreAllMocks();
});

async function mountEditor() {
  const utils = render(NodeEditor, { props: { scene: SCENE, documentKind: "manuscript" } as never });
  await vi.waitFor(() => expect(utils.container.querySelector(".ProseMirror")?.textContent).toContain("The cat sat"));
  return utils.container.querySelector(".ProseMirror") as HTMLElement;
}

describe("Esc cancels a running generation (#2464)", () => {
  it("cancels while generating", async () => {
    const pm = await mountEditor();
    const cancel = vi.spyOn(controller(), "cancelGeneration");
    controller().generating = true;
    await fireEvent.keyDown(pm, { key: "Escape" });
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("does nothing when not generating", async () => {
    const pm = await mountEditor();
    const cancel = vi.spyOn(controller(), "cancelGeneration");
    await fireEvent.keyDown(pm, { key: "Escape" });
    expect(cancel).not.toHaveBeenCalled();
  });
});
