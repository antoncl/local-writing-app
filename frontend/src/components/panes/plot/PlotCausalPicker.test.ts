// @vitest-environment happy-dom
// PlotCausalPicker RENDER guard (ADR-0048 S7 Slice 6b). The card→card "Leads to…"
// editor DISPLAYS the board's OTHER cards with the linked ones checked, excludes the
// card itself, and reports a toggle. Mount-tested here ([[reference_component_test_harness]]);
// no xyflow import.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PlotCausalPicker from "./PlotCausalPicker.svelte";
import type { PlotCardChoice } from "./plotCardActions";

const cards: PlotCardChoice[] = [
  { id: "a", title: "She leaves home" },
  { id: "b", title: "The storm hits" },
  { id: "c", title: "They reconcile" },
];

function renderPicker(
  over: { cards?: PlotCardChoice[]; selfId?: string; linked?: string[]; filter?: string } = {},
) {
  const onToggle = vi.fn();
  render(PlotCausalPicker, {
    props: {
      cards: over.cards ?? cards,
      selfId: over.selfId,
      linked: new Set(over.linked ?? []),
      onToggle,
      filter: over.filter ?? "",
    },
  });
  return { onToggle };
}

describe("PlotCausalPicker", () => {
  it("lists the candidate cards by title", () => {
    renderPicker();
    expect(screen.getByText("She leaves home")).toBeInTheDocument();
    expect(screen.getByText("The storm hits")).toBeInTheDocument();
    expect(screen.getByText("They reconcile")).toBeInTheDocument();
  });

  it("excludes the card itself (no self-link)", () => {
    renderPicker({ selfId: "a" });
    expect(screen.queryByText("She leaves home")).not.toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });

  it("checks a target that is already linked", () => {
    renderPicker({ selfId: "a", linked: ["c"] });
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    // Order follows the (self-excluded) list: b unchecked, c checked.
    expect(boxes[0].checked).toBe(false);
    expect(boxes[1].checked).toBe(true);
  });

  it("reports a toggle with the target id and the new checked state", async () => {
    const { onToggle } = renderPicker({ selfId: "a" });
    await fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(onToggle).toHaveBeenCalledWith("b", true);
  });

  it("shows an empty hint when there is no other card to link to", () => {
    renderPicker({ cards: [{ id: "solo", title: "Alone" }], selfId: "solo" });
    expect(screen.getByText(/No other cards yet/i)).toBeInTheDocument();
  });

  it("narrows the list to cards whose title matches the filter (case-insensitive)", () => {
    renderPicker({ filter: "storm" });
    expect(screen.getByText("The storm hits")).toBeInTheDocument();
    expect(screen.queryByText("She leaves home")).not.toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });

  it("distinguishes a no-match filter from an empty board", () => {
    renderPicker({ filter: "zzz" });
    expect(screen.getByText(/No cards match your filter/i)).toBeInTheDocument();
  });
});
