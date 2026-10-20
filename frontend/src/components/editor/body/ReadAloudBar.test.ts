// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { render, screen, fireEvent } from "@/lib/test/component";
import { proseStarterKit } from "@/lib/editor-core/proseStarterKit";
import { ReadAloudHighlight } from "@/lib/editor-core/readAloudHighlight";
import { readAloud } from "@/lib/stores/readAloud.svelte";
import ReadAloudBar from "./ReadAloudBar.svelte";

// The shared controller, driven by a silent engine (happy-dom has no speech).
vi.mock("@/lib/stores/readAloud.svelte", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/stores/readAloud.svelte")>();
  const engine = {
    speak: vi.fn(),
    cancel: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    getVoices: () => [{ name: "Ada", lang: "en-GB", voiceURI: "voice-ada" }],
  };
  const makeUtterance = (text: string) => ({ text, rate: 1, voice: null, onend: null, onerror: null });
  return { ...real, readAloud: new real.ReadAloudController({ engine, makeUtterance, storage: null }) };
});

let editor: Editor | null = null;

function begin(canFlag: boolean) {
  editor = new Editor({ element: document.createElement("div"), extensions: [proseStarterKit(), ReadAloudHighlight], content: "<p>One. Two.</p>" });
  const markRange = vi.fn(() => "todo_1");
  readAloud.start({ editor, docKey: "s1", from: 0, to: editor.state.doc.content.size, canFlag, markRange });
  return markRange;
}

afterEach(() => {
  readAloud.stop();
  editor?.destroy();
  editor = null;
});

describe("ReadAloudBar", () => {
  it("shows progress and routes pause and stop", async () => {
    begin(true);
    render(ReadAloudBar);
    expect(screen.getByTestId("read-aloud-status").textContent).toContain("Reading aloud · sentence 1 of 2");
    await fireEvent.click(screen.getByTestId("read-aloud-toggle"));
    expect(readAloud.status).toBe("paused");
    expect(screen.getByTestId("read-aloud-status").textContent).toContain("Paused · sentence 1 of 2");
    await fireEvent.click(screen.getByTestId("read-aloud-stop"));
    expect(readAloud.status).toBe("idle");
  });

  it("flags the current sentence once, with brief feedback", async () => {
    const markRange = begin(true);
    render(ReadAloudBar);
    const flag = screen.getByTestId("read-aloud-flag") as HTMLButtonElement;
    await fireEvent.click(flag);
    expect(markRange).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId("read-aloud-flagged")).toBeTruthy();
    expect(flag.disabled).toBe(true);
    expect(readAloud.status).toBe("playing");
  });

  it("disables Flag outside a scene, saying why", () => {
    begin(false);
    render(ReadAloudBar);
    const flag = screen.getByTestId("read-aloud-flag") as HTMLButtonElement;
    expect(flag.disabled).toBe(true);
    expect(flag.title).toBe("Flags are scene TODOs — open a scene to flag");
  });

  it("offers speeds and voices and stores the choice", async () => {
    begin(true);
    render(ReadAloudBar);
    const rate = screen.getByTestId("read-aloud-rate") as HTMLSelectElement;
    expect([...rate.options].map((o) => o.textContent)).toEqual(["0.8×", "1×", "1.2×", "1.5×"]);
    await fireEvent.change(rate, { target: { value: "1.5" } });
    expect(readAloud.rate).toBe(1.5);
    const voice = screen.getByTestId("read-aloud-voice") as HTMLSelectElement;
    expect([...voice.options].map((o) => o.textContent)).toEqual(["System default", "Ada (en-GB)"]);
    await fireEvent.change(voice, { target: { value: "voice-ada" } });
    expect(readAloud.voiceURI).toBe("voice-ada");
  });
});
