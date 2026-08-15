// #750 — the project node loads scene-shaped (project.md round-trips through the
// editor pane, same as the save path), so the editor Delete button was active on
// the project window and requestDeleteScene would fall through to
// api.deleteScene, wiping project.md with mislabeled "Delete Prompt" copy. This
// pins the guard: a project pane schedules no confirm and deletes nothing, while
// a plain scene pane still reaches the confirm — so a blanket "always return"
// mutation can't pass this file.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { api } from "@/lib/api";

// The guard only reads `pane.document?.type` and the `pane.scene` truthiness, so
// a minimal scene-shaped stub is enough for both panes.
const sceneStub = (id: string, title: string) =>
  ({ id, title, body: "" }) as never;

describe("editorPanes delete guard for the project node (#750)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
    // Keep background reference lookups off the network for the scene control.
    vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });
  });

  afterEach(() => editorPanes.reset());

  it("refuses the project node — no confirm scheduled, nothing deleted", async () => {
    editorPanes.panes = [
      {
        ...createEmptyEditorPane("pane_project"),
        document: { type: "project" as const, id: "project_root" },
        scene: sceneStub("project_root", "My Project"),
      },
    ];
    const confirm = vi.spyOn(confirmService, "request");
    const deleteScene = vi.spyOn(api, "deleteScene");

    await editorPanes.requestDeleteScene("pane_project");

    expect(confirm).not.toHaveBeenCalled();
    expect(deleteScene).not.toHaveBeenCalled();
  });

  it("still reaches the confirm for a plain scene pane (positive control)", async () => {
    editorPanes.panes = [
      {
        ...createEmptyEditorPane("pane_scene"),
        document: { type: "manuscript" as const, id: "scene_1" },
        scene: sceneStub("scene_1", "Chapter One"),
      },
    ];
    const confirm = vi
      .spyOn(confirmService, "request")
      .mockImplementation(() => {}); // swallow — we only assert it was reached

    await editorPanes.requestDeleteScene("pane_scene");

    expect(confirm).toHaveBeenCalledTimes(1);
  });
});
