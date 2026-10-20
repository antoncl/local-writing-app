// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { proseStarterKit } from "@/lib/editor-core/proseStarterKit";
import { ReadAloudHighlight } from "@/lib/editor-core/readAloudHighlight";
import { FLAG_NOTE, LEAD_IN_TEXT, ReadAloudController, projectSpeechLang, voiceForLang, type ReadAloudUtterance, type SpeechEngine } from "./readAloud.svelte";

const VOICES = [
  { name: "Ada", lang: "en-GB", voiceURI: "voice-ada" },
  { name: "Bo", lang: "en-US", voiceURI: "voice-bo" },
];

/** A fake engine that behaves like the real one (#2574): it keeps a queue,
 *  plays one utterance at a time, fires `start` as each begins and `end` on
 *  finish(), and errors every queued utterance on cancel(). The silent lead-in
 *  (volume 0) plays through at once and is recorded in `leadIns`, so `spoken`
 *  is the sentences actually started, in order. */
function makeHarness(stored: Record<string, string> = {}) {
  const spoken: ReadAloudUtterance[] = [];
  const leadIns: ReadAloudUtterance[] = [];
  const queued: ReadAloudUtterance[] = [];
  let current: ReadAloudUtterance | null = null;
  const startNext = (): void => {
    current = queued.shift() ?? null;
    if (!current) return;
    if (current.volume === 0) {
      leadIns.push(current);
      const lead = current;
      current = null;
      lead.onstart?.();
      lead.onend?.();
      startNext();
      return;
    }
    spoken.push(current);
    current.onstart?.();
  };
  const engine: SpeechEngine = {
    speak: vi.fn((u: never) => {
      queued.push(u as ReadAloudUtterance);
      if (!current) startNext();
    }),
    cancel: vi.fn(() => {
      const dropped = [...(current ? [current] : []), ...queued.splice(0)];
      current = null;
      for (const u of dropped) u.onerror?.({ error: "interrupted" });
    }),
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
    makeUtterance: (text) => ({ text, rate: 1, voice: null, lang: "", volume: 1, onstart: null, onend: null, onerror: null }),
    storage,
  });
  /** The utterance being spoken ends; the engine starts the next queued one. */
  const finish = () => {
    const done = current;
    current = null;
    done?.onend?.();
    if (!current) startNext();
  };
  return { controller, engine, spoken, leadIns, queued, store, finish };
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

  it("the flag's own mark does not pause the reading, but a user edit does (#2572)", () => {
    const { controller, engine } = makeHarness();
    const editor = makeEditor();
    const markRange = vi.fn((from: number, to: number) => {
      editor.view.dispatch(editor.state.tr.addMark(from, to, editor.state.schema.marks.bold.create()));
      return "todo_1";
    });
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange });
    controller.flag();
    expect(controller.status).toBe("playing");
    expect(controller.edited).toBe(false);
    editor.commands.insertContentAt(1, "x");
    expect(controller.status).toBe("paused"); // paused, not stopped: the bar stays
    expect(controller.edited).toBe(true);
    expect(controller.docKey).toBe("s1");
    expect(engine.cancel).toHaveBeenCalled(); // the stale sentence is silenced
    controller.flag(); // positions are stale: no flag until reading resumes
    expect(markRange).toHaveBeenCalledTimes(1);
  });

  it("resuming after an edit reads on from the cursor's sentence, as the text now stands", () => {
    const { controller, spoken } = makeHarness();
    const editor = makeEditor("<p>One. Two.</p><p>Three. Four.</p>");
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    // Edit the second paragraph, leaving the cursor inside "Three."
    editor.commands.setTextSelection(editor.state.doc.content.size - 9); // inside "Three."
    editor.commands.insertContent("X");
    expect(controller.edited).toBe(true);
    controller.resume();
    expect(controller.status).toBe("playing");
    expect(controller.edited).toBe(false);
    expect(spoken.at(-1)?.text).toBe("ThreXe."); // the sentence the cursor is in, whole, as edited
    expect(controller.total).toBe(2); // that sentence and "Four." — not the start of the reading
  });

  it("From cursor (Alt+Shift+R) restarts at the cursor at any time", () => {
    const { controller, spoken } = makeHarness();
    const editor = makeEditor("<p>One. Two.</p><p>Three.</p>");
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    editor.commands.setTextSelection(editor.state.doc.content.size - 3); // inside "Three."
    const event = new KeyboardEvent("keydown", { key: "R", code: "KeyR", altKey: true, shiftKey: true });
    expect(controller.handleKey(editor.view, event)).toBe(true);
    expect(spoken.at(-1)?.text).toBe("Three.");
    expect(controller.total).toBe(1);
  });

  it("a whole-document replace (a node switch) still stops the reading", () => {
    const { controller } = makeHarness();
    const editor = makeEditor();
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    editor.commands.setContent("<p>Another document.</p>");
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

describe("queued speaking (#2574: no clipped first words)", () => {
  const range = (editor: Editor) => ({ from: 0, to: editor.state.doc.content.size });

  it("hands the engine a silent lead-in and every remaining sentence up front", () => {
    const { controller, engine, leadIns, queued, spoken } = makeHarness();
    const editor = makeEditor(); // One. Two. | Three.
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    expect(engine.speak).toHaveBeenCalledTimes(4); // lead-in + 3 sentences, all at once
    expect(leadIns).toHaveLength(1);
    expect(leadIns[0].text).toBe(LEAD_IN_TEXT);
    expect(leadIns[0].volume).toBe(0);
    expect(spoken.map((u) => u.text)).toEqual(["One."]); // playing
    expect(queued.map((u) => u.text)).toEqual(["Two.", "Three."]); // already waiting: no gap
    expect(spoken[0].volume).toBe(1);
  });

  it("a speed change re-queues from the current sentence; while paused, on resume", () => {
    const { controller, spoken, finish, leadIns } = makeHarness();
    const editor = makeEditor();
    controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    finish(); // now on "Two."
    controller.setRate(1.5);
    expect(spoken.at(-1)?.text).toBe("Two."); // restarted once, at the new speed
    expect(spoken.at(-1)?.rate).toBe(1.5);
    expect(leadIns).toHaveLength(2); // a fresh queue gets its lead-in too
    controller.pause();
    controller.setRate(0.8);
    expect(spoken.at(-1)?.rate).toBe(1.5); // nothing re-queued while paused
    controller.resume();
    expect(spoken.at(-1)?.text).toBe("Two.");
    expect(spoken.at(-1)?.rate).toBe(0.8);
  });

  it("advances on `end` for a voice that never reports `start`", () => {
    const h = makeHarness();
    const editor = makeEditor();
    h.controller.start({ editor, docKey: "s1", ...range(editor), canFlag: true, markRange: vi.fn() });
    for (const u of [...h.queued]) u.onstart = null; // a voice with no start events
    h.finish(); // "One." ends; "Two." plays silently-reporting
    expect(h.controller.index).toBe(1);
    expect(highlighted(editor)).toBe("Two.");
  });
});
