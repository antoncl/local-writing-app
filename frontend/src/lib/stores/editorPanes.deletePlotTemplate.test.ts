// S4c finding #3 — the editor-pane Delete button is shown for every pane, and
// #deleteScene dispatches by documentKind. A plot_template must route to its own
// deleter (DELETE /plot/templates/{id}); the pre-fix code fell through to the
// `else` and called api.deleteScene, which 404s on a `plot` node (the exact
// hazard the `view` branch guards against). This pins the correct routing.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { api } from "@/lib/api";
import type { PlotTemplate } from "@/lib/types";

const TEMPLATE: PlotTemplate = {
  id: "plot_owned_clone",
  title: "My Three-Act",
  body: "# guide",
  revision: "r1",
  entry_type: "plot:template",
  template: { slug: "my-three-act", display_name: "My Three-Act" },
  metadata: {},
  computed_metadata: {},
  is_library: false,
  editable: true,
};

describe("editorPanes delete routing for plot templates (S4c #3)", () => {
  beforeEach(() => {
    editorPanes.reset();
    vi.restoreAllMocks();
    editorPanes.panes = [
      {
        ...createEmptyEditorPane("pane_1"),
        document: { type: "plot_template" as const, id: TEMPLATE.id },
        scene: TEMPLATE,
        draftEntryType: TEMPLATE.entry_type,
      },
    ];
    // Keep the confirm off the UI and background refreshes off the network.
    vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });
  });

  afterEach(() => editorPanes.reset());

  it("routes delete to api.deletePlotTemplate, never api.deleteScene", async () => {
    vi.spyOn(api, "deletePlotTemplate").mockResolvedValue({ entries: [] });
    const deleteScene = vi.spyOn(api, "deleteScene");

    // The confirm dialog fires onConfirm → #deleteScene; capture its promise so
    // the assertion waits for the async delete to complete.
    let deletion: Promise<void> | undefined;
    vi.spyOn(confirmService, "request").mockImplementation((req: { onConfirm: () => Promise<void> }) => {
      deletion = req.onConfirm();
    });

    await editorPanes.requestDeleteScene("pane_1");
    await deletion;

    expect(api.deletePlotTemplate).toHaveBeenCalledWith(TEMPLATE.id);
    expect(deleteScene).not.toHaveBeenCalled();
  });
});
