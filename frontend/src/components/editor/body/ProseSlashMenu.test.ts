// @vitest-environment happy-dom
// ProseSlashMenu (#2454): one-line rows, the highlighted command's
// description in a footer, and no mousedown anywhere on the menu may take
// focus from the editor (the host's keymap drives the menu).
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import ProseSlashMenu from "./ProseSlashMenu.svelte";
import type { SlashCommand, SlashMenuState } from "@/lib/editor-core/slashMenu";

const COMMANDS: SlashCommand[] = [
  { group: "Insert", label: "Table", description: "Pick a size.", run: () => {} },
  { group: "AI", label: "Continue", description: "Write the next beat.", run: () => {} },
];

function menu(selectedIndex: number): SlashMenuState {
  return { visible: true, x: 0, y: 0, selectedIndex, mode: "commands", gridRows: 1, gridCols: 1 };
}

function mount(selectedIndex: number, onRunCommand = vi.fn()) {
  return render(ProseSlashMenu, {
    props: {
      menu: menu(selectedIndex),
      filterText: "",
      commands: COMMANDS,
      onRunCommand,
      onInsertTable: vi.fn(),
      onHoverCommand: vi.fn(),
      onHoverGrid: vi.fn(),
    },
  });
}

describe("ProseSlashMenu", () => {
  it("renders one-line rows and shows only the highlighted description", () => {
    const { container } = mount(1);
    const rows = [...container.querySelectorAll<HTMLButtonElement>(".slash-list button")];
    expect(rows.map((row) => row.textContent?.trim())).toEqual(["Table", "Continue"]);
    expect(container.querySelector(".slash-hint")?.textContent).toBe("Write the next beat.");
    expect(screen.queryByText("Pick a size.")).toBeNull();
  });

  it("never lets a mousedown on the menu move focus", () => {
    const onRunCommand = vi.fn();
    const { container } = mount(0, onRunCommand);
    for (const target of [
      container.querySelector(".slash-menu")!,
      container.querySelector(".slash-group")!,
      container.querySelector(".slash-hint")!,
    ]) {
      const event = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
      target.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
    }
    const row = container.querySelector<HTMLButtonElement>('[data-index="1"]')!;
    const event = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    row.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(onRunCommand).toHaveBeenCalledWith(COMMANDS[1]);
  });
});
