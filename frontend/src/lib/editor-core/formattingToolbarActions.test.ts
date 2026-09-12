import { describe, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/core";
import { buildLongTextToolbarActions, formattingToolbarParts } from "./formattingToolbarActions";
import { isToolbarSeparator, isToolbarSubmenu, type ToolbarAction, type ToolbarMenuEntry } from "./selectionToolbar";

// A chainable editor stub: `chain()` returns a Proxy whose every property
// access yields a function returning the proxy itself (so calls compose
// fluently, as TipTap's chain does), except `run`, which records the calls
// made so far and returns true. Arguments passed to a command (e.g.
// `insertTable({...})`) are recorded alongside the method name.
function makeEditor() {
  const calls: string[] = [];
  const callArgs: Record<string, unknown[]> = {};
  const chain: unknown = new Proxy(
    {},
    {
      get(_target, prop: string) {
        if (prop === "run") {
          return () => {
            calls.push("run");
            return true;
          };
        }
        return (...args: unknown[]) => {
          calls.push(prop);
          callArgs[prop] = args;
          return chain;
        };
      },
    },
  );
  const editor = { chain: () => chain } as unknown as Editor;
  return { editor, calls, callArgs };
}

function actionIds(actions: ToolbarAction[]) {
  return actions.map((a) => a.id);
}

function styleItems(actions: ToolbarAction[]): ToolbarMenuEntry[] {
  const style = actions.find((a) => a.id === "style");
  if (!style || style.kind !== "menu") throw new Error("no style menu");
  return style.items;
}

function leafIds(items: ToolbarMenuEntry[]): string[] {
  return items.map((e) => e.id);
}

function runLeaf(items: ToolbarMenuEntry[], id: string) {
  const leaf = items.find((e) => e.id === id);
  if (!leaf || isToolbarSeparator(leaf) || isToolbarSubmenu(leaf)) throw new Error(`no ${id} leaf`);
  void leaf.run();
}

describe("buildLongTextToolbarActions (#1884 slice 1)", () => {
  it("hasText, no table: formatting + Style (with Insert table), no Table menu, no AI/To-do", () => {
    const { editor } = makeEditor();
    const actions = buildLongTextToolbarActions(editor, true, false);
    expect(actionIds(actions)).toEqual(["bold", "italic", "strike", "style"]);
    expect(leafIds(styleItems(actions))).toEqual([
      "paragraph",
      "heading-1",
      "heading-2",
      "heading-3",
      "style-sep",
      "bullet-list",
      "numbered-list",
      "quote",
      "style-sep-2",
      "insert-table",
    ]);
    expect(actions.some((a) => a.id === "table")).toBe(false);
    expect(actions.some((a) => a.id.startsWith("ai-"))).toBe(false);
    expect(actions.some((a) => a.id === "todo")).toBe(false);
  });

  it("hasText + inTable: formatting + Style (no Insert table) + Table menu", () => {
    const { editor } = makeEditor();
    const actions = buildLongTextToolbarActions(editor, true, true);
    expect(actionIds(actions)).toEqual(["bold", "italic", "strike", "style", "table"]);
    expect(leafIds(styleItems(actions))).not.toContain("insert-table");
  });

  it("no selection, inTable: Table menu only", () => {
    const { editor } = makeEditor();
    const actions = buildLongTextToolbarActions(editor, false, true);
    expect(actionIds(actions)).toEqual(["table"]);
  });

  it("no selection, no table: empty", () => {
    const { editor } = makeEditor();
    const actions = buildLongTextToolbarActions(editor, false, false);
    expect(actions).toEqual([]);
  });

  it("running bold calls toggleBold then run", () => {
    const { editor, calls } = makeEditor();
    const actions = buildLongTextToolbarActions(editor, true, false);
    const bold = actions.find((a) => a.id === "bold");
    if (!bold || bold.kind !== "button") throw new Error("no bold button");
    void bold.run();
    expect(calls).toEqual(["focus", "toggleBold", "run"]);
  });

  it("running insert-table calls insertTable with the 3x3 header default", () => {
    const { editor, calls, callArgs } = makeEditor();
    const actions = buildLongTextToolbarActions(editor, true, false);
    runLeaf(styleItems(actions), "insert-table");
    expect(calls).toContain("insertTable");
    expect(calls).toContain("run");
    expect(callArgs.insertTable).toEqual([{ rows: 3, cols: 3, withHeaderRow: true }]);
  });
});

describe("formattingToolbarParts (#1893: the body and the rail share one formatting core)", () => {
  it("returns the parts separately so a host can interleave its own actions", () => {
    const { editor } = makeEditor();
    const parts = formattingToolbarParts(editor, true, true);
    expect(actionIds(parts.marks)).toEqual(["bold", "italic", "strike"]);
    expect(parts.style?.id).toBe("style");
    expect(parts.table?.id).toBe("table");
    const idle = formattingToolbarParts(editor, false, false);
    expect(idle).toEqual({ marks: [], style: null, table: null });
  });

  it("the default block transforms toggle on the whole textblock", () => {
    const { editor, calls, callArgs } = makeEditor();
    const parts = formattingToolbarParts(editor, true, false);
    if (!parts.style || parts.style.kind !== "menu") throw new Error("no style menu");
    runLeaf(parts.style.items, "heading-2");
    expect(calls).toEqual(["focus", "toggleHeading", "run"]);
    expect(callArgs.toggleHeading).toEqual([{ level: 2 }]);
    calls.length = 0;
    runLeaf(parts.style.items, "bullet-list");
    expect(calls).toEqual(["focus", "toggleBulletList", "run"]);
    calls.length = 0;
    runLeaf(parts.style.items, "numbered-list");
    expect(calls).toEqual(["focus", "toggleOrderedList", "run"]);
    calls.length = 0;
    runLeaf(parts.style.items, "quote");
    expect(calls).toEqual(["focus", "toggleBlockquote", "run"]);
  });

  it("a host's block transforms replace the defaults (the body's partial-selection extraction)", () => {
    const { editor, calls } = makeEditor();
    const setHeading = vi.fn();
    const wrapBlock = vi.fn();
    const parts = formattingToolbarParts(editor, true, false, { setHeading, wrapBlock });
    if (!parts.style || parts.style.kind !== "menu") throw new Error("no style menu");
    runLeaf(parts.style.items, "heading-3");
    runLeaf(parts.style.items, "quote");
    runLeaf(parts.style.items, "bullet-list");
    expect(setHeading).toHaveBeenCalledWith(3);
    expect(wrapBlock.mock.calls).toEqual([["blockquote"], ["bulletList"]]);
    expect(calls).toEqual([]);
  });

  it("Insert table is offered in the Style menu only outside a table, whatever the host", () => {
    const { editor } = makeEditor();
    const outside = formattingToolbarParts(editor, true, false, { setHeading: vi.fn() });
    const inside = formattingToolbarParts(editor, true, true, { setHeading: vi.fn() });
    if (!outside.style || outside.style.kind !== "menu" || !inside.style || inside.style.kind !== "menu") {
      throw new Error("no style menu");
    }
    expect(leafIds(outside.style.items)).toContain("insert-table");
    expect(leafIds(inside.style.items)).not.toContain("insert-table");
  });
});
