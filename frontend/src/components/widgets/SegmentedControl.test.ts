// @vitest-environment happy-dom
import { describe, it, expect } from "vitest";
import { render, screen } from "@/lib/test/component";

import SegmentedControl from "@/components/widgets/SegmentedControl.svelte";

// The revision review (#1620) tints Current warm and Proposed cool with the same
// tokens the diff markup uses; Both stays neutral. The tint is driven by a
// per-item `tone` surfaced as `data-tone`, so pin that it reaches the DOM — a
// silent drop (tone removed from the items, or data-tone from the button) would
// otherwise take the visual cue with it and no test would notice.
const VIEWS = [
  { id: "now", label: "Current", tone: "warm" },
  { id: "was", label: "Proposed", tone: "cool" },
  { id: "both", label: "Both" },
] as const;

describe("SegmentedControl — per-item tone (#1620)", () => {
  it("tags the warm/cool segments with data-tone and leaves an untoned one bare", () => {
    render(SegmentedControl, {
      props: { items: VIEWS, value: "now", ariaLabel: "Which version", onSelect: () => {} },
    });
    expect(screen.getByRole("button", { name: "Current" })).toHaveAttribute("data-tone", "warm");
    expect(screen.getByRole("button", { name: "Proposed" })).toHaveAttribute("data-tone", "cool");
    expect(screen.getByRole("button", { name: "Both" })).not.toHaveAttribute("data-tone");
  });
});
