// newPlotTemplate (#918) — the "+ New template" action on the Plot Templates pane.
// The non-fork twin of forkPlotTemplate: blank-create an owned template via the API,
// refresh the roster, then open the fresh node in an editor to name it + author beats.
// What these tests pin: it creates, then opens the CREATED id, and only after the
// create resolves (so the open never races an absent node).
import { beforeEach, describe, expect, it, vi } from "vitest";

import { treeActions } from "./treeActions.svelte";
import { api } from "@/lib/api";
import { editorPanes } from "./editorPanes.svelte";
import type { PlotTemplate } from "@/lib/types";

const CREATED: PlotTemplate = {
  id: "plot_new",
  title: "New template",
  body: "",
  revision: "r0",
  entry_type: "plot:template",
  template: { slug: "", display_name: "New template" },
  metadata: {},
  computed_metadata: {},
  source_layer_id: "layer_project",
  source_layer_label: "",
  is_library: false,
  editable: true,
};

describe("treeActions.newPlotTemplate (#918)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Mirror App's run() without its store side effects.
    treeActions.run = async (action) => {
      try {
        await action();
        return true;
      } catch {
        return false;
      }
    };
    vi.spyOn(api, "createPlotTemplate").mockResolvedValue(CREATED);
    // refreshPlotTemplates() runs inside newPlotTemplate; keep it off the network.
    vi.spyOn(api, "listPlotTemplates").mockResolvedValue({ entries: [] });
  });

  it("blank-creates a template and opens the fresh node", async () => {
    const open = vi.spyOn(editorPanes, "openPlotTemplate").mockResolvedValue(undefined);

    await treeActions.newPlotTemplate();

    expect(api.createPlotTemplate).toHaveBeenCalled();
    expect(open).toHaveBeenCalledWith(CREATED.id);
    // The node must exist before we try to open it.
    expect(
      (api.createPlotTemplate as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0],
    ).toBeLessThan((open as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0]);
  });
});
