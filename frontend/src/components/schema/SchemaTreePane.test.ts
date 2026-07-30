// @vitest-environment happy-dom
// Detail Types kind-tabs RENDER guard (#729). Making plot a first-class kind in
// the schema-authoring UI means the "Plot" tab actually has to appear in the tab
// strip and route through `onSwitchKind("plot")` — a SchemaKind-array edit whose
// only user-visible proof is the rendered tab. A type-only check ("plot" is in
// SchemaKind) can't see a tab that never renders; mounting the pane can.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import SchemaTreePane from "./SchemaTreePane.svelte";

describe("SchemaTreePane kind tabs (#729)", () => {
  it("renders a Plot tab alongside the other schema kinds", () => {
    render(SchemaTreePane, { props: {} });
    const tablist = screen.getByRole("tablist", { name: "Type kind" });
    for (const label of ["Scene", "Lore", "Research", "Prompt", "Assistant", "Project", "Plot"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    expect(tablist).toBeInTheDocument();
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
