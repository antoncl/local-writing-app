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
    tabs: [],
    activeBodyTab: "body",
    ...over,
  };
}

function baseOn(over: Partial<{ toggleInteriority: () => void; authoringLayerChange: undefined; selectBodyTab: (id: string) => void }> = {}) {
  return { toggleInteriority: () => {}, authoringLayerChange: undefined, selectBodyTab: () => {}, ...over };
}

describe("EditorHeader", () => {
  it("renders the title field snippet's output and the word-count chip for a scene", () => {
    render(EditorHeader, {
      model: baseModel(),
      on: baseOn(),
    });
    expect(screen.getByDisplayValue("Chapter One")).toBeInTheDocument();
    expect(screen.getByText(/42 words/)).toBeInTheDocument();
  });

  it("renders the void branch (no header content) for a chat body, even with a scene open", () => {
    const { container } = render(EditorHeader, {
      model: baseModel({ bodyShape: "chat" }),
      on: baseOn(),
    });
    expect(container.querySelector(".editor-header-void")).not.toBeNull();
    expect(container.querySelector(".editor-header")).toBeNull();
    expect(container.querySelector(".title-input")).toBeNull();
  });

  it("shows the interiority toggle only when hasInteriorityBeats, and calls on.toggleInteriority", async () => {
    const toggleInteriority = vi.fn();
    const { rerender } = render(EditorHeader, {
      model: baseModel({ hasInteriorityBeats: false }),
      on: baseOn({ toggleInteriority }),
    });
    expect(screen.queryByRole("button", { name: /Interiority/ })).toBeNull();

    await rerender({
      model: baseModel({ hasInteriorityBeats: true }),
      on: baseOn({ toggleInteriority }),
    });
    const button = screen.getByRole("button", { name: /Interiority/ });
    await fireEvent.click(button);
    expect(toggleInteriority).toHaveBeenCalledTimes(1);
  });

  it("renders no strip when there are no tabs", () => {
    const { container } = render(EditorHeader, { model: baseModel(), on: baseOn() });
    expect(container.querySelector(".body-tabs")).toBeNull();
  });

  describe("body tab strip (#2010)", () => {
    const tabs = [
      { id: "body" as const, kind: "body" as const, label: "Body", fieldIds: [] },
      { id: "list:relationships" as const, kind: "list" as const, label: "Relationships", fieldIds: ["relationships"], count: 2 },
      { id: "list:allies" as const, kind: "list" as const, label: "Allies", fieldIds: ["allies"] },
    ];

    it("renders Body, Relationships 2, Allies (empty, no count)", () => {
      render(EditorHeader, { model: baseModel({ tabs }), on: baseOn() });
      const strip = screen.getByRole("tablist", { name: "Body" });
      const buttons = strip.querySelectorAll("button");
      expect(buttons).toHaveLength(3);
      expect(buttons[0].textContent).toBe("Body");
      expect(buttons[1].textContent).toBe("Relationships2");
      expect(buttons[2].textContent).toBe("Allies");
    });

    it("clicking a tab calls on.selectBodyTab with its id", async () => {
      const selectBodyTab = vi.fn();
      render(EditorHeader, { model: baseModel({ tabs }), on: baseOn({ selectBodyTab }) });
      await fireEvent.click(screen.getByRole("tab", { name: /Allies/ }));
      expect(selectBodyTab).toHaveBeenCalledWith("list:allies");
    });

    it("ArrowRight moves the selection to the next tab", async () => {
      const selectBodyTab = vi.fn();
      render(EditorHeader, {
        model: baseModel({ tabs, activeBodyTab: "body" }),
        on: baseOn({ selectBodyTab }),
      });
      const strip = screen.getByRole("tablist", { name: "Body" });
      await fireEvent.keyDown(strip, { key: "ArrowRight" });
      expect(selectBodyTab).toHaveBeenCalledWith("list:relationships");
    });

    it("chat shape renders no strip", () => {
      const { container } = render(EditorHeader, {
        model: baseModel({ bodyShape: "chat", tabs }),
        on: baseOn(),
      });
      expect(container.querySelector(".body-tabs")).toBeNull();
    });
  });
});
