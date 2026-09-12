// @vitest-environment happy-dom
// ColoredSelect's popover goes through the shared `anchoredPopover` action
// instead of an inline rect-anchoring copy (#1587) — body-portaled, fixed,
// and floor-widthed to the trigger pill.
import { describe, expect, it } from "vitest";
import { render, fireEvent, screen } from "@/lib/test/component";
import ColoredSelect from "./ColoredSelect.svelte";

describe("ColoredSelect popover (#1587)", () => {
  it("is body-portaled, fixed-positioned, and lists every row", async () => {
    const { container } = render(ColoredSelect, {
      props: {
        value: "a",
        options: [
          { value: "a", label: "A" },
          { value: "b", label: "B" },
        ],
      },
    });
    await fireEvent.click(container.querySelector(".colored-select-trigger") as HTMLElement);

    const pop = document.querySelector(".colored-select-popover");
    expect(pop).not.toBeNull();
    expect(pop!.parentElement).toBe(document.body);
    expect((pop as HTMLElement).style.position).toBe("fixed");

    const rows = pop!.querySelectorAll('[role="option"]');
    expect(rows).toHaveLength(3); // blank row (default allowBlank) + A + B

    await fireEvent.click(screen.getByText("B"));
    expect(document.querySelector(".colored-select-popover")).toBeNull();
  });

  it("a derived option shows at rest but is never offered (#1906)", async () => {
    const { container } = render(ColoredSelect, {
      props: {
        value: "on_page",
        allowBlank: false,
        options: [
          { value: "unwritten", label: "Unwritten" },
          { value: "off_page", label: "Off the page" },
          { value: "on_page", label: "On the page", derived: true },
        ],
      },
    });
    // The trigger names the held (derived) value…
    expect(container.querySelector(".colored-select-trigger")?.textContent).toContain("On the page");
    await fireEvent.click(container.querySelector(".colored-select-trigger") as HTMLElement);
    // …and the list offers only the author's two.
    const rows = [...document.querySelectorAll('[role="option"]')].map((r) => r.textContent?.trim());
    expect(rows).toEqual(["Unwritten", "Off the page"]);
  });
});
