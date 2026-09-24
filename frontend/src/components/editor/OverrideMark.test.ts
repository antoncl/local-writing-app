// @vitest-environment happy-dom
// OverrideMark (#2184 slice 3): the interactive `ti-versions` mark extracted
// from RailFieldRow — pins the chip text/aria/tooltip, that it fires onReset,
// and that it is a real tab stop (a <button>, not hover-only).
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import OverrideMark from "./OverrideMark.svelte";

describe("OverrideMark", () => {
  it("renders the chip text and aria-label, and the tooltip as its title", () => {
    render(OverrideMark, {
      chipText: "Reset to Aetheria",
      tooltip: "Overridden here — Aetheria's title is “Marek Vell”.",
      ariaLabel: "Reset the title to Aetheria's",
      onReset: () => {},
    });
    const mark = screen.getByRole("button", { name: "Reset the title to Aetheria's" });
    expect(mark.getAttribute("title")).toBe("Overridden here — Aetheria's title is “Marek Vell”.");
    expect(mark.textContent).toContain("Reset to Aetheria");
  });

  it("calls onReset on click", async () => {
    const onReset = vi.fn();
    render(OverrideMark, { chipText: "Reset to Aetheria", tooltip: "x", ariaLabel: "Reset the title", onReset });
    await fireEvent.click(screen.getByRole("button", { name: "Reset the title" }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("is a real tab stop (a <button>)", () => {
    render(OverrideMark, { chipText: "Reset to Aetheria", tooltip: "x", ariaLabel: "Reset the title", onReset: () => {} });
    const mark = screen.getByRole("button", { name: "Reset the title" });
    expect(mark.tagName).toBe("BUTTON");
  });

  it("applies a data-testid when given", () => {
    render(OverrideMark, {
      chipText: "Reset to Aetheria",
      tooltip: "x",
      ariaLabel: "Reset the title",
      onReset: () => {},
      testid: "title-override-mark",
    });
    expect(screen.getByTestId("title-override-mark")).toBeInTheDocument();
  });
});
