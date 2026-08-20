import { describe, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/core";
import { buildTableMenuAction } from "./tableMenuActions";
import {
  isToolbarSeparator,
  isToolbarSubmenu,
  type ToolbarMenuEntry,
} from "./selectionToolbar";

// A chainable editor stub: every table command returns the chain and records
// its name, so we can assert which TipTap command a menu leaf fires.
function makeEditor() {
  const calls: string[] = [];
  const chain: Record<string, unknown> = {};
  const methods = [
    "focus",
    "addRowBefore",
    "addRowAfter",
    "deleteRow",
    "addColumnBefore",
    "addColumnAfter",
    "deleteColumn",
    "toggleHeaderRow",
    "toggleHeaderColumn",
    "deleteTable",
  ];
  for (const m of methods) chain[m] = () => (calls.push(m), chain);
  chain.run = () => (calls.push("run"), true);
  return { editor: { chain: () => chain } as unknown as Editor, calls };
}

// Find a runnable leaf anywhere in the (one-level) submenu tree by id.
function findLeaf(entries: ToolbarMenuEntry[], id: string): { run: () => void; danger?: boolean } {
  for (const e of entries) {
    if (isToolbarSeparator(e)) continue;
    if (isToolbarSubmenu(e)) {
      for (const child of e.items) {
        if (!isToolbarSeparator(child) && !isToolbarSubmenu(child) && child.id === id) return child;
      }
      continue;
    }
    if (e.id === id) return e;
  }
  throw new Error(`no leaf ${id}`);
}

describe("buildTableMenuAction (#1223)", () => {
  it("groups the table commands into Row / Column / Align / Header submenus + a delete leaf", () => {
    const { editor } = makeEditor();
    const action = buildTableMenuAction(editor, vi.fn());
    expect(action.kind).toBe("menu");
    expect(action.label).toBe("Table");
    const submenus = action.items.filter(isToolbarSubmenu).map((s) => s.label);
    expect(submenus).toEqual(["Row", "Column", "Align", "Header"]);
    // A separator then a destructive "Delete table" leaf close the menu.
    expect(action.items.some(isToolbarSeparator)).toBe(true);
    expect(findLeaf(action.items, "table-delete").danger).toBe(true);
  });

  it("each leaf fires its TipTap chain command", () => {
    const cases: Array<[string, string]> = [
      ["row-above", "addRowBefore"],
      ["row-below", "addRowAfter"],
      ["row-delete", "deleteRow"],
      ["col-left", "addColumnBefore"],
      ["col-right", "addColumnAfter"],
      ["col-delete", "deleteColumn"],
      ["header-row", "toggleHeaderRow"],
      ["header-column", "toggleHeaderColumn"],
      ["table-delete", "deleteTable"],
    ];
    for (const [id, command] of cases) {
      const { editor, calls } = makeEditor();
      findLeaf(buildTableMenuAction(editor, vi.fn()).items, id).run();
      expect(calls).toContain(command);
      expect(calls).toContain("run");
    }
  });

  it("alignment leaves delegate to the injected onAlign (column-wide, host-owned)", () => {
    const { editor } = makeEditor();
    const onAlign = vi.fn();
    const items = buildTableMenuAction(editor, onAlign).items;
    findLeaf(items, "align-left").run();
    findLeaf(items, "align-center").run();
    findLeaf(items, "align-right").run();
    expect(onAlign.mock.calls).toEqual([["left"], ["center"], ["right"]]);
  });
});
