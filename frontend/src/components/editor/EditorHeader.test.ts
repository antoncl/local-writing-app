// @vitest-environment happy-dom
// EditorHeader (#2029 split of NodeEditor): pins the chat void branch (no
// header content, no error), the title snippet + word-count chip rendering
// for a scene, and the interiority toggle's gating + callback wiring.
import { describe, expect, it, vi } from "vitest";
import { createRawSnippet } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import EditorHeader from "./EditorHeader.svelte";
import type { EditableDocument } from "@/lib/types";

function scene(over: Partial<EditableDocument> = {}): EditableDocument {
  return {
    id: "scene_1",
    title: "Chapter One",
    body: "",
    status: "draft",
    entry_type: "manuscript:scene",
    metadata: {},
    ...over,
  } as EditableDocument;
}

function chatTitleField() {
  return createRawSnippet(() => ({
    render: () => `<input class="title-input" value="Chapter One" />`,
  }));
}

function baseModel(over: Record<string, unknown> = {}) {
  return {
    scene: scene(),
    documentKind: "manuscript" as const,
    bodyShape: "prose" as const,
    documentNameLabel: "Title",
    titleMutated: false,
    hasInteriorityBeats: false,
    interiorityRevealed: false,
    liveWordCount: 42,
    characterCostRowsView: [],
    lastInvocationCostUsd: null,
    sceneSessionCostUsd: 0,
    rollupCostKind: null,
    todoStatusHint: "",
    authoringLayerId: null,
    recentlySaved: false,
    chatTitleField: chatTitleField(),
    ...over,
  };
}

describe("EditorHeader", () => {
  it("renders the title field snippet's output and the word-count chip for a scene", () => {
    render(EditorHeader, {
      model: baseModel(),
      on: { toggleInteriority: () => {}, authoringLayerChange: undefined },
    });
    expect(screen.getByDisplayValue("Chapter One")).toBeInTheDocument();
    expect(screen.getByText(/42 words/)).toBeInTheDocument();
  });

  it("renders the void branch (no header content) for a chat body, even with a scene open", () => {
    const { container } = render(EditorHeader, {
      model: baseModel({ bodyShape: "chat" }),
      on: { toggleInteriority: () => {}, authoringLayerChange: undefined },
    });
    expect(container.querySelector(".editor-header-void")).not.toBeNull();
    expect(container.querySelector(".editor-header")).toBeNull();
    expect(container.querySelector(".title-input")).toBeNull();
  });

  it("shows the interiority toggle only when hasInteriorityBeats, and calls on.toggleInteriority", async () => {
    const toggleInteriority = vi.fn();
    const { rerender } = render(EditorHeader, {
      model: baseModel({ hasInteriorityBeats: false }),
      on: { toggleInteriority, authoringLayerChange: undefined },
    });
    expect(screen.queryByRole("button", { name: /Interiority/ })).toBeNull();

    await rerender({
      model: baseModel({ hasInteriorityBeats: true }),
      on: { toggleInteriority, authoringLayerChange: undefined },
    });
    const button = screen.getByRole("button", { name: /Interiority/ });
    await fireEvent.click(button);
    expect(toggleInteriority).toHaveBeenCalledTimes(1);
  });
});
