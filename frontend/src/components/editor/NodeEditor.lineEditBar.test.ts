// @vitest-environment happy-dom
// #2460: the Line edit review bar is a footer row of the editor PANE (NodeEditor),
// outside the prose scroll frame - so it never covers text. The controller lives
// in ProseBodyView and is bound up through EditorBodyHost; this mounts the real
// chain and drives the controller's `lineEdits` state directly.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
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

// Mount, then wait for the scene to load into the editor: loading a document
// resets the suggestion controller, which would wipe state set before it lands.
async function mountEditor() {
  const utils = render(NodeEditor, { props: { scene: SCENE, documentKind: "manuscript" } as never });
  await vi.waitFor(() => expect(utils.container.querySelector(".ProseMirror")?.textContent).toContain("The cat sat"));
  return utils;
}

const controller = () => controllers[controllers.length - 1] as AiSuggestionController;

// The mount fetches cost / names / snapshots; the network guard (#973) forbids the real thing.
beforeEach(() => {
  vi.spyOn(api, "aiListInvocations").mockResolvedValue({ invocations: [] } as never);
  vi.spyOn(api, "getSceneEffectiveNames").mockResolvedValue({});
  vi.spyOn(api, "listSnapshots").mockResolvedValue({ snapshots: [] } as never);
});

afterEach(() => {
  controllers.length = 0;
  vi.restoreAllMocks();
});

describe("NodeEditor - Line edit review bar placement", () => {
  it("shows the bar only while line edits are pending, as a pane footer outside the scroll frame", async () => {
    await mountEditor();
    expect(screen.queryByTestId("line-edit-review-bar")).toBeNull();

    controller().lineEdits = { remaining: 2, index: 1, currentReason: "livelier" };
    const bar = await screen.findByTestId("line-edit-review-bar");
    expect(screen.getByTestId("line-edit-count").textContent).toBe("Edit 1 of 2");

    // Not inside the prose scroll frame, but inside the editor panel.
    expect(bar.closest(".editor-wrap")).toBeNull();
    expect(bar.closest(".editor-panel")).not.toBeNull();

    controller().lineEdits = null;
    await vi.waitFor(() => expect(screen.queryByTestId("line-edit-review-bar")).toBeNull());
  });

  it("the bar's batch controls act on the prose body's controller", async () => {
    await mountEditor();
    const acceptAll = vi.spyOn(controller(), "acceptAllLineEdits").mockImplementation(() => {});
    const rejectAll = vi.spyOn(controller(), "rejectAllLineEdits").mockImplementation(() => {});
    controller().lineEdits = { remaining: 1, index: 1, currentReason: "r" };
    await fireEvent.click(await screen.findByTestId("line-edit-accept-all"));
    await fireEvent.click(screen.getByTestId("line-edit-reject-all"));
    expect(acceptAll).toHaveBeenCalledTimes(1);
    expect(rejectAll).toHaveBeenCalledTimes(1);
    // the per-edit controls moved to the margin card
    expect(screen.queryByTestId("line-edit-accept")).toBeNull();
  });
});
