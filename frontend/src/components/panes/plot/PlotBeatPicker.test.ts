// @vitest-environment happy-dom
// PlotBeatPicker RENDER guard (ADR-0048 S7 Slice 5b). The card→beat link editor
// DISPLAYS the book's arcs + their beats with the linked ones checked, and reports
// a toggle. Mount-tested here ([[reference_component_test_harness]]); no xyflow import.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PlotBeatPicker from "./PlotBeatPicker.svelte";
import type { TemplateInstanceSummary } from "@/lib/types";

const arc = (id: string, title: string, beats: { id: string; title: string }[]): TemplateInstanceSummary => ({
  id,
  title,
  body: "",
  entry_type: "plot:template_instance",
  metadata: { instance_beats: beats },
});

function renderPicker(arcs: TemplateInstanceSummary[], linked: string[] = []) {
  const onToggle = vi.fn();
  render(PlotBeatPicker, { props: { arcs, linked: new Set(linked), onToggle } });
  return { onToggle };
}

describe("PlotBeatPicker", () => {
  it("shows an empty hint when there are no arcs", () => {
    renderPicker([]);
    expect(screen.getByText(/No arcs yet/i)).toBeInTheDocument();
  });

  it("lists each arc with its beats", () => {
    renderPicker([arc("i1", "Hero's Journey", [{ id: "b1", title: "Call to Adventure" }, { id: "b2", title: "Refusal" }])]);
    expect(screen.getByText("Hero's Journey")).toBeInTheDocument();
    expect(screen.getByText("Call to Adventure")).toBeInTheDocument();
    expect(screen.getByText("Refusal")).toBeInTheDocument();
  });

  it("checks a beat that is already linked", () => {
    renderPicker([arc("i1", "Arc", [{ id: "b1", title: "One" }, { id: "b2", title: "Two" }])], ["i1:b2"]);
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    // Order follows the beats: b1 unchecked, b2 checked.
    expect(boxes[0].checked).toBe(false);
    expect(boxes[1].checked).toBe(true);
  });

  it("reports a toggle with the instance + beat ids and the new checked state", async () => {
    const { onToggle } = renderPicker([arc("i9", "Arc", [{ id: "beat_x", title: "X" }])]);
    await fireEvent.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalledWith("i9", "beat_x", true);
  });

  it("shows a per-arc note when an arc has no beats", () => {
    renderPicker([arc("i1", "Bare arc", [])]);
    expect(screen.getByText(/No beats yet/i)).toBeInTheDocument();
  });
});
