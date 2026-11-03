// @vitest-environment happy-dom
// The revealed interiority textarea writes back through `leaveOnAppExit` (#2649): a
// blur toward a non-app target saves, and a later value change plus a press elsewhere
// in the app saves the NEW value (a writing assistant's fix after the blur).
import { afterEach, describe, expect, it } from "vitest";
import { Schema } from "@tiptap/pm/model";
import { EditorState } from "@tiptap/pm/state";
import { EditorView } from "@tiptap/pm/view";

import { createInteriorityPlugin, findBeats, INTERIORITY_META } from "./interiorityReveal";

const schema = new Schema({
  nodes: {
    doc: { content: "block+" },
    paragraph: { group: "block", content: "inline*", toDOM: () => ["p", 0] },
    text: { group: "inline" },
  },
  marks: {
    character: {
      attrs: { characterId: { default: null }, internal: { default: "" } },
      toDOM: (m) => ["span", { "data-character": m.attrs.characterId }, 0],
    },
  },
});

let view: EditorView | null = null;
afterEach(() => {
  view?.destroy();
  view = null;
  document.body.replaceChildren();
});

function mount() {
  const app = document.createElement("div");
  app.id = "app";
  const outside = document.createElement("button");
  const host = document.createElement("div");
  app.append(host, outside);
  document.body.append(app);
  const mark = schema.marks.character.create({ characterId: "annie", internal: "old" });
  const doc = schema.node("doc", null, [schema.node("paragraph", null, [schema.text("She fired.", [mark])])]);
  view = new EditorView(host, {
    state: EditorState.create({ doc, plugins: [createInteriorityPlugin(() => "")] }),
  });
  view.dispatch(view.state.tr.setMeta(INTERIORITY_META.revealAll, true));
  const area = host.querySelector("textarea") as HTMLTextAreaElement;
  return { area, outside };
}

const internal = () => findBeats(view!.state.doc, schema.marks.character)[0].internal;

describe("interiority textarea write-back (#2649)", () => {
  it("keeps the box live on a blur toward a non-app target, so a later fix lands in it", () => {
    const { area, outside } = mount();
    area.value = "first";
    area.dispatchEvent(new FocusEvent("focusout", { bubbles: true, relatedTarget: null }));
    // Nothing is written yet: a write-back redraws the widget and detaches the box.
    expect(internal()).toBe("old");
    expect(area.isConnected).toBe(true);
    // The assistant writes its fix into the same box; the next app press saves it.
    area.value = "assistant fix";
    outside.dispatchEvent(new Event("pointerdown", { bubbles: true, composed: true }));
    expect(internal()).toBe("assistant fix");
  });

  it("writes as soon as the window loses focus after such a blur", () => {
    const { area } = mount();
    area.value = "typed";
    area.dispatchEvent(new FocusEvent("focusout", { bubbles: true, relatedTarget: null }));
    window.dispatchEvent(new FocusEvent("blur"));
    expect(internal()).toBe("typed");
  });

  it("writes when focus moves to another app control", () => {
    const { area, outside } = mount();
    area.value = "moved";
    area.dispatchEvent(new FocusEvent("focusout", { bubbles: true, relatedTarget: outside }));
    expect(internal()).toBe("moved");
  });

  it("a window blur with no pending blur writes nothing", () => {
    mount();
    window.dispatchEvent(new FocusEvent("blur"));
    expect(internal()).toBe("old");
  });
});
