// @vitest-environment happy-dom
// Moving a field definition to another layer (#2442). SchemaPanes owns the
// authoring state; after `doMoveSchemaField` the still-open inline editor must
// follow the field to its new home layer — it labels "currently on <layer>" and
// the next save writes to that layer. SchemaPanes registers its panes with the
// panel registry instead of rendering them, so the test renders the registered
// regions through RegionBody, as the workspace shell does.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import SchemaPanes from "./SchemaPanes.svelte";
import RegionBody from "@/components/workspace/RegionBody.svelte";
import { clearSchema, setSchemaOverview } from "@/lib/stores/schema";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import type { MetadataSchema, MetadataSchemaOverview } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: {
    moveMetadataField: vi.fn(),
    getMetadataSchemaOverview: vi.fn(),
    validateProject: vi.fn(),
    upsertMetadataField: vi.fn(),
  },
}));
import { api } from "@/lib/api";

const SERIES = "series";
const PROJECT = "proj";

const effectiveSchema = {
  version: 1,
  entry_types: {
    "manuscript:scene": { name: "Scene", kind: "manuscript", fields: ["truth"], own_fields: ["truth"] },
  },
  fields: { truth: { name: "Truth", type: "text", options: [] } },
  groups: {},
} as unknown as MetadataSchema;

function overviewWithTruthOn(layerId: string): MetadataSchemaOverview {
  return {
    effective_schema: effectiveSchema,
    layers: [
      { id: SERIES, label: "Series", folder_path: "/series", schema_path: "/series/metadata.schema.yaml", exists: true },
      { id: PROJECT, label: "Project", folder_path: "/proj", schema_path: "/proj/metadata.schema.yaml", exists: true },
    ],
    entry_type_sources: { "manuscript:scene": { layer_id: "builtin", layer_label: "Built-in", built_in: true } },
    field_sources: {
      truth: { layer_id: layerId, layer_label: layerId === SERIES ? "Series" : "Project", built_in: false },
    },
  } as unknown as MetadataSchemaOverview;
}

describe("SchemaPanes move field to another layer (#2442)", () => {
  beforeEach(() => {
    setSchemaOverview(overviewWithTruthOn(PROJECT));
    vi.mocked(api.moveMetadataField).mockResolvedValue(effectiveSchema);
    // The refresh after the move reports the field's new home layer.
    vi.mocked(api.getMetadataSchemaOverview).mockResolvedValue(overviewWithTruthOn(SERIES));
    vi.mocked(api.validateProject).mockResolvedValue({ errors: [], warnings: [] } as never);
    vi.mocked(api.upsertMetadataField).mockResolvedValue(effectiveSchema);
  });
  afterEach(() => {
    clearSchema();
    vi.clearAllMocks();
  });

  function mountPanes() {
    render(SchemaPanes, {
      props: {
        isProjectOpen: true,
        run: async (fn: () => Promise<void>) => {
          await fn();
          return true;
        },
        setStatus: vi.fn(),
        refreshOpenEditorPaneBaselines: vi.fn(async () => {}),
      },
    });
    render(RegionBody, { props: { id: "schema" } });
    render(RegionBody, { props: { id: "schema_type" } });
  }

  it("re-points the open editor (label, picker, and next save) at the new layer", async () => {
    mountPanes();

    // Open the field the way a user does: click it in the Types tree.
    const fieldRow = await screen.findByLabelText(/^Field truth/);
    await fireEvent.click(fieldRow.querySelector("button") ?? fieldRow);
    await vi.waitFor(() => expect(document.querySelector(".sfi-move-hint strong")?.textContent).toBe("Project"));
    const picker = screen.getByLabelText("Move to layer") as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.value)).toEqual(["", SERIES]);

    // Move up to the ancestor layer (no confirm: only a downward move warns).
    await fireEvent.change(picker, { target: { value: SERIES } });
    await fireEvent.click(screen.getByRole("button", { name: "Move" }));

    await vi.waitFor(() => expect(api.moveMetadataField).toHaveBeenCalledWith("truth", SERIES, "manuscript:scene"));
    // The editor follows the field: it now says Series, and offers Project to move back to.
    await vi.waitFor(() => expect(document.querySelector(".sfi-move-hint strong")?.textContent).toBe("Series"));
    const pickerAfter = screen.getByLabelText("Move to layer") as HTMLSelectElement;
    expect(Array.from(pickerAfter.options).map((o) => o.value)).toEqual(["", PROJECT]);

    // ...and the next save writes to the new layer, not the old one.
    await fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await vi.waitFor(() => expect(api.upsertMetadataField).toHaveBeenCalled());
    expect(vi.mocked(api.upsertMetadataField).mock.calls[0][0]).toBe(SERIES);
  });

  it("follows a downward move once the warning is confirmed", async () => {
    setSchemaOverview(overviewWithTruthOn(SERIES));
    vi.mocked(api.getMetadataSchemaOverview).mockResolvedValue(overviewWithTruthOn(PROJECT));
    mountPanes();

    const fieldRow = await screen.findByLabelText(/^Field truth/);
    await fireEvent.click(fieldRow.querySelector("button") ?? fieldRow);
    await vi.waitFor(() => expect(document.querySelector(".sfi-move-hint strong")?.textContent).toBe("Series"));

    const picker = screen.getByLabelText("Move to layer") as HTMLSelectElement;
    await fireEvent.change(picker, { target: { value: PROJECT } });
    await fireEvent.click(screen.getByRole("button", { name: "Move" }));
    // A move to a nearer layer warns first and does nothing until confirmed.
    expect(confirmService.active?.title).toBe("Move field to a nearer layer?");
    expect(api.moveMetadataField).not.toHaveBeenCalled();
    await confirmService.resolve();

    await vi.waitFor(() => expect(document.querySelector(".sfi-move-hint strong")?.textContent).toBe("Project"));
    await fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await vi.waitFor(() => expect(api.upsertMetadataField).toHaveBeenCalled());
    expect(vi.mocked(api.upsertMetadataField).mock.calls[0][0]).toBe(PROJECT);
  });
});
