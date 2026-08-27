// @vitest-environment happy-dom
// SwatchPicker's inherited-placeholder behaviour (#1440). When a color field is
// unset the rail passes the RESOLVED inherited colour as `placeholderHex`, and
// the trigger must show that colour (dashed, "not set") instead of the old empty
// hatched dot — otherwise the inherited colour is invisible.
import { describe, expect, it } from "vitest";
import { render } from "@/lib/test/component";
import SwatchPicker from "./SwatchPicker.svelte";

describe("SwatchPicker inherited placeholder (#1440)", () => {
  it("shows the inherited colour as a dashed dot when value is unset", () => {
    const { container } = render(SwatchPicker, {
      props: { value: null, placeholderHex: "#5b5ca8" },
    });
    const dot = container.querySelector(".swatch-dot-inherited") as HTMLElement | null;
    expect(dot).not.toBeNull();
    // The actual colour is visible (inline background), not the empty hatch.
    expect(dot!.style.background.toLowerCase().replace(/\s/g, "")).toContain("#5b5ca8");
    expect(container.querySelector(".swatch-dot-empty")).toBeNull();
    // Labelled as inherited (and that clicking sets an override).
    expect(container.querySelector(".swatch-trigger")!.getAttribute("aria-label")).toMatch(/inherited/i);
  });

  it("falls back to the empty hatched dot when there is no inherited colour", () => {
    const { container } = render(SwatchPicker, {
      props: { value: null, placeholderHex: null },
    });
    expect(container.querySelector(".swatch-dot-empty")).not.toBeNull();
    expect(container.querySelector(".swatch-dot-inherited")).toBeNull();
    expect(container.querySelector(".swatch-trigger")!.getAttribute("aria-label")).toBe("Pick a color");
  });
});
