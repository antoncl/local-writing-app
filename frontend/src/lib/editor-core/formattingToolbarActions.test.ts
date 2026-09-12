import { describe, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/core";
import { formattingToolbarActions, formattingToolbarParts } from "./formattingToolbarActions";
import { setSelectionHeading, wrapSelectionBlock } from "./blockTransforms";
import { isToolbarSeparator, isToolbarSubmenu, type ToolbarAction, type ToolbarMenuEntry } from "./selectionToolbar";

vi.mock("./blockTransforms", () => ({ setSelectionHeading: vi.fn(), wrapSelectionBlock: vi.fn() }));

// A chainable editor stub: `chain()` returns a Proxy whose every property
// access yields a function returning the proxy itself (so calls compose
// fluently, as TipTap's chain does), except `run`, which records the calls
// made so far and returns true. Arguments passed to a command (e.g.
// `insertTable({...})`) are recorded alongside the method name. The selection
// ends at `selectionTo` — what "Insert table" collapses to.
function makeEditor(selectionTo = 7) {
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
  const editor = { chain: () => chain, state: { selection: { to: selectionTo } } } as unknown as Editor;
  return { editor, calls, callArgs };
}

function actionIds(actions: ToolbarAction[]) {
  return actions.map((a) => a.id);
}

function leafIds(items: ToolbarMenuEntry[]): string[] {
  return items.map((e) => e.id);
}

function runLeaf(items: ToolbarMenuEntry[], id: string) {
  const leaf = items.find((e) => e.id === id);
  if (!leaf || isToolbarSeparator(leaf) || isToolbarSubmenu(leaf)) throw new Error(`no ${id} leaf`);
  void leaf.run();
}

function styleOf(editor: Editor, hasText: boolean, inTable: boolean): ToolbarMenuEntry[] {
  const { style } = formattingToolbarParts(editor, hasText, inTable);
  if (!style) throw new Error("no style menu");
  return style.items;
}

describe("formattingToolbarParts (#1893: the body and the rail share one formatting core)", () => {
  it("hasText, no table: marks + Style (with Insert table), no Table menu", () => {
    const { editor } = makeEditor();
    const parts = formattingToolbarParts(editor, true, false);
    expect(actionIds(parts.marks)).toEqual(["bold", "italic", "strike"]);
    expect(parts.style?.id).toBe("style");
    expect(leafIds(parts.style!.items)).toEqual([
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
    expect(parts.table).toBeNull();
  });

  it("hasText + inTable: marks + Style (no Insert table) + Table menu", () => {
    const { editor } = makeEditor();
    const parts = formattingToolbarParts(editor, true, true);
    expect(parts.marks).toHaveLength(3);
    expect(leafIds(parts.style!.items)).not.toContain("insert-table");
    expect(parts.table?.id).toBe("table");
  });

  it("no selection, inTable: Table menu only", () => {
    const { editor } = makeEditor();
    const parts = formattingToolbarParts(editor, false, true);
    expect(parts.marks).toEqual([]);
    expect(parts.style).toBeNull();
    expect(parts.table?.id).toBe("table");
  });

  it("no selection, no table: nothing", () => {
    const { editor } = makeEditor();
    expect(formattingToolbarParts(editor, false, false)).toEqual({ marks: [], style: null, table: null });
  });

  it("running bold calls toggleBold then run", () => {
    const { editor, calls } = makeEditor();
    const bold = formattingToolbarParts(editor, true, false).marks.find((a) => a.id === "bold");
    if (!bold || bold.kind !== "button") throw new Error("no bold button");
    void bold.run();
    expect(calls).toEqual(["focus", "toggleBold", "run"]);
  });

  it("the Style menu's blocks go through the one block-transform implementation", () => {
    const { editor, calls } = makeEditor();
    const items = styleOf(editor, true, false);
    runLeaf(items, "heading-3");
    runLeaf(items, "quote");
    runLeaf(items, "bullet-list");
    runLeaf(items, "numbered-list");
    expect(vi.mocked(setSelectionHeading).mock.calls).toEqual([[editor, 3]]);
    expect(vi.mocked(wrapSelectionBlock).mock.calls).toEqual([
      [editor, "blockquote"],
      [editor, "bulletList"],
      [editor, "orderedList"],
    ]);
    expect(calls).toEqual([]);
  });

  it("Insert table keeps the selected text: collapses to the selection's end, then inserts 3x3 with a header row", () => {
    const { editor, calls, callArgs } = makeEditor(42);
    runLeaf(styleOf(editor, true, false), "insert-table");
    expect(calls).toEqual(["focus", "setTextSelection", "insertTable", "run"]);
    expect(callArgs.setTextSelection).toEqual([42]);
    expect(callArgs.insertTable).toEqual([{ rows: 3, cols: 3, withHeaderRow: true }]);
  });
});

describe("formattingToolbarActions (the rail's long_text toolbar, #1884 slice 1)", () => {
  it("is the parts as one list, in order, with no Revise or To-do", () => {
    const { editor } = makeEditor();
    expect(actionIds(formattingToolbarActions(editor, true, false))).toEqual(["bold", "italic", "strike", "style"]);
    expect(actionIds(formattingToolbarActions(editor, true, true))).toEqual(["bold", "italic", "strike", "style", "table"]);
    expect(actionIds(formattingToolbarActions(editor, false, true))).toEqual(["table"]);
    expect(formattingToolbarActions(editor, false, false)).toEqual([]);
  });
});
