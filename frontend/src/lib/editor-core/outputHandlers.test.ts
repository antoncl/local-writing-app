import { describe, expect, it } from "vitest";
import type { Editor } from "@tiptap/core";
import type { AIEntryPatch } from "@/lib/types";

import {
  inlineHandler,
  extractHandler,
  inlineDestinationFor,
  outputHandlerFor,
  type ExtractHost,
  type InlineDestination,
  type InlineGathered,
  type InlineHost,
} from "./outputHandlers";

// ADR-0065 S2: the OutputHandler registry + the generic base. S2a lifted the
// inline source-gather out of AiSuggestionController; S2b registers
// extract_to_node (the brainstorm commit) and unifies produce/apply onto the
// generic `OutputHandler<Host, Produced>` base. These pin routing, the inline
// gather, and that both handlers honour the base contract.

// A fake TipTap editor: selection + a textBetween that echoes its range so a
// gather's slices are checkable, and a doc size.
function fakeEditor(
  selection: { from: number; to: number },
  size = 100,
  textBetween: (from: number, to: number) => string = (from, to) => `T[${from},${to}]`,
): Editor {
  return {
    state: { selection, doc: { content: { size }, textBetween } },
  } as unknown as Editor;
}

function makeInlineHost(
  editor: Editor | null,
  destination: InlineDestination,
): InlineHost & { errors: { message: string; anchor?: number }[] } {
  const errors: { message: string; anchor?: number }[] = [];
  return {
    errors,
    destination,
    getEditor: () => editor,
    setError: (message, anchor) => errors.push({ message, anchor }),
    streamInline: async () => {},
  };
}

const patch = (over: Partial<AIEntryPatch> = {}): AIEntryPatch => ({
  body: null,
  fields: {},
  dropped: [],
  garbled: false,
  ...over,
});

describe("outputHandlerFor — routing", () => {
  it("routes a commit to extract_to_node (a commit only rides on chat_panel)", () => {
    expect(outputHandlerFor({ kind: "chat_panel", commit: { review: "visual_diff" } })?.key).toBe(
      "extract_to_node",
    );
  });

  it("routes the two inline kinds to inline", () => {
    expect(outputHandlerFor({ kind: "append_to_body" })?.key).toBe("inline");
    expect(outputHandlerFor({ kind: "replace_selection" })?.key).toBe("inline");
  });

  it("has no handler for a plain chat_panel, unset, or null (result stays in the chat)", () => {
    expect(outputHandlerFor({ kind: "chat_panel" })).toBeNull();
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

describe("the handlers' declarative bundles", () => {
  it("inline is the scan / inline_mark / inline bundle", () => {
    expect(inlineHandler).toMatchObject({
      key: "inline",
      source: "scan",
      review: "inline_mark",
      activation: "inline",
    });
  });

  it("extract_to_node is the transcript / patch_diff / conversation bundle", () => {
    expect(extractHandler).toMatchObject({
      key: "extract_to_node",
      source: "transcript",
      review: "patch_diff",
      activation: "conversation",
    });
  });
});

describe("inlineHandler.produce — the gather", () => {
  it("cursor: gathers text before and after the caret, no selection", () => {
    const host = makeInlineHost(fakeEditor({ from: 10, to: 10 }), "cursor");
    expect(inlineHandler.produce(host)).toEqual({
      destination: "cursor",
      from: 10,
      to: 10,
      textBefore: "T[0,10]",
      textAfter: "T[10,100]",
    });
    expect(host.errors).toEqual([]);
  });

  it("selection: gathers the selection plus clamped surrounding context", () => {
    const host = makeInlineHost(fakeEditor({ from: 20, to: 30 }, 200), "selection");
    expect(inlineHandler.produce(host)).toEqual({
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
    const host = makeInlineHost(fakeEditor({ from: 15, to: 15 }), "selection");
    expect(inlineHandler.produce(host)).toBeNull();
    expect(host.errors).toEqual([{ message: "Select text to revise.", anchor: 15 }]);
  });

  it("selection: a whitespace-only selection is a reported error", () => {
    const host = makeInlineHost(fakeEditor({ from: 20, to: 30 }, 200, () => "   "), "selection");
    expect(inlineHandler.produce(host)).toBeNull();
    expect(host.errors).toEqual([{ message: "Select non-empty text to revise.", anchor: 20 }]);
  });

  it("returns null when there is no editor", () => {
    const host = makeInlineHost(null, "cursor");
    expect(inlineHandler.produce(host)).toBeNull();
    expect(host.errors).toEqual([]);
  });
});

describe("inlineHandler.apply", () => {
  it("delegates to the host's streamInline primitive", async () => {
    const seen: InlineGathered[] = [];
    const host: InlineHost = {
      destination: "cursor",
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

describe("extractHandler — produce/apply delegate to the host", () => {
  it("produce runs the host's extraction", async () => {
    const p = patch({ fields: { name: "Vale" } });
    const host: ExtractHost = { extract: async () => p, publish: () => {} };
    expect(await extractHandler.produce(host)).toBe(p);
  });

  it("apply publishes the produced patch through the host", async () => {
    const published: AIEntryPatch[] = [];
    const host: ExtractHost = {
      extract: async () => null,
      publish: (pp) => {
        published.push(pp);
      },
    };
    const p = patch({ body: "a life" });
    await extractHandler.apply(p, host);
    expect(published).toEqual([p]);
  });
});
