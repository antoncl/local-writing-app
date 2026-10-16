// @vitest-environment happy-dom
// #2460: the review plugin keeps placed edits in state (document untouched),
// decorates them, and resolves them one at a time or all at once.
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import {
  LineEditSuggestions,
  acceptAllLineEdits,
  acceptCurrentLineEdit,
  acceptLineEdit,
  installLineEdits,
  lineEditState,
  rejectAllLineEdits,
  rejectCurrentLineEdit,
  rejectLineEdit,
  setCurrentLineEdit,
  marginCardWidth,
  setLineEditCardWide,
  stepLineEdit,
} from "./lineEditSuggestions";
import { placeLineEdits } from "./lineEdits";
import { tableExtensions } from "./alignedTable";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

const TEXT = "The cat sat on the mat.";

function setup(select = false) {
  const host = document.createElement("div");
  document.body.append(host);
  const editor = new Editor({
    element: host,
    extensions: [proseStarterKit(), LineEditSuggestions],
    content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: TEXT }] }] },
  });
  editors.push(editor);
  const { placed } = placeLineEdits(editor.state.doc, 0, editor.state.doc.content.size, [
    { find: "cat", replace: "dog", reason: "livelier" },
    { find: " on the mat", replace: "", reason: "cut" },
  ]);
  if (select) editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 });
  installLineEdits(editor.view, placed, editor.state.doc.content.size - 1);
  return editor;
}
const setupSelected = () => ({ editor: setup(true) });
const docText = (editor: Editor) => editor.state.doc.textContent;

describe("LineEditSuggestions", () => {
  it("install leaves the document alone and decorates the passages and the new-words widget", () => {
    const editor = setup();
    expect(docText(editor)).toBe(TEXT);
    expect(lineEditState(editor.state).edits).toHaveLength(2);
    const dom = editor.view.dom;
    const old = dom.querySelectorAll(".line-edit");
    expect(old).toHaveLength(2);
    expect(old[0].getAttribute("title")).toBe("livelier");
    // one new-words span (the pure cut has none); the only buttons are the current edit's card
    expect(dom.querySelectorAll(".r-was")).toHaveLength(1);
    expect(dom.querySelector(".r-was")?.textContent).toBe("dog");
    expect(dom.querySelectorAll("button")).toHaveLength(5);
    expect(dom.querySelectorAll("button")).toHaveLength(dom.querySelectorAll(".line-edit-card button").length);
  });

  describe("decision card", () => {
    const cards = (editor: Editor) => editor.view.dom.querySelectorAll('[data-testid="line-edit-card"]');
    const reasonOf = (editor: Editor) => editor.view.dom.querySelector('[data-testid="line-edit-card-reason"]')?.textContent;
    const click = (editor: Editor, id: string) =>
      (editor.view.dom.querySelector(`[data-testid="${id}"]`) as HTMLElement).click();

    it("renders once, for the current edit, with its reason and shortcut titles", () => {
      const editor = setup();
      expect(cards(editor)).toHaveLength(1);
      expect(reasonOf(editor)).toBe("livelier");
      expect(editor.view.dom.querySelector('[data-testid="line-edit-card-accept"]')?.getAttribute("title")).toContain("Alt+Enter");
      expect(editor.view.dom.querySelector('[data-testid="line-edit-card-reject"]')?.getAttribute("title")).toContain("Alt+Backspace");
      expect(editor.view.dom.querySelector('[data-testid="line-edit-card-prev"]')?.getAttribute("aria-label")).toBe("Previous edit");
    });

    it("renders Keep before Reject, titled, and clicking it calls keep with the current edit", () => {
      const editor = setup();
      const keep = vi.fn();
      const { placed } = placeLineEdits(editor.state.doc, 0, editor.state.doc.content.size, [
        { find: "cat", replace: "dog", reason: "livelier" },
      ]);
      rejectAllLineEdits(editor.view);
      installLineEdits(editor.view, placed, undefined, { keep });
      const button = editor.view.dom.querySelector<HTMLElement>('[data-testid="line-edit-card-keep"]')!;
      expect(button.getAttribute("title")).toBe("Keep as a TODO — decide later");
      expect(button.nextElementSibling).toBe(editor.view.dom.querySelector('[data-testid="line-edit-card-reject"]'));
      button.click();
      expect(keep).toHaveBeenCalledTimes(1);
      expect(keep.mock.calls[0][1]).toMatchObject({ find: "cat", replace: "dog", reason: "livelier" });
    });

    it("follows the current edit: step, accept advancing, selecting another edit", () => {
      const editor = setup();
      const [first, second] = lineEditState(editor.state).edits;
      stepLineEdit(editor.view, 1);
      expect(cards(editor)).toHaveLength(1);
      expect(reasonOf(editor)).toBe("cut");
      setCurrentLineEdit(editor.view, first.id);
      expect(reasonOf(editor)).toBe("livelier");
      acceptCurrentLineEdit(editor.view);
      expect(lineEditState(editor.state).currentId).toBe(second.id);
      expect(cards(editor)).toHaveLength(1);
      expect(reasonOf(editor)).toBe("cut");
    });

    it("disappears when no edits remain", () => {
      const editor = setup();
      rejectAllLineEdits(editor.view);
      expect(cards(editor)).toHaveLength(0);
    });

    it("buttons call through; accept is one undo step", () => {
      const editor = setup();
      click(editor, "line-edit-card-next");
      expect(reasonOf(editor)).toBe("cut");
      click(editor, "line-edit-card-prev");
      expect(reasonOf(editor)).toBe("livelier");
      click(editor, "line-edit-card-accept");
      expect(docText(editor)).toBe("The dog sat on the mat.");
      expect(reasonOf(editor)).toBe("cut");
      click(editor, "line-edit-card-reject");
      expect(docText(editor)).toBe("The dog sat on the mat.");
      expect(cards(editor)).toHaveLength(0);
      editor.commands.undo();
      expect(docText(editor)).toBe(TEXT);
    });

    it("keeps editor focus on mousedown, and sits at the paragraph end in narrow mode", () => {
      const editor = setup();
      const card = cards(editor)[0] as HTMLElement;
      expect(card.classList.contains("line-edit-card-wide")).toBe(false);
      expect(card.parentElement?.tagName).toBe("P");
      // last in the paragraph (PM's own trailing <br> may follow a widget)
      expect(card.nextSibling === null || (card.nextSibling as HTMLElement).className === "ProseMirror-trailingBreak").toBe(true);
      const down = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
      card.querySelector("button")!.dispatchEvent(down);
      expect(down.defaultPrevented).toBe(true);
    });

    it("wide mode puts the same card at the edit itself, right after its new words; one card either way", () => {
      const editor = setup();
      setLineEditCardWide(editor.view, true);
      const found = cards(editor);
      expect(found).toHaveLength(1);
      const card = found[0] as HTMLElement;
      expect(card.classList.contains("line-edit-card-wide")).toBe(true);
      // Older text first (#2533): the passage, then its coming words, then the card.
      expect((card.previousSibling as HTMLElement).className).toContain("r-was");
      expect(reasonOf(editor)).toBe("livelier");
      setLineEditCardWide(editor.view, false);
      expect(cards(editor)).toHaveLength(1);
      expect(cards(editor)[0].classList.contains("line-edit-card-wide")).toBe(false);
    });
  });

  it("collapses the selection to the end of the revised range on install", () => {
    const { editor } = setupSelected();
    const { from, to } = editor.state.selection;
    expect(from).toBe(to);
    expect(to).toBe(editor.state.doc.content.size - 1);
  });

  it("the first edit is current, and only the current passage carries the outline class", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    expect(lineEditState(editor.state).currentId).toBe(first.id);
    const dom = editor.view.dom;
    expect(dom.querySelectorAll(".line-edit.line-edit-current")).toHaveLength(1);
    expect(dom.querySelector(".line-edit.line-edit-current")?.textContent).toBe("cat");
    setCurrentLineEdit(editor.view, second.id);
    expect(dom.querySelector(".line-edit.line-edit-current")?.textContent).toBe(" on the mat");
  });

  it("clicking the passage or the new words makes that edit current", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    setCurrentLineEdit(editor.view, second.id);
    editor.view.dom.querySelector(".r-was")!.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, cancelable: true }),
    );
    expect(lineEditState(editor.state).currentId).toBe(first.id);
    const oldSecond = editor.view.dom.querySelectorAll(".line-edit")[1] as HTMLElement;
    editor.view.someProp("handleClick", (f) => f(editor.view, 0, { target: oldSecond } as unknown as MouseEvent));
    expect(lineEditState(editor.state).currentId).toBe(second.id);
  });

  it("stepLineEdit moves by position and wraps", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    stepLineEdit(editor.view, 1);
    expect(lineEditState(editor.state).currentId).toBe(second.id);
    stepLineEdit(editor.view, 1);
    expect(lineEditState(editor.state).currentId).toBe(first.id);
    stepLineEdit(editor.view, -1);
    expect(lineEditState(editor.state).currentId).toBe(second.id);
  });

  it("stepping scrolls the current edit's own span into view, not its paragraph", () => {
    const editor = setup();
    const [, second] = lineEditState(editor.state).edits;
    const scrolled: Element[] = [];
    const proto = Element.prototype as unknown as { scrollIntoView?: (o?: unknown) => void };
    const original = proto.scrollIntoView;
    const calls: unknown[] = [];
    proto.scrollIntoView = function (this: Element, opts?: unknown) {
      scrolled.push(this);
      calls.push(opts);
    };
    try {
      stepLineEdit(editor.view, 1);
    } finally {
      proto.scrollIntoView = original;
    }
    expect(scrolled).toHaveLength(1);
    expect(scrolled[0].getAttribute("data-line-edit-id")).toBe(String(second.id));
    expect(scrolled[0].tagName).not.toBe("P");
    expect(calls[0]).toEqual({ block: "nearest", inline: "nearest" });
  });

  it("after resolving the current edit, the next by position is current; wraps; none when empty", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    // current = first; accepting it moves to the second
    acceptCurrentLineEdit(editor.view);
    expect(docText(editor)).toBe("The dog sat on the mat.");
    expect(lineEditState(editor.state).currentId).toBe(second.id);
    expect(first.id).not.toBe(second.id);
    rejectCurrentLineEdit(editor.view);
    expect(lineEditState(editor.state)).toMatchObject({ edits: [], currentId: null });
  });

  it("resolving the last edit by position wraps current to the first", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    setCurrentLineEdit(editor.view, second.id);
    rejectCurrentLineEdit(editor.view);
    expect(lineEditState(editor.state).currentId).toBe(first.id);
  });

  it("accepting the current edit is one undo step", () => {
    const editor = setup();
    acceptCurrentLineEdit(editor.view);
    expect(docText(editor)).toBe("The dog sat on the mat.");
    editor.commands.undo();
    expect(docText(editor)).toBe(TEXT);
  });

  describe("keyboard", () => {
    const press = (editor: Editor, key: string, init: KeyboardEventInit = { altKey: true }) => {
      const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
      editor.view.dom.dispatchEvent(event);
      return event;
    };

    it("Alt+Down / Alt+Up step; Alt+Enter accepts; Alt+Backspace rejects the current edit", () => {
      const editor = setup();
      const [first, second] = lineEditState(editor.state).edits;
      expect(press(editor, "ArrowDown").defaultPrevented).toBe(true);
      expect(lineEditState(editor.state).currentId).toBe(second.id);
      press(editor, "ArrowUp");
      expect(lineEditState(editor.state).currentId).toBe(first.id);
      press(editor, "Enter");
      expect(docText(editor)).toBe("The dog sat on the mat.");
      press(editor, "Backspace");
      expect(docText(editor)).toBe("The dog sat on the mat.");
      expect(lineEditState(editor.state).edits).toHaveLength(0);
    });

    it("does nothing without Alt, and does not swallow Alt+Enter when nothing is pending", () => {
      const editor = setup();
      press(editor, "ArrowDown", {});
      press(editor, "Backspace", {});
      expect(lineEditState(editor.state).edits).toHaveLength(2);
      expect(docText(editor)).toBe(TEXT);
      rejectAllLineEdits(editor.view);
      expect(press(editor, "Enter").defaultPrevented).toBe(false);
      expect(press(editor, "ArrowDown").defaultPrevented).toBe(false);
    });
  });

  it("accept applies one edit and keeps the other in place", () => {
    const editor = setup();
    const [first] = lineEditState(editor.state).edits;
    acceptLineEdit(editor.view, first.id);
    expect(docText(editor)).toBe("The dog sat on the mat.");
    const { edits, accepted } = lineEditState(editor.state);
    expect(accepted).toBe(1);
    expect(edits).toHaveLength(1);
    expect(editor.state.doc.textBetween(edits[0].from, edits[0].to)).toBe(" on the mat");
  });

  it("accept ignores stored marks and takes the replaced text's marks", () => {
    const editor = setup();
    const bold = editor.state.schema.marks.bold.create();
    editor.view.dispatch(editor.state.tr.setStoredMarks([bold]));
    const [first] = lineEditState(editor.state).edits;
    acceptLineEdit(editor.view, first.id);
    expect(docText(editor)).toBe("The dog sat on the mat.");
    expect(editor.getJSON().content?.[0].content).toEqual([
      { type: "text", text: "The dog sat on the mat." },
    ]);
  });

  it("accept keeps the marks of the text it replaces", () => {
    const editor = setup();
    // make "cat" italic, then accept the edit over it
    const [first] = lineEditState(editor.state).edits;
    const italic = editor.state.schema.marks.italic.create();
    editor.view.dispatch(editor.state.tr.addMark(first.from, first.to, italic));
    acceptLineEdit(editor.view, lineEditState(editor.state).edits[0].id);
    const marks: string[] = [];
    editor.state.doc.descendants((node) => {
      if (node.isText && node.text?.includes("dog")) marks.push(...node.marks.map((m) => m.type.name));
    });
    expect(marks).toEqual(["italic"]);
    expect(docText(editor)).toBe("The dog sat on the mat.");
  });

  it("reject drops the edit and leaves the text", () => {
    const editor = setup();
    const [first] = lineEditState(editor.state).edits;
    rejectLineEdit(editor.view, first.id);
    expect(docText(editor)).toBe(TEXT);
    expect(lineEditState(editor.state)).toMatchObject({ accepted: 0 });
    expect(lineEditState(editor.state).edits).toHaveLength(1);
  });

  it("reject all clears everything and changes nothing", () => {
    const editor = setup();
    rejectAllLineEdits(editor.view);
    expect(docText(editor)).toBe(TEXT);
    expect(lineEditState(editor.state).edits).toHaveLength(0);
  });

  it("accept all applies every edit as ONE undo step", () => {
    const editor = setup();
    acceptAllLineEdits(editor.view);
    expect(docText(editor)).toBe("The dog sat.");
    expect(lineEditState(editor.state)).toMatchObject({ edits: [], accepted: 2 });
    editor.commands.undo();
    expect(docText(editor)).toBe(TEXT);
  });

  it("typing inside an edit's range drops that edit, not the others", () => {
    const editor = setup();
    const [first, second] = lineEditState(editor.state).edits;
    editor.view.dispatch(editor.state.tr.insertText("X", first.from + 1));
    const { edits } = lineEditState(editor.state);
    expect(edits.map((e) => e.id)).toEqual([second.id]);
    // the survivor moved with the text
    expect(editor.state.doc.textBetween(edits[0].from, edits[0].to)).toBe(" on the mat");
  });

  it("an edit before the others shifts their positions", () => {
    const editor = setup();
    editor.view.dispatch(editor.state.tr.insertText("Well, ", 1));
    const { edits } = lineEditState(editor.state);
    expect(edits).toHaveLength(2);
    expect(editor.state.doc.textBetween(edits[0].from, edits[0].to)).toBe("cat");
  });
});

describe("decision card placement", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("finds the scroll frame lazily and flips wide/narrow from the room right of the column", () => {
    // The plugin view is created before the editor is attached to the page, so
    // the frame must be looked up when the observer fires, not up front.
    const callbacks: Array<() => void> = [];
    const observed: Element[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(cb: () => void) {
          callbacks.push(cb);
        }
        observe(el: Element) {
          observed.push(el);
        }
        disconnect() {}
      },
    );
    const host = document.createElement("div");
    const editor = new Editor({
      element: host,
      extensions: [proseStarterKit(), LineEditSuggestions],
      content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: TEXT }] }] },
    });
    editors.push(editor);
    const frame = document.createElement("div");
    frame.className = "editor-wrap";
    frame.append(host);
    document.body.append(frame);
    Object.defineProperty(frame, "clientWidth", { value: 1000 });
    frame.getBoundingClientRect = () => ({ left: 0 }) as DOMRect;
    let domRight = 700;
    editor.view.dom.getBoundingClientRect = () => ({ right: domRight }) as DOMRect;

    callbacks.forEach((cb) => cb());
    expect(observed).toContain(frame);
    expect(lineEditState(editor.state).wide).toBe(true);
    expect(editor.view.dom.style.getPropertyValue("--line-edit-card-w")).toBe("232px");

    // #2478: a gutter narrower than the full card still gets a margin card, sized to it.
    domRight = 816; // room 184
    callbacks.forEach((cb) => cb());
    expect(lineEditState(editor.state).wide).toBe(true);
    expect(editor.view.dom.style.getPropertyValue("--line-edit-card-w")).toBe("204px");

    domRight = 900; // room 100: below the minimum card
    callbacks.forEach((cb) => cb());
    expect(lineEditState(editor.state).wide).toBe(false);
  });

  it("the margin card's width follows the room, from 180 to 232px (#2478)", () => {
    expect(marginCardWidth(400)).toBe(232);
    expect(marginCardWidth(184)).toBe(204);
    expect(marginCardWidth(160)).toBe(180);
    expect(marginCardWidth(159)).toBeNull();
  });

  describe("revealing the current edit with its card (#2478)", () => {
    // A scroll frame 300px tall at viewport y=100; rects are stubbed (happy-dom
    // has no layout), positions given as the viewport y's the reveal reads.
    function framed(spanTop: number, cardTop: number, cardHeight: number) {
      const frame = document.createElement("div");
      frame.className = "editor-wrap";
      const host = document.createElement("div");
      frame.append(host);
      document.body.append(frame);
      const editor = new Editor({
        element: host,
        extensions: [proseStarterKit(), LineEditSuggestions],
        content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: TEXT }] }] },
      });
      editors.push(editor);
      frame.getBoundingClientRect = () => ({ top: 100, bottom: 400, height: 300 }) as DOMRect;
      const rect = (top: number, height: number) => () => ({ top, bottom: top + height, height }) as DOMRect;
      // Stub before install so the install-time reveal reads these rects.
      const origQuery = editor.view.dom.querySelector.bind(editor.view.dom);
      editor.view.dom.querySelector = ((sel: string) => {
        const el = origQuery(sel) as HTMLElement | null;
        if (!el) return el;
        if (sel.startsWith("[data-line-edit-id")) el.getBoundingClientRect = rect(spanTop, 20);
        if (sel === ".line-edit-card") el.getBoundingClientRect = rect(cardTop, cardHeight);
        return el;
      }) as typeof editor.view.dom.querySelector;
      const { placed } = placeLineEdits(editor.state.doc, 0, editor.state.doc.content.size, [
        { find: "cat", replace: "dog", reason: "livelier" },
      ]);
      installLineEdits(editor.view, placed);
      return frame;
    }

    it("on install, scrolls so a card below the fold comes into view with its edit", () => {
      // Edit at 300, card 360-420: the card overruns the frame bottom (400) by 20.
      const frame = framed(300, 360, 60);
      expect(frame.scrollTop).toBe(20);
    });

    it("when edit and card don't both fit, the edit wins", () => {
      // Edit at 450 (below the fold); card 700-760: together 310px > the 300px frame.
      const frame = framed(450, 700, 60);
      expect(frame.scrollTop).toBe(70); // edit bottom 470 brought to the frame bottom 400
    });
  });

  it("an edit inside a table cell gets the block card even when there is margin room", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const cell = (text: string) => ({
      type: "tableCell",
      content: [{ type: "paragraph", content: [{ type: "text", text }] }],
    });
    const editor = new Editor({
      element: host,
      extensions: [proseStarterKit(), ...tableExtensions, LineEditSuggestions],
      content: {
        type: "doc",
        content: [{ type: "table", content: [{ type: "tableRow", content: [cell(TEXT), cell("x")] }] }],
      },
    });
    editors.push(editor);
    const { placed } = placeLineEdits(editor.state.doc, 0, editor.state.doc.content.size, [
      { find: "cat", replace: "dog", reason: "livelier" },
    ]);
    installLineEdits(editor.view, placed);
    setLineEditCardWide(editor.view, true);
    const card = editor.view.dom.querySelector("[data-testid=line-edit-card]");
    expect(card).not.toBeNull();
    expect(card!.classList.contains("line-edit-card-wide")).toBe(false);
    expect(card!.closest("td")).not.toBeNull();
  });
});
