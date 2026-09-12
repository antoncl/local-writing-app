import { describe, expect, it } from "vitest";
import type { Editor } from "@tiptap/core";
import { buildLongTextToolbarActions } from "./longTextToolbarActions";
import { isToolbarSeparator, isToolbarSubmenu, type ToolbarMenuEntry } from "./selectionToolbar";

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

function actionIds(actions: ReturnType<typeof buildLongTextToolbarActions>) {
  return actions.map((a) => a.id);
}

function styleItems(actions: ReturnType<typeof buildLongTextToolbarActions>): ToolbarMenuEntry[] {
  const style = actions.find((a) => a.id === "style");
  if (!style || style.kind !== "menu") throw new Error("no style menu");
  return style.items;
}

function leafIds(items: ToolbarMenuEntry[]): string[] {
  return items.map((e) => e.id);
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
    const insertTable = styleItems(actions).find((e) => e.id === "insert-table");
    if (!insertTable || isToolbarSeparator(insertTable) || isToolbarSubmenu(insertTable)) {
      throw new Error("no insert-table leaf");
    }
    void insertTable.run();
    expect(calls).toContain("insertTable");
    expect(calls).toContain("run");
    expect(callArgs.insertTable).toEqual([{ rows: 3, cols: 3, withHeaderRow: true }]);
  });
});
