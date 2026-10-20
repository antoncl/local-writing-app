// Read aloud (#2570): the browser's speech synthesis reads a passage of the open
// document sentence by sentence while the editor highlights the one being
// spoken. Speech is a single global resource, so this is one app-wide
// controller: starting a reading anywhere stops the one before it.
//
// Rate and voice changes apply from the NEXT sentence (the one being spoken
// finishes as it started) - restarting mid-sentence would repeat words.
import type { Editor } from "@tiptap/core";
import type { EditorView } from "@tiptap/pm/view";
import { collectSentences, type ReadAloudSentence } from "@/lib/editor-core/readAloudText";
import { setReadAloudHighlight, type ReadAloudInput } from "@/lib/editor-core/readAloudHighlight";

export const READ_ALOUD_RATES = [0.8, 1, 1.2, 1.5] as const;
export const FLAG_NOTE = "Flagged while reading aloud";
const RATE_KEY = "lwa.readAloud.rate";
const VOICE_KEY = "lwa.readAloud.voice";

type PrefStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/** The slice of an utterance the controller sets (SpeechSynthesisUtterance fits). */
export interface ReadAloudUtterance {
  text: string;
  rate: number;
  voice: unknown;
  lang: string;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
}

/** The slice of `window.speechSynthesis` the controller uses. */
export interface SpeechEngine {
  speak(utterance: never): void;
  cancel(): void;
  pause(): void;
  resume(): void;
  getVoices(): Array<{ name: string; lang: string; voiceURI: string }>;
  addEventListener?(type: "voiceschanged", listener: () => void): void;
  removeEventListener?(type: "voiceschanged", listener: () => void): void;
}

export interface ReadAloudDeps {
  engine: SpeechEngine | null;
  makeUtterance: (text: string) => ReadAloudUtterance;
  storage: PrefStorage | null;
}

export type ReadAloudStart = {
  editor: Editor;
  /** The document the reading belongs to (the footer shows the bar for it). */
  docKey: string | null;
  from: number;
  to: number;
  /** Flags are scene TODOs: only a scene can take one. */
  canFlag: boolean;
  markRange: (from: number, to: number, note: string) => string | null;
};

function defaultDeps(): ReadAloudDeps {
  const hasSpeech = typeof window !== "undefined" && "speechSynthesis" in window;
  let storage: PrefStorage | null = null;
  try {
    storage = typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    storage = null; // storage access can throw (privacy modes) - treat as absent.
  }
  return {
    engine: hasSpeech ? (window.speechSynthesis as unknown as SpeechEngine) : null,
    makeUtterance: (text) => new SpeechSynthesisUtterance(text) as unknown as ReadAloudUtterance,
    storage,
  };
}

/** The BCP 47 tag a reading speaks in, from the open project's resolved
 *  Spelling (`en_US` → `en-US`, the more specific) or Language (`en`); null when
 *  neither is set. Without it the browser falls back to the system language,
 *  which reads English prose in, say, a Danish voice. */
export function projectSpeechLang(metadata: Record<string, unknown> | null | undefined): string | null {
  const spelling = metadata?.spelling;
  if (typeof spelling === "string" && /^[a-z]{2,3}[_-][A-Za-z]{2}$/.test(spelling)) return spelling.replace("_", "-");
  const language = metadata?.language;
  if (typeof language === "string" && /^[a-z]{2,3}$/.test(language)) return language;
  return null;
}

/** The first of `voices` that speaks `lang`: an exact tag match (`en-US`), else
 *  the same language (`en-GB` for `en-US`, any `en-*` for `en`); null if none. */
export function voiceForLang<V extends { lang: string }>(voices: V[], lang: string | null): V | null {
  if (!lang) return null;
  const norm = (tag: string) => tag.replace("_", "-").toLowerCase();
  const want = norm(lang);
  const primary = want.split("-")[0];
  return (
    voices.find((v) => norm(v.lang) === want) ??
    voices.find((v) => norm(v.lang).split("-")[0] === primary) ??
    null
  );
}

/** Whether this browser can speak at all - the entries are not offered without it. */
export function speechAvailable(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export class ReadAloudController implements ReadAloudInput {
  status = $state<"idle" | "playing" | "paused">("idle");
  docKey = $state<string | null>(null);
  index = $state(0);
  total = $state(0);
  canFlag = $state(false);
  flaggedIndexes = $state<number[]>([]);
  rate = $state(1);
  voiceURI = $state("");
  voices = $state<Array<{ name: string; lang: string; voiceURI: string }>>([]);
  lastFlagAt = $state(0);
  /** The open project's language as a BCP 47 tag (App sets it), or null. */
  lang = $state<string | null>(null);

  #deps: ReadAloudDeps;
  #editor: Editor | null = null;
  #sentences: ReadAloudSentence[] = [];
  #markRange: ReadAloudStart["markRange"] | null = null;
  #generation = 0; // bumped whenever speech is cancelled, so a stale `end` is ignored
  #suppress = false; // the flag's own mark must not stop the reading
  #current: ReadAloudUtterance | null = null; // held: some browsers drop a speaking utterance's events if it is collected
  #onTransaction = ({ transaction }: { transaction: { docChanged: boolean } }) => {
    if (transaction.docChanged && !this.#suppress) this.stop();
  };
  #onDestroy = () => this.stop();
  #onVoices = () => this.#refreshVoices();

  constructor(deps: ReadAloudDeps = defaultDeps()) {
    this.#deps = deps;
    this.#loadPrefs();
    this.#refreshVoices();
    deps.engine?.addEventListener?.("voiceschanged", this.#onVoices);
  }

  /** Whether `editor` is the one being read. */
  isReading(editor: Editor): boolean {
    return this.status !== "idle" && this.#editor === editor;
  }

  /** Start reading `from`..`to` of `editor`, stopping any reading in progress.
   *  False when there is nothing to speak (or no speech engine). */
  start(opts: ReadAloudStart): boolean {
    this.stop();
    const engine = this.#deps.engine;
    const sentences = collectSentences(opts.editor.state.doc, opts.from, opts.to);
    if (!engine || sentences.length === 0) return false;
    this.#editor = opts.editor;
    this.#sentences = sentences;
    this.#markRange = opts.markRange;
    this.docKey = opts.docKey;
    this.canFlag = opts.canFlag;
    this.total = sentences.length;
    this.index = 0;
    this.flaggedIndexes = [];
    this.status = "playing";
    opts.editor.on("transaction", this.#onTransaction);
    opts.editor.on("destroy", this.#onDestroy);
    this.#speakCurrent();
    return true;
  }

  pause(): void {
    if (this.status !== "playing") return;
    this.#deps.engine?.pause();
    this.status = "paused";
  }

  resume(): void {
    if (this.status !== "paused") return;
    this.#deps.engine?.resume();
    this.status = "playing";
  }

  togglePause(): void {
    if (this.status === "playing") this.pause();
    else this.resume();
  }

  stop(): void {
    if (this.status === "idle") return;
    this.#generation++;
    // The engine's pause is global and outlives cancel(): stopped while paused,
    // Chrome would swallow the next reading's speech until something resumed it.
    if (this.status === "paused") this.#deps.engine?.resume();
    this.#deps.engine?.cancel();
    const editor = this.#editor;
    if (editor) {
      editor.off("transaction", this.#onTransaction);
      editor.off("destroy", this.#onDestroy);
      if (!editor.isDestroyed) setReadAloudHighlight(editor.view, null);
    }
    this.#editor = null;
    this.#current = null;
    this.#sentences = [];
    this.#markRange = null;
    this.status = "idle";
    this.docKey = null;
    this.index = 0;
    this.total = 0;
    this.canFlag = false;
    this.flaggedIndexes = [];
  }

  /** Mark the sentence being read as a scene TODO; reading goes on. */
  flag(): void {
    const sentence = this.#sentences[this.index];
    if (this.status === "idle" || !this.canFlag || !sentence || !this.#markRange) return;
    if (this.flaggedIndexes.includes(this.index)) return;
    this.#suppress = true;
    let id: string | null;
    try {
      id = this.#markRange(sentence.from, sentence.to, FLAG_NOTE);
    } finally {
      this.#suppress = false;
    }
    if (!id) return;
    this.flaggedIndexes = [...this.flaggedIndexes, this.index];
    this.lastFlagAt = Date.now();
  }

  /** Continue from the sentence containing doc position `pos` (ignored when none does). */
  jumpToPos(pos: number): void {
    if (this.status === "idle") return;
    const target = this.#sentences.findIndex((s) => pos >= s.from && pos <= s.to);
    if (target < 0) return;
    this.#generation++;
    this.#deps.engine?.cancel();
    if (this.status === "paused") {
      this.#deps.engine?.resume();
      this.status = "playing";
    }
    this.index = target;
    this.#speakCurrent();
  }

  setRate(rate: number): void {
    if (!READ_ALOUD_RATES.includes(rate as (typeof READ_ALOUD_RATES)[number])) return;
    this.rate = rate;
    this.#savePref(RATE_KEY, rate === 1 ? null : String(rate));
  }

  /** The open project's resolved fields (ProjectInfo.metadata): its Spelling /
   *  Language decide the language a reading speaks in by default. */
  setProjectLanguage(metadata: Record<string, unknown> | null | undefined): void {
    this.lang = projectSpeechLang(metadata);
  }

  setVoice(uri: string): void {
    this.voiceURI = uri;
    this.#savePref(VOICE_KEY, uri || null);
  }

  // The plugin's seams (ReadAloudInput) - both act only on the view being read.
  handleKey(view: EditorView, event: KeyboardEvent): boolean {
    if (this.status === "idle" || this.#editor?.view !== view) return false;
    if (event.key === "Escape") {
      this.stop();
      return true;
    }
    if (!event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey) return false;
    // The key's position, not its character: Alt+Shift turns letters into other characters on macOS.
    if (event.code === "KeyP") {
      this.togglePause();
      return true;
    }
    if (event.code === "KeyF" && this.canFlag) {
      this.flag();
      return true;
    }
    return false;
  }

  handleClick(view: EditorView, pos: number): void {
    if (this.status !== "idle" && this.#editor?.view === view) this.jumpToPos(pos);
  }

  #speakCurrent(): void {
    const editor = this.#editor;
    const engine = this.#deps.engine;
    const sentence = this.#sentences[this.index];
    if (!editor || !engine || !sentence) return;
    const generation = this.#generation;
    const utterance = this.#deps.makeUtterance(sentence.text);
    utterance.rate = this.rate;
    // A voice the writer picked wins; otherwise one that speaks the project's
    // language, not whatever the system language's default happens to be.
    utterance.voice = this.voiceURI
      ? this.#voiceObject(this.voiceURI)
      : voiceForLang(this.#deps.engine?.getVoices() ?? [], this.lang);
    if (this.lang) utterance.lang = this.lang;
    utterance.onend = () => {
      if (generation !== this.#generation) return;
      if (this.index + 1 < this.#sentences.length) {
        this.index++;
        this.#speakCurrent();
      } else {
        this.stop();
      }
    };
    // A cancel() ends the utterance with an error too; only a failure of the
    // utterance still being read stops the reading.
    utterance.onerror = () => {
      if (generation === this.#generation) this.stop();
    };
    this.#current = utterance;
    setReadAloudHighlight(editor.view, { from: sentence.from, to: sentence.to });
    this.#scrollTo(editor, sentence.from);
    engine.speak(utterance as never);
  }

  #scrollTo(editor: Editor, pos: number): void {
    try {
      const { node } = editor.view.domAtPos(pos);
      const element = node.nodeType === 3 ? node.parentElement : (node as HTMLElement);
      element?.scrollIntoView?.({ block: "nearest" });
    } catch {
      // A position the view can't resolve: the highlight is still shown.
    }
  }

  #voiceObject(uri: string): unknown {
    return (this.#deps.engine?.getVoices() ?? []).find((v) => v.voiceURI === uri) ?? null;
  }

  #refreshVoices(): void {
    this.voices = [...(this.#deps.engine?.getVoices() ?? [])];
  }

  #loadPrefs(): void {
    try {
      const rate = Number(this.#deps.storage?.getItem(RATE_KEY));
      if (READ_ALOUD_RATES.includes(rate as (typeof READ_ALOUD_RATES)[number])) this.rate = rate;
      this.voiceURI = this.#deps.storage?.getItem(VOICE_KEY) ?? "";
    } catch {
      // Storage unavailable: the defaults stand.
    }
  }

  #savePref(key: string, value: string | null): void {
    try {
      if (value === null) this.#deps.storage?.removeItem(key);
      else this.#deps.storage?.setItem(key, value);
    } catch {
      // Storage disabled / quota - the pref just won't persist; not fatal.
    }
  }
}

export const readAloud = new ReadAloudController();
