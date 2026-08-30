// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import AiPolicySlider from "./AiPolicySlider.svelte";

describe("AiPolicySlider inherit note (#1672)", () => {
  it("names the inherited value and its source", () => {
    const { container } = render(AiPolicySlider, {
      props: {
        value: "inherit" as const,
        canInherit: true,
        inherited: { policy: "cloud-allowed" as const, source: "Series" },
        onChange: vi.fn(),
      },
    });
    const note = container.querySelector(".inherit-note");
    expect(note?.textContent).toContain("Inheriting");
    expect(note?.textContent).toContain("Cloud"); // humanized from cloud-allowed
    expect(note?.textContent).toContain("Series"); // the provenance
  });

  it("says 'app default' when no ancestor states a policy (source null)", () => {
    const { container } = render(AiPolicySlider, {
      props: {
        value: "inherit" as const,
        canInherit: true,
        inherited: { policy: "off" as const, source: null },
        onChange: vi.fn(),
      },
    });
    const note = container.querySelector(".inherit-note");
    expect(note?.textContent).toContain("Off");
    expect(note?.textContent).toContain("app default");
  });

  it("falls back to the generic relationship copy when the value isn't resolved", () => {
    const { container } = render(AiPolicySlider, {
      props: { value: "inherit" as const, canInherit: true, inherited: null, onChange: vi.fn() },
    });
    expect(container.querySelector(".inherit-note")?.textContent).toContain(
      "from the projects above",
    );
  });

  it("shows Reset (not the inherit note) once a concrete stop is chosen", () => {
    const { container } = render(AiPolicySlider, {
      props: {
        value: "cloud-allowed" as const,
        canInherit: true,
        inherited: { policy: "off" as const, source: "Universe" },
        onChange: vi.fn(),
      },
    });
    expect(container.querySelector(".inherit-note")).toBeNull();
    expect(screen.getByRole("button", { name: /Reset to inherited/ })).toBeTruthy();
  });

  it("routes a stop click through onChange", async () => {
    const onChange = vi.fn();
    render(AiPolicySlider, {
      props: { value: "inherit" as const, canInherit: true, inherited: null, onChange },
    });
    await fireEvent.click(screen.getByRole("radio", { name: "Cloud" }));
    expect(onChange).toHaveBeenCalledWith("cloud-allowed");
  });
});
