import { describe, expect, it } from "vitest";
import type { Editor } from "@tiptap/core";

import {
  inlineHandler,
  inlineDestinationFor,
  outputHandlerFor,
  type InlineGathered,
  type InlineHost,
} from "./outputHandlers";

// ADR-0065 S2a: the OutputHandler registry + the inline handler. These pin the
// routing (which output is inline vs not), the destination sub-choice, and the
// inline `produce` gather — the source logic lifted out of AiSuggestionController.

// A fake TipTap editor: selection + a textBetween that echoes its range so a
// gather's slices are checkable, and a doc size. textBetween can be overridden
// (e.g. to return whitespace) to exercise the empty/blank-selection guards.
function fakeEditor(
  selection: { from: number; to: number },
  size = 100,
  textBetween: (from: number, to: number) => string = (from, to) => `T[${from},${to}]`,
): Editor {
  return {
    state: {
      selection,
      doc: { content: { size }, textBetween },
    },
  } as unknown as Editor;
}

function makeHost(editor: Editor | null): InlineHost & { errors: { message: string; anchor?: number }[] } {
  const errors: { message: string; anchor?: number }[] = [];
  return {
    errors,
    getEditor: () => editor,
    setError: (message, anchor) => errors.push({ message, anchor }),
    streamInline: async () => {},
  };
}

describe("outputHandlerFor — routing (S2a)", () => {
  it("routes the two inline kinds to the inline handler", () => {
    expect(outputHandlerFor({ kind: "append_to_body" })?.key).toBe("inline");
    expect(outputHandlerFor({ kind: "replace_selection" })?.key).toBe("inline");
  });

  it("returns null for chat_panel, commit, unset, and null (not inline / not yet registered)", () => {
    // chat_panel (general) and commit (extract_to_node) stay with their current
    // consumers until S2b registers extract_to_node.
    expect(outputHandlerFor({ kind: "chat_panel" })).toBeNull();
    expect(outputHandlerFor({ kind: "chat_panel", commit: { review: "visual_diff" } })).toBeNull();
    expect(outputHandlerFor({ kind: "" })).toBeNull();
    expect(outputHandlerFor(null)).toBeNull();
    expect(outputHandlerFor(undefined)).toBeNull();
  });
});

describe("inlineDestinationFor", () => {
  it("maps replace_selection→selection, everything else→cursor", () => {
    expect(inlineDestinationFor({ kind: "replace_selection" })).toBe("selection");
    expect(inlineDestinationFor({ kind: "append_to_body" })).toBe("cursor");
    expect(inlineDestinationFor(null)).toBe("cursor");
  });
});

describe("inlineHandler — declarative bundle", () => {
  it("is the inline bundle (scan source, inline_mark review, inline activation)", () => {
    expect(inlineHandler).toMatchObject({
      key: "inline",
      source: "scan",
      review: "inline_mark",
      activation: "inline",
    });
  });
});

describe("inlineHandler.produce — the gather", () => {
  it("cursor: gathers text before and after the caret, no selection", () => {
    const host = makeHost(fakeEditor({ from: 10, to: 10 }));
    expect(inlineHandler.produce(host, "cursor")).toEqual({
      destination: "cursor",
      from: 10,
      to: 10,
      textBefore: "T[0,10]",
      textAfter: "T[10,100]",
    });
    expect(host.errors).toEqual([]);
  });

  it("selection: gathers the selection plus clamped surrounding context", () => {
    const host = makeHost(fakeEditor({ from: 20, to: 30 }, 200));
    expect(inlineHandler.produce(host, "selection")).toEqual({
      destination: "selection",
      from: 20,
      to: 30,
      selectionText: "T[20,30]",
      // beforeStart = max(0, 20-600) = 0 ; afterEnd = min(200, 30+600) = 200
      textBefore: "T[0,20]",
      textAfter: "T[30,200]",
    });
  });

  it("selection: an empty selection is a reported error, not a gather", () => {
    const host = makeHost(fakeEditor({ from: 15, to: 15 }));
    expect(inlineHandler.produce(host, "selection")).toBeNull();
    expect(host.errors).toEqual([{ message: "Select text to revise.", anchor: 15 }]);
  });

  it("selection: a whitespace-only selection is a reported error", () => {
    const host = makeHost(fakeEditor({ from: 20, to: 30 }, 200, () => "   "));
    expect(inlineHandler.produce(host, "selection")).toBeNull();
    expect(host.errors).toEqual([{ message: "Select non-empty text to revise.", anchor: 20 }]);
  });

  it("returns null when there is no editor", () => {
    const host = makeHost(null);
    expect(inlineHandler.produce(host, "cursor")).toBeNull();
    expect(host.errors).toEqual([]);
  });
});

describe("inlineHandler.apply", () => {
  it("delegates to the host's streamInline primitive", async () => {
    const seen: InlineGathered[] = [];
    const host: InlineHost = {
      getEditor: () => null,
      setError: () => {},
      streamInline: async (g) => {
        seen.push(g);
      },
    };
    const gathered: InlineGathered = {
      destination: "cursor",
      from: 1,
      to: 1,
      textBefore: "a",
      textAfter: "b",
    };
    await inlineHandler.apply(gathered, host);
    expect(seen).toEqual([gathered]);
  });
});
