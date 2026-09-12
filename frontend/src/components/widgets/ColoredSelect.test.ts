// @vitest-environment happy-dom
// ColoredSelect's popover goes through the shared `anchoredPopover` action
// instead of an inline rect-anchoring copy (#1587) — body-portaled, fixed,
// and floor-widthed to the trigger pill.
import { describe, expect, it, vi } from "vitest";
import { createRawSnippet, tick } from "svelte";
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

  it("a value omitted from the pick shows at rest but is not offered (#1906/#1911)", async () => {
    const { container } = render(ColoredSelect, {
      props: {
        value: "on_page",
        allowBlank: false,
        omitFromPick: ["on_page"],
        options: [
          { value: "unwritten", label: "Unwritten" },
          { value: "off_page", label: "Off the page" },
          { value: "on_page", label: "On the page" },
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

describe("ColoredSelect head abilities (#1904)", () => {
  it("renders the icon and the quiet face", () => {
    const { container } = render(ColoredSelect, {
      props: {
        value: "a",
        options: [{ value: "a", label: "A" }],
        icon: "ti ti-user",
        quiet: true,
      },
    });
    const trigger = container.querySelector(".colored-select-trigger") as HTMLElement;
    expect(trigger.classList.contains("quiet")).toBe(true);
    expect(trigger.querySelector(".colored-select-icon.ti-user")).not.toBeNull();

    const { container: defaultContainer } = render(ColoredSelect, {
      props: {
        value: "a",
        options: [{ value: "a", label: "A" }],
      },
    });
    const defaultTrigger = defaultContainer.querySelector(".colored-select-trigger") as HTMLElement;
    expect(defaultTrigger.classList.contains("quiet")).toBe(false);
    expect(defaultTrigger.querySelector(".colored-select-icon")).toBeNull();
  });

  it("renders the footer under the rows and its close() closes the popover", async () => {
    const footer = createRawSnippet<[{ close: () => void }]>((getArgs) => ({
      render: () => `<button type="button" class="t-footer">Edit…</button>`,
      setup(el) {
        el.addEventListener("click", () => getArgs().close());
      },
    }));
    const { container } = render(ColoredSelect, {
      props: {
        value: "a",
        options: [{ value: "a", label: "A" }],
        footer,
      },
    });
    await fireEvent.click(container.querySelector(".colored-select-trigger") as HTMLElement);

    const pop = document.querySelector(".colored-select-popover") as HTMLElement;
    expect(pop).not.toBeNull();
    const footerButton = pop.querySelector(".colored-select-footer .t-footer");
    expect(footerButton).not.toBeNull();
    const options = pop.querySelectorAll('[role="option"]');
    const lastOption = options[options.length - 1];
    // The footer button must come AFTER the last option row in DOM order.
    expect(
      lastOption.compareDocumentPosition(footerButton as Node) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    await fireEvent.click(footerButton as HTMLElement);
    expect(document.querySelector(".colored-select-popover")).toBeNull();
  });

  it("readOnly with a footer still opens; the rows are inert; the footer works", async () => {
    const onChange = vi.fn();
    const footer = createRawSnippet<[{ close: () => void }]>((getArgs) => ({
      render: () => `<button type="button" class="t-footer">Edit…</button>`,
      setup(el) {
        el.addEventListener("click", () => getArgs().close());
      },
    }));
    const { container } = render(ColoredSelect, {
      props: {
        value: "a",
        options: [{ value: "a", label: "A" }, { value: "b", label: "B" }],
        allowBlank: false,
        readOnly: true,
        footer,
        onChange,
      },
    });
    const trigger = container.querySelector(".colored-select-trigger") as HTMLButtonElement;
    expect(trigger.disabled).toBe(false);
    // Openable means it LOOKS openable: caret shown, no inert face.
    expect(trigger.querySelector(".colored-select-caret")).not.toBeNull();
    expect(trigger.classList.contains("read-only")).toBe(false);

    await fireEvent.click(trigger);
    const pop = document.querySelector(".colored-select-popover") as HTMLElement;
    expect(pop).not.toBeNull();

    const options = pop.querySelectorAll('[role="option"]');
    expect(options.length).toBeGreaterThan(0);
    options.forEach((opt) => expect(opt.getAttribute("aria-disabled")).toBe("true"));

    await fireEvent.click(options[0]);
    expect(onChange).not.toHaveBeenCalled();
    expect(document.querySelector(".colored-select-popover")).not.toBeNull();

    await fireEvent.click(pop.querySelector(".t-footer") as HTMLElement);
    expect(document.querySelector(".colored-select-popover")).toBeNull();
  });

  it("the footer is the listbox's sibling, not an option inside it", async () => {
    const footer = createRawSnippet<[{ close: () => void }]>(() => ({
      render: () => `<button type="button" class="t-footer">Edit…</button>`,
    }));
    const { container } = render(ColoredSelect, {
      props: { value: "a", options: [{ value: "a", label: "A" }], footer },
    });
    await fireEvent.click(container.querySelector(".colored-select-trigger") as HTMLElement);
    const listbox = document.querySelector('.colored-select-popover [role="listbox"]') as HTMLElement;
    expect(listbox).not.toBeNull();
    expect(listbox.querySelectorAll('[role="option"]').length).toBe(2); // blank + A
    expect(listbox.querySelector(".t-footer")).toBeNull();
    expect(document.querySelector(".colored-select-popover .t-footer")).not.toBeNull();
  });

  it("keyboard: opening focuses the selected row, arrows walk rows + footer, Escape returns focus to the trigger", async () => {
    const footer = createRawSnippet<[{ close: () => void }]>(() => ({
      render: () => `<button type="button" class="t-footer">Edit…</button>`,
    }));
    const { container } = render(ColoredSelect, {
      props: {
        value: "b",
        options: [{ value: "a", label: "A" }, { value: "b", label: "B" }],
        allowBlank: false,
        footer,
      },
    });
    const trigger = container.querySelector(".colored-select-trigger") as HTMLButtonElement;
    trigger.focus();
    await fireEvent.click(trigger);
    await tick();
    const pop = document.querySelector(".colored-select-popover") as HTMLElement;
    const rows = Array.from(pop.querySelectorAll<HTMLElement>('[role="option"]'));
    const footerButton = pop.querySelector(".t-footer") as HTMLElement;
    expect(document.activeElement).toBe(rows[1]); // the selected row, B

    await fireEvent.keyDown(document.activeElement as HTMLElement, { key: "ArrowDown" });
    expect(document.activeElement).toBe(footerButton);
    await fireEvent.keyDown(document.activeElement as HTMLElement, { key: "ArrowDown" });
    expect(document.activeElement).toBe(rows[0]); // wraps
    await fireEvent.keyDown(document.activeElement as HTMLElement, { key: "ArrowUp" });
    expect(document.activeElement).toBe(footerButton); // wraps back

    await fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector(".colored-select-popover")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("keyboard: readOnly + footer opens with focus on the footer action; Tab out closes", async () => {
    const footer = createRawSnippet<[{ close: () => void }]>(() => ({
      render: () => `<button type="button" class="t-footer">Edit…</button>`,
    }));
    const { container } = render(ColoredSelect, {
      props: { value: "a", options: [{ value: "a", label: "A" }], allowBlank: false, readOnly: true, footer },
    });
    const trigger = container.querySelector(".colored-select-trigger") as HTMLButtonElement;
    await fireEvent.click(trigger);
    await tick();
    const footerButton = document.querySelector(".colored-select-popover .t-footer") as HTMLElement;
    expect(document.activeElement).toBe(footerButton);

    // Focus leaving the popover for somewhere that is neither it nor the trigger.
    await fireEvent.focusOut(footerButton, { relatedTarget: document.body });
    expect(document.querySelector(".colored-select-popover")).toBeNull();
  });

  it("readOnly without a footer stays inert", async () => {
    const { container } = render(ColoredSelect, {
      props: {
        value: "a",
        options: [{ value: "a", label: "A" }],
        readOnly: true,
      },
    });
    const trigger = container.querySelector(".colored-select-trigger") as HTMLButtonElement;
    expect(trigger.disabled).toBe(true);
    expect(trigger.querySelector(".colored-select-caret")).toBeNull();

    await fireEvent.click(trigger);
    expect(document.querySelector(".colored-select-popover")).toBeNull();
  });
});
