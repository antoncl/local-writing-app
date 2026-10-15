// Quote links (#2498): where a quote's passage is shown. The real layout store
// is used (the moves are what's under test); editorPanes is a minimal fake.
import { beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => ({
  panes: [] as { id: string; document: { type: string; id: string } }[],
  openScene: vi.fn(),
  revealSearchMatchInOpenPane: vi.fn(),
  editorPaneComponents: {} as Record<string, unknown>,
}));
vi.mock("@/lib/stores/editorPanes.svelte", () => ({ editorPanes: fake }));

import { workspaceLayout } from "./workspaceLayout.svelte";
import { G_EDITOR } from "./workspaceLayout.serialize";
import { revealQuoteBeside } from "./quoteReveal";

const QUOTE = "the lantern was still burning";
const scenePane = { id: "pane-scene", document: { type: "manuscript", id: "scene_1" } };

function seat(group: ReturnType<typeof workspaceLayout.allGroups>[number], ...ids: string[]) {
  group.tabs.push(...ids);
  group.active = ids[ids.length - 1];
}

beforeEach(() => {
  workspaceLayout.reset();
  fake.panes = [];
  fake.openScene.mockReset();
  fake.revealSearchMatchInOpenPane.mockReset();
  fake.editorPaneComponents = {};
});

describe("revealQuoteBeside", () => {
  it("only reveals when the scene's pane is already the visible tab", async () => {
    const g = workspaceLayout.groupById(G_EDITOR)!;
    seat(g, "pane-chat", "pane-scene");
    fake.panes = [scenePane];
    await revealQuoteBeside({ sceneId: "scene_1", quote: QUOTE, besidePanelId: "pane-chat" });
    expect(fake.openScene).not.toHaveBeenCalled();
    expect(fake.revealSearchMatchInOpenPane).toHaveBeenCalledWith("scene_1", {
      query: QUOTE, matchCase: true, wholeWord: false, excerpt: "", ordinal: 0,
    });
    expect(workspaceLayout.groupOf("pane-scene")!.id).toBe(g.id);
  });

  it("opens a closed scene, moves it beside the chat's group, then reveals", async () => {
    const g = workspaceLayout.groupById(G_EDITOR)!;
    seat(g, "pane-chat");
    fake.openScene.mockImplementation(async () => {
      fake.panes = [scenePane];
      seat(g, "pane-scene"); // the App effect homes it in the chat's group
    });
    const order: string[] = [];
    fake.revealSearchMatchInOpenPane.mockImplementation(() => order.push("reveal"));
    await revealQuoteBeside({ sceneId: "scene_1", quote: QUOTE, besidePanelId: "pane-chat" });
    expect(fake.openScene).toHaveBeenCalledWith("scene_1");
    const chatGroup = workspaceLayout.groupOf("pane-chat")!;
    const sceneGroup = workspaceLayout.groupOf("pane-scene")!;
    expect(sceneGroup.id).not.toBe(chatGroup.id);
    const ids = workspaceLayout.allGroups().map((x) => x.id);
    expect(ids.indexOf(sceneGroup.id)).toBe(ids.indexOf(chatGroup.id) + 1); // to its right
    expect(order).toEqual(["reveal"]);
  });

  it("after the move, reveals into the remounted editor, not the one the move destroyed", async () => {
    const g = workspaceLayout.groupById(G_EDITOR)!;
    seat(g, "pane-chat");
    const oldHandle = { name: "old" };
    const newHandle = { name: "new" };
    fake.openScene.mockImplementation(async () => {
      fake.panes = [scenePane];
      seat(g, "pane-scene");
      fake.editorPaneComponents["pane-scene"] = oldHandle;
    });
    // The move remounts the pane: its handle is replaced a little later.
    const moved = vi.spyOn(workspaceLayout, "dropOnEdge").mockImplementation(function (this: unknown, ...args) {
      moved.mockRestore();
      workspaceLayout.dropOnEdge(...(args as Parameters<typeof workspaceLayout.dropOnEdge>));
      setTimeout(() => (fake.editorPaneComponents["pane-scene"] = newHandle), 40);
    });
    let handleAtReveal: unknown = null;
    fake.revealSearchMatchInOpenPane.mockImplementation(() => {
      handleAtReveal = fake.editorPaneComponents["pane-scene"];
    });
    await revealQuoteBeside({ sceneId: "scene_1", quote: QUOTE, besidePanelId: "pane-chat" });
    expect(handleAtReveal).toBe(newHandle);
  });

  it("moves the scene into an existing second editor group rather than splitting a third", async () => {
    const main = workspaceLayout.groupById(G_EDITOR)!;
    seat(main, "editor_1", "editor_2"); // two editor tabs in the main group
    workspaceLayout.dropOnEdge("editor_2", main.id, "right"); // editor_2 now has its own group
    const chatGroup = workspaceLayout.groupOf("editor_2")!;
    const groupsBefore = workspaceLayout.allGroups().length;
    const scene = { id: "editor_3", document: { type: "manuscript", id: "scene_1" } };
    fake.openScene.mockImplementation(async () => {
      fake.panes = [scene];
      seat(chatGroup, "editor_3"); // homed into the chat's (active) group
    });
    await revealQuoteBeside({ sceneId: "scene_1", quote: QUOTE, besidePanelId: "editor_2" });
    expect(workspaceLayout.groupOf("editor_3")!.id).toBe(main.id);
    expect(workspaceLayout.allGroups().length).toBe(groupsBefore);
  });

  it("activates a scene tab that is hidden in another group instead of moving it", async () => {
    const [a] = workspaceLayout.allGroups();
    seat(a, "pane-chat");
    workspaceLayout.dropOnEdge("pane-chat", a.id, "right"); // chat now alone beside a
    const other = workspaceLayout.allGroups().find((g) => !g.tabs.includes("pane-chat"))!;
    seat(other, "pane-scene", "pane-other"); // scene is a background tab
    other.active = "pane-other";
    fake.panes = [scenePane];
    await revealQuoteBeside({ sceneId: "scene_1", quote: QUOTE, besidePanelId: "pane-chat" });
    expect(workspaceLayout.groupOf("pane-scene")!.id).toBe(other.id);
    expect(other.active).toBe("pane-scene");
    expect(fake.revealSearchMatchInOpenPane).toHaveBeenCalledTimes(1);
  });
});
