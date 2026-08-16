// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ToggleSwitch from "@/components/widgets/ToggleSwitch.svelte";

describe("ToggleSwitch", () => {
  it("renders a switch reflecting `checked`", () => {
    render(ToggleSwitch, { props: { checked: true, ariaLabel: "Enable", onChange: vi.fn() } });
    const sw = screen.getByRole("switch", { name: "Enable" });
    expect(sw.getAttribute("aria-checked")).toBe("true");
  });

  it("calls onChange with the negated value on click", async () => {
    const onChange = vi.fn();
    render(ToggleSwitch, { props: { checked: false, ariaLabel: "Enable", onChange } });
    await fireEvent.click(screen.getByRole("switch", { name: "Enable" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith(true);
  });

  it("does not fire onChange while disabled", async () => {
    const onChange = vi.fn();
    render(ToggleSwitch, { props: { checked: false, ariaLabel: "Enable", disabled: true, onChange } });
    await fireEvent.click(screen.getByRole("switch", { name: "Enable" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("marks the tri-state `unset` mode and toggles on from it (#522/#1073)", async () => {
    const onChange = vi.fn();
    // Unset is the rail's "not set": neither on nor off, knob parked centre.
    render(ToggleSwitch, { props: { checked: false, unset: true, ariaLabel: "Flag (not set)", onChange } });
    const sw = screen.getByRole("switch", { name: "Flag (not set)" });
    expect(sw.classList.contains("unset")).toBe(true);
    expect(sw.getAttribute("aria-checked")).toBe("false");
    // Clicking an unset toggle turns it on (getting back to unset is the row's
    // revert affordance, not this control).
    await fireEvent.click(sw);
    expect(onChange).toHaveBeenCalledExactlyOnceWith(true);
  });
});
