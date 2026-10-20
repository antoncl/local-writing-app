import { describe, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/core";
import type { AIEntryPatch } from "@/lib/types";

import {
  REVISE_CONTEXT_CHARS,
  inlineHandler,
  inlineEditsHandler,
  inlineNotesHandler,
  extractHandler,
  gatheredRequestFields,
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
    // No mutation pills in the fake doc: nodesBetween visits nothing.
    state: { selection, doc: { content: { size }, textBetween, nodesBetween: () => {} } },
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
    runLineEdits: async () => {},
    runLineNotes: async () => {},
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
  it("routes the extract_to_node handler (the brainstorm commit) by its key", () => {
    expect(
      outputHandlerFor({ handler: "extract_to_node", commit: { review: "visual_diff" } })?.key,
    ).toBe("extract_to_node");
  });

  it("routes the inline handler to inline, regardless of destination", () => {
    expect(outputHandlerFor({ handler: "inline" })?.key).toBe("inline");
    expect(outputHandlerFor({ handler: "inline", destination: "selection" })?.key).toBe("inline");
  });

  it("has no handler for a general chat, unset, unknown, or null (result stays in the chat)", () => {
    expect(outputHandlerFor({})).toBeNull(); // a general chat: a present-but-empty output block
    expect(outputHandlerFor({ handler: "" })).toBeNull();
    expect(outputHandlerFor({ handler: "bogus" })).toBeNull();
    expect(outputHandlerFor(null)).toBeNull();
    expect(outputHandlerFor(undefined)).toBeNull();
  });
});

describe("inlineDestinationFor", () => {
  it("maps destination selection→selection, everything else→cursor", () => {
    expect(inlineDestinationFor({ handler: "inline", destination: "selection" })).toBe("selection");
    expect(inlineDestinationFor({ handler: "inline" })).toBe("cursor");
    expect(inlineDestinationFor({ handler: "inline", destination: "cursor" })).toBe("cursor");
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

  it("inline_edits is the scan / edit_list / inline bundle", () => {
    expect(inlineEditsHandler).toMatchObject({
      key: "inline_edits",
      source: "scan",
      review: "edit_list",
      activation: "inline",
    });
  });

  it("routes the inline_edits handler by its key", () => {
    expect(outputHandlerFor({ handler: "inline_edits" })?.key).toBe("inline_edits");
  });

  it("inline_notes is the scan / note_list / inline bundle, routed by its key, on the selection", () => {
    expect(inlineNotesHandler).toMatchObject({
      key: "inline_notes",
      source: "scan",
      review: "note_list",
      activation: "inline",
    });
    expect(outputHandlerFor({ handler: "inline_notes" })).toBe(inlineNotesHandler);
    expect(inlineNotesHandler.surface({ handler: "inline_notes", destination: "cursor" })).toBe("selection");
  });

  it("inline_notes applies through the host's runLineNotes, not runLineEdits", async () => {
    const host = { runLineNotes: vi.fn(async () => {}), runLineEdits: vi.fn(async () => {}) } as unknown as InlineHost;
    const gathered = { destination: "selection", from: 1, to: 2, textBefore: "", textAfter: "" } as InlineGathered;
    await inlineNotesHandler.apply(gathered, host);
    expect(host.runLineNotes).toHaveBeenCalledWith(gathered);
    expect(host.runLineEdits).not.toHaveBeenCalled();
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
      // A short doc: the window runs past both ends, so it clamps to them.
      textBefore: "T[0,20]",
      textAfter: "T[30,200]",
      markersBefore: [],
    });
  });

  it("selection: a long doc sends REVISE_CONTEXT_CHARS of context each side (#2565)", () => {
    const host = makeInlineHost(fakeEditor({ from: 5000, to: 5010 }, 10000), "selection");
    expect(inlineHandler.produce(host)).toMatchObject({
      textBefore: `T[${5000 - REVISE_CONTEXT_CHARS},5000]`,
      textAfter: `T[5010,${5010 + REVISE_CONTEXT_CHARS}]`,
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
      runLineEdits: async () => {
        throw new Error("inline must stream, not run line edits");
      },
      runLineNotes: async () => {
        throw new Error("inline must stream, not run a check");
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

describe("surface — each handler names its own editor surface (#2465)", () => {
  it("inline reads the declared destination; inline_edits is the selection; extract is the conversation", () => {
    expect(inlineHandler.surface({ handler: "inline" })).toBe("cursor");
    expect(inlineHandler.surface({ handler: "inline", destination: "selection" })).toBe("selection");
    expect(inlineEditsHandler.surface({ handler: "inline_edits", destination: "cursor" })).toBe("selection");
    expect(extractHandler.surface({ handler: "extract_to_node" })).toBe("conversation");
  });
});

describe("inlineEditsHandler.apply (#2465)", () => {
  it("delegates to the host's runLineEdits, never the stream", async () => {
    const seen: InlineGathered[] = [];
    const host: InlineHost = {
      destination: "selection",
      getEditor: () => null,
      setError: () => {},
      streamInline: async () => {
        throw new Error("line edits must not stream");
      },
      runLineEdits: async (g) => {
        seen.push(g);
      },
      runLineNotes: async () => {
        throw new Error("line edits must not run a check");
      },
    };
    const gathered: InlineGathered = { destination: "selection", from: 1, to: 4, textBefore: "", textAfter: "", selectionText: "abc" };
    await inlineEditsHandler.apply(gathered, host);
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

describe("gatheredRequestFields (#2491)", () => {
  const base = { from: 1, to: 5, textBefore: "before", textAfter: "after" };

  it("a selection run sends its text, the selection and the markers before it", () => {
    expect(
      gatheredRequestFields({ ...base, destination: "selection", selectionText: "sel", markersBefore: ["a1", "c1"] }),
    ).toEqual({ text_before: "before", text_after: "after", selection: "sel", markers_before_selection: ["a1", "c1"] });
  });

  it("an empty marker list is still sent: nothing precedes the selection", () => {
    expect(
      gatheredRequestFields({ ...base, destination: "selection", selectionText: "sel", markersBefore: [] }),
    ).toMatchObject({ markers_before_selection: [] });
  });

  it("a cursor run names no selection and no markers", () => {
    expect(gatheredRequestFields({ ...base, destination: "cursor" })).toEqual({
      text_before: "before",
      text_after: "after",
    });
  });
});
