// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { proseStarterKit } from "@/lib/editor-core/proseStarterKit";
import { ReadAloudHighlight } from "@/lib/editor-core/readAloudHighlight";
import { FLAG_NOTE, ReadAloudController, projectSpeechLang, voiceForLang, type ReadAloudUtterance, type SpeechEngine } from "./readAloud.svelte";

const VOICES = [
  { name: "Ada", lang: "en-GB", voiceURI: "voice-ada" },
  { name: "Bo", lang: "en-US", voiceURI: "voice-bo" },
];

function makeHarness(stored: Record<string, string> = {}) {
  const spoken: ReadAloudUtterance[] = [];
  const engine: SpeechEngine = {
    speak: vi.fn((u: never) => void spoken.push(u as ReadAloudUtterance)),
    cancel: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    getVoices: () => VOICES,
  };
  const store = { ...stored };
  const storage = {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => void (store[k] = v),
    removeItem: (k: string) => void delete store[k],
  };
  const controller = new ReadAloudController({
    engine,
    makeUtterance: (text) => ({ text, rate: 1, voice: null, lang: "", onend: null, onerror: null }),
    storage,
  });
  const finish = () => spoken[spoken.length - 1].onend?.();
  return { controller, engine, spoken, store, finish };
}

let editors: Editor[] = [];
function makeEditor(html = "<p>One. Two.</p><p>Three.</p>") {
  const holder = document.createElement("div");
  document.body.appendChild(holder);
  const editor = new Editor({ element: holder, extensions: [proseStarterKit(), ReadAloudHighlight], content: html });
  editors.push(editor);
  return editor;
}
const highlighted = (editor: Editor) => editor.view.dom.querySelector(".read-aloud-current")?.textContent ?? null;

beforeEach(() => {
  editors = [];
});
afterEach(() => {
  for (const e of editors) e.destroy();
});

describe("ReadAloudController", () => {
  const range = (editor: Editor) => ({ from: 0, to: editor.state.doc.content.size });

  it("speaks sentence by sentence, highlighting each, and stops after the last", () => {
    const { controller, spoken, finish } = makeHarness();
    const editor = makeEditor();
    expect(controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() })).toBe(true);
    expect(spoken.map((u) => u.text)).toEqual(["One."]);
    expect(controller.status).toBe("playing");
    expect(controller.total).toBe(3);
    expect(highlighted(editor)).toBe("One.");
    finish();
    expect(spoken.map((u) => u.text)).toEqual(["One.", "Two."]);
    expect(controller.index).toBe(1);
    expect(highlighted(editor)).toBe("Two.");
    finish();
    finish();
    expect(controller.status).toBe("idle");
    expect(highlighted(editor)).toBeNull();
    expect(controller.docKey).toBeNull();
  });

  it("does not start when there is nothing to read", () => {
    const { controller, spoken } = makeHarness();
    const editor = makeEditor("<p></p>");
    expect(controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() })).toBe(false);
    expect(spoken).toHaveLength(0);
  });

  it("pause and resume go to the engine; stop cancels and clears", () => {
    const { controller, engine } = makeHarness();
    const editor = makeEditor();
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    controller.togglePause();
    expect(engine.pause).toHaveBeenCalled();
    expect(controller.status).toBe("paused");
    controller.togglePause();
    expect(engine.resume).toHaveBeenCalled();
    expect(controller.status).toBe("playing");
    controller.stop();
    expect(engine.cancel).toHaveBeenCalled();
    expect(controller.status).toBe("idle");
    expect(highlighted(editor)).toBeNull();
  });

  it("stopping while paused resumes the engine first, so the next reading is heard", () => {
    // The engine's pause is global and survives cancel(); Chrome would swallow
    // the next reading's speech if a paused reading were stopped without a resume.
    const { controller, engine } = makeHarness();
    const editor = makeEditor();
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    controller.pause();
    vi.mocked(engine.resume).mockClear();
    controller.stop();
    expect(engine.resume).toHaveBeenCalledTimes(1);
    const resumeOrder = vi.mocked(engine.resume).mock.invocationCallOrder[0];
    const cancelOrder = vi.mocked(engine.cancel).mock.invocationCallOrder.at(-1)!;
    expect(resumeOrder).toBeLessThan(cancelOrder);
  });

  it("a cancelled utterance's late end does not advance the reading", () => {
    const { controller, spoken } = makeHarness();
    const editor = makeEditor();
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    const first = spoken[0];
    controller.stop();
    first.onend?.();
    expect(spoken).toHaveLength(1);
    expect(controller.status).toBe("idle");
  });

  it("flag marks the current sentence once and keeps reading", () => {
    const { controller, spoken, finish } = makeHarness();
    const editor = makeEditor();
    const markRange = vi.fn(() => "todo_1");
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange });
    finish();
    controller.flag();
    controller.flag();
    expect(markRange).toHaveBeenCalledTimes(1);
    const [from, to, note] = markRange.mock.calls[0] as unknown as [number, number, string];
    expect(editor.state.doc.textBetween(from, to)).toBe("Two.");
    expect(note).toBe(FLAG_NOTE);
    expect(controller.flaggedIndexes).toEqual([1]);
    expect(controller.status).toBe("playing");
    expect(spoken).toHaveLength(2);
  });

  it("flag does nothing when flags are unavailable", () => {
    const { controller } = makeHarness();
    const editor = makeEditor();
    const markRange = vi.fn(() => "todo_1");
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: false, markRange });
    controller.flag();
    expect(markRange).not.toHaveBeenCalled();
  });

  it("the flag's own mark does not stop the reading, but a user edit does", () => {
    const { controller } = makeHarness();
    const editor = makeEditor();
    const markRange = vi.fn((from: number, to: number) => {
      editor.view.dispatch(editor.state.tr.addMark(from, to, editor.state.schema.marks.bold.create()));
      return "todo_1";
    });
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange });
    controller.flag();
    expect(controller.status).toBe("playing");
    editor.commands.insertContentAt(1, "x");
    expect(controller.status).toBe("idle");
  });

  it("stops when the editor is destroyed", () => {
    const { controller } = makeHarness();
    const editor = makeEditor();
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    editor.destroy();
    expect(controller.status).toBe("idle");
  });

  it("a second start stops the first", () => {
    const { controller, engine } = makeHarness();
    const a = makeEditor();
    const b = makeEditor("<p>Other.</p>");
    controller.start({ editor: a, docKey: "a", ...range(a), canFlag: true, markRange: vi.fn() });
    controller.start({ editor: b, docKey: "b", ...range(b), canFlag: true, markRange: vi.fn() });
    expect(engine.cancel).toHaveBeenCalled();
    expect(controller.docKey).toBe("b");
    expect(controller.isReading(a)).toBe(false);
    expect(controller.isReading(b)).toBe(true);
    expect(highlighted(a)).toBeNull();
  });

  it("jumps to the sentence under a click and ignores a click outside any", () => {
    const { controller, engine, spoken } = makeHarness();
    const editor = makeEditor();
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    controller.handleClick(editor.view, 0);
    expect(spoken).toHaveLength(1);
    // "Three." is in the second paragraph: 1 + 10 + 1 chars in, so position ~ 14.
    controller.handleClick(editor.view, 14);
    expect(engine.cancel).toHaveBeenCalled();
    expect(spoken.map((u) => u.text)).toEqual(["One.", "Three."]);
    expect(controller.index).toBe(2);
  });

  it("keys act only while reading this editor", () => {
    const { controller } = makeHarness();
    const editor = makeEditor();
    const key = (init: KeyboardEventInit) => new KeyboardEvent("keydown", init);
    expect(controller.handleKey(editor.view, key({ key: "Escape" }))).toBe(false);
    const markRange = vi.fn(() => "todo_1");
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange });
    expect(controller.handleKey(editor.view, key({ code: "KeyP", altKey: true, shiftKey: true }))).toBe(true);
    expect(controller.status).toBe("paused");
    expect(controller.handleKey(editor.view, key({ code: "KeyF", altKey: true, shiftKey: true }))).toBe(true);
    expect(markRange).toHaveBeenCalledTimes(1);
    expect(controller.handleKey(editor.view, key({ key: "a" }))).toBe(false);
    expect(controller.handleKey(editor.view, key({ key: "Escape" }))).toBe(true);
    expect(controller.status).toBe("idle");
  });

  it("persists rate and voice, loads them, and applies them to the next utterance", () => {
    const h = makeHarness();
    h.controller.setRate(1.5);
    h.controller.setVoice("voice-bo");
    expect(h.store["lwa.readAloud.rate"]).toBe("1.5");
    expect(h.store["lwa.readAloud.voice"]).toBe("voice-bo");
    const reloaded = makeHarness(h.store);
    expect(reloaded.controller.rate).toBe(1.5);
    expect(reloaded.controller.voiceURI).toBe("voice-bo");
    const editor = makeEditor();
    reloaded.controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    expect(reloaded.spoken[0].rate).toBe(1.5);
    expect(reloaded.spoken[0].voice).toEqual(VOICES[1]);
    reloaded.controller.setRate(0.8);
    reloaded.finish();
    expect(reloaded.spoken[1].rate).toBe(0.8);
  });
});

describe("project language (a Danish system must not read English prose in a Danish voice)", () => {
  it("takes the tag from Spelling first, then Language", () => {
    expect(projectSpeechLang({ language: "en", spelling: "en_US" })).toBe("en-US");
    expect(projectSpeechLang({ language: "en" })).toBe("en");
    expect(projectSpeechLang({ language: "da" })).toBe("da");
    expect(projectSpeechLang({})).toBeNull();
    expect(projectSpeechLang(null)).toBeNull();
  });

  it("picks an exact voice, else the same language, else none", () => {
    const voices = [
      { name: "Helle", lang: "da-DK" },
      { name: "Ada", lang: "en-GB" },
      { name: "Bo", lang: "en_US" },
    ];
    expect(voiceForLang(voices, "en-US")?.name).toBe("Bo");
    expect(voiceForLang(voices, "en-AU")?.name).toBe("Ada");
    expect(voiceForLang(voices, "en")?.name).toBe("Ada");
    expect(voiceForLang(voices, "fr")).toBeNull();
    expect(voiceForLang(voices, null)).toBeNull();
  });

  it("speaks in the project's language with a matching voice unless one was picked", () => {
    const h = makeHarness();
    h.controller.setProjectLanguage({ language: "en", spelling: "en_US" });
    const editor = makeEditor();
    h.controller.start({ editor, docKey: "s1", from: 0, to: editor.state.doc.content.size, canFlag: true, markRange: vi.fn() });
    expect(h.spoken[0].lang).toBe("en-US");
    expect(h.spoken[0].voice).toEqual(VOICES[1]); // Bo, en-US — not Ada, who comes first
    h.controller.setVoice("voice-ada");
    h.finish();
    expect(h.spoken[1].voice).toEqual(VOICES[0]); // the picked voice wins from the next sentence
  });
});
