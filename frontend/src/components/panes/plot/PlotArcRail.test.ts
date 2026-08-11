// @vitest-environment happy-dom
// PlotArcRail RENDER guard (ADR-0048 S7 Slice 5a). The arc palette DISPLAYS the
// book's arcs + their beats, so it needs a mount test that asserts the content
// renders and the actions fire ([[reference_component_test_harness]]). Written with
// NO @xyflow/svelte import (it's a plain sidebar), so it mounts here on its own.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PlotArcRail from "./PlotArcRail.svelte";
import type { TemplateInstanceSummary, PlotTemplateSummary } from "@/lib/types";

const arc = (over: Partial<TemplateInstanceSummary> & { id: string; title: string }): TemplateInstanceSummary => ({
  body: "",
  entry_type: "plot:template_instance",
  metadata: {},
  ...over,
});

const template = (id: string, title: string): PlotTemplateSummary =>
  ({ id, title, body: "", entry_type: "plot:template", metadata: {} }) as unknown as PlotTemplateSummary;

function renderRail(
  over: { instances?: TemplateInstanceSummary[]; templates?: PlotTemplateSummary[]; usedBeatKeys?: Set<string> } = {},
) {
  const props = {
    instances: [] as TemplateInstanceSummary[],
    templates: [] as PlotTemplateSummary[],
    usedBeatKeys: new Set<string>(),
    onOpen: vi.fn(),
    onInstantiate: vi.fn(),
    onCreateBlank: vi.fn(),
    onRemove: vi.fn(),
    ...over,
  };
  render(PlotArcRail, { props });
  return props;
}

describe("PlotArcRail", () => {
  it("shows an empty-state hint when there are no arcs", () => {
    renderRail();
    expect(screen.getByText(/No arcs yet/i)).toBeInTheDocument();
  });

  it("lists arcs with their beat counts", () => {
    renderRail({
      instances: [
        arc({ id: "i1", title: "Hero's Journey", metadata: { instance_beats: [{ title: "Ordinary World" }, { title: "Call" }] } }),
        arc({ id: "i2", title: "Ad-hoc arc" }),
      ],
    });
    expect(screen.getByRole("button", { name: "Hero's Journey" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ad-hoc arc" })).toBeInTheDocument();
    // The beat count chip for the two-beat arc.
    expect(screen.getByTitle("2 beats")).toBeInTheDocument();
  });

  it("expands an arc to reveal its beat titles", async () => {
    renderRail({
      instances: [arc({ id: "i1", title: "Arc", metadata: { instance_beats: [{ title: "Inciting incident" }] } })],
    });
    expect(screen.queryByText("Inciting incident")).toBeNull();
    await fireEvent.click(screen.getByLabelText("Expand beats"));
    expect(screen.getByText("Inciting incident")).toBeInTheDocument();
  });

  it("makes an id-bearing beat draggable and checks a used beat (#824 palette)", async () => {
    renderRail({
      instances: [
        arc({ id: "i1", title: "Arc", metadata: { instance_beats: [{ id: "b1", title: "One" }, { id: "b2", title: "Two" }] } }),
      ],
      usedBeatKeys: new Set(["i1:b1"]),
    });
    await fireEvent.click(screen.getByLabelText("Expand beats"));
    const one = screen.getByText("One").closest("li") as HTMLElement;
    expect(one.getAttribute("draggable")).toBe("true");
    // "One" is already on a card → the linked check shows; "Two" is not.
    expect(screen.getByTitle("Linked to a card")).toBeInTheDocument();
  });

  it("opens an arc via its id", async () => {
    const props = renderRail({ instances: [arc({ id: "i9", title: "Open me" })] });
    await fireEvent.click(screen.getByRole("button", { name: "Open me" }));
    expect(props.onOpen).toHaveBeenCalledWith("i9");
  });

  it("removes an arc via its id", async () => {
    const props = renderRail({ instances: [arc({ id: "i7", title: "Bye" })] });
    await fireEvent.click(screen.getByLabelText("Remove this arc"));
    expect(props.onRemove).toHaveBeenCalledWith("i7");
  });

  it("adds a blank arc from the add menu", async () => {
    const props = renderRail();
    await fireEvent.click(screen.getByLabelText("Add an arc"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Blank arc" }));
    expect(props.onCreateBlank).toHaveBeenCalledTimes(1);
  });

  it("instantiates from a template listed in the add menu", async () => {
    const props = renderRail({ templates: [template("t1", "Tragedy")] });
    await fireEvent.click(screen.getByLabelText("Add an arc"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Tragedy" }));
    expect(props.onInstantiate).toHaveBeenCalledWith("t1");
  });
});
