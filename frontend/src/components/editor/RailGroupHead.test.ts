// @vitest-environment happy-dom
// #1884 slice 3 — the one L1 group header, shared by the rail (foldable) and
// the type editor (non-foldable).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import RailGroupHead from "./RailGroupHead.svelte";

describe("RailGroupHead (#1884 slice 3)", () => {
  it("renders the label", () => {
    render(RailGroupHead, { props: { label: "Arc" } });
    expect(screen.getByText("Arc")).toBeTruthy();
  });

  it("with onToggle: renders a button with aria-expanded matching expanded, click calls onToggle", async () => {
    const onToggle = vi.fn();
    render(RailGroupHead, { props: { label: "Arc", expanded: true, onToggle } });
    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-expanded", "true");
    await fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("without onToggle: no button, just a plain label", () => {
    render(RailGroupHead, { props: { label: "General" } });
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("General")).toBeTruthy();
  });
});
