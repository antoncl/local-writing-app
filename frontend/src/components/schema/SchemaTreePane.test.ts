// @vitest-environment happy-dom
// Detail Types kind-tabs RENDER guard (#729). Making plot a first-class kind in
// the schema-authoring UI means the "Plot" tab actually has to appear in the tab
// strip and route through `onSwitchKind("plot")`. The strip renders from the
// shared SCHEMA_KINDS/SCHEMA_KIND_META table, so this drives its expectations
// off the SAME table — a kind added to the table without a rendered tab (or a
// relabelled tab) fails here. The cascade the tab feeds (entry-type → kind →
// heading in SchemaPanes) is pinned by the asSchemaKind/SCHEMA_KIND_META unit
// tests in schemaTypeHelpers.test.ts; together they cover the whole path that
// shipped broken (the Plot tab silently collapsing to the Scene tree).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { SCHEMA_KINDS, SCHEMA_KIND_META } from "@/lib/utils/schemaTypeHelpers";
import SchemaTreePane from "./SchemaTreePane.svelte";

describe("SchemaTreePane kind tabs (#729)", () => {
  it("renders one tab per schema kind — including Plot — labelled from the shared table", () => {
    render(SchemaTreePane, { props: {} });
    expect(screen.getByRole("tablist", { name: "Type kind" })).toBeInTheDocument();
    // Every kind in the table has a rendered tab; Plot is present, not just typed.
    expect(SCHEMA_KINDS).toContain("plot");
    for (const kind of SCHEMA_KINDS) {
      expect(screen.getByRole("tab", { name: SCHEMA_KIND_META[kind].label })).toBeInTheDocument();
    }
  });

  it("marks the Plot tab selected when the pane is scoped to plot, and switches to it on click", async () => {
    const onSwitchKind = vi.fn();
    const { rerender } = render(SchemaTreePane, { props: { schemaFieldKind: "scene", onSwitchKind } });

    await fireEvent.click(screen.getByRole("tab", { name: "Plot" }));
    expect(onSwitchKind).toHaveBeenCalledWith("plot");

    await rerender({ schemaFieldKind: "plot", onSwitchKind });
    expect(screen.getByRole("tab", { name: "Plot" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Scene" })).toHaveAttribute("aria-selected", "false");
  });
});
