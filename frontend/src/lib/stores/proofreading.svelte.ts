// Proofreading (ADR-0102 §1): the lens. One app-wide switch, off at every start
// and never persisted: a revision pass is a sitting, and a lens that came back
// on by itself would underline the next first draft.
//
// Switching it on the first time loads the engine (a dynamic import, so the
// binary never loads before the writer asks for it). Switching it off keeps the
// engine for the session, so the next switch-on is immediate.
//
// Each prose editor's highlight plugin asks this controller to lint a block's
// text and subscribes to hear when its findings may have changed: the lens went
// on or off, the engine became ready, or the words changed. Results are cached
// by text and cleared whenever the words change.
import { untrack } from "svelte";
import { loreEntriesStore } from "@/lib/stores/lore";
import { autoDictionary } from "@/lib/proofread/dictionary";
import type { Finding, ProofreadEngine } from "@/lib/proofread/findings";
import type { LoreEntrySummary } from "@/lib/types";

const CACHE_LIMIT = 4000;

export type LensStatus ="off" | "loading" | "ready" | "error";

/** What the highlight extension needs of the lens. */
export interface ProofreadLens {
  readonly active: boolean;
  /** The findings for `text` if already linted, else undefined. */
  cached(text: string): Finding[] | undefined;
  /** Lint `text` (from the cache when it can). Rejects only on engine failure. */
  lint(text: string): Promise<Finding[]>;
  /** Hear when findings may have changed; returns the unsubscribe. */
  subscribe(listener: () => void): () => void;
}

export interface ProofreadingDeps {
  loadEngine: () => Promise<ProofreadEngine>;
  /** Subscribe to the lore roster; returns the unsubscribe. */
  subscribeLore: (run: (entries: LoreEntrySummary[]) => void) => () => void;
  /** How long the engine may take to start before the lens reports an error. */
  startTimeoutMs: number;
}

const defaultDeps: ProofreadingDeps = {
  loadEngine: async () => (await import("@/lib/proofread/harperEngine")).createHarperEngine(),
  subscribeLore: (run) => loreEntriesStore.subscribe(run),
  // A binary that fails to load inside Harper's worker never rejects its setup
  // promise: without a limit the lens would say "loading" forever.
  startTimeoutMs: 60_000,
};

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`the checker did not start within ${ms / 1000} s`)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}

export class ProofreadingController implements ProofreadLens {
  on = $state(false);
  status = $state<LensStatus>("off");
  error = $state<string | null>(null);

  private engine: ProofreadEngine | null = null;
  private loading: Promise<void> | null = null;
  private listeners = new Set<() => void>();
  private cache = new Map<string, Finding[]>();
  private pending = new Map<string, Promise<Finding[]>>();
  private lore: LoreEntrySummary[] = [];
  private stopLore: (() => void) | null = null;
  /** As-of-scene names per editor (a scene's mid-story renames, #61). */
  private viewNames = new Map<string, string[]>();
  /** The word list the engine was last given, to skip a needless reload. */
  private loadedWords: string | null = null;
  /** Bumped by every word reload, so a lint that started before it is dropped. */
  private generation = 0;
  /** The latest word load. Lints wait on it, so none runs against a half-loaded
   *  dictionary (setting words is two engine calls). */
  private wordsLoad: Promise<void> = Promise.resolve();
  /** The load of `loadedWords` itself, failure included — what a second
   *  caller asking for the same words waits on. */
  private currentLoad: Promise<void> = Promise.resolve();

  constructor(private deps: ProofreadingDeps = defaultDeps) {}

  get active(): boolean {
    return this.on && this.status === "ready";
  }

  toggle(): void {
    this.setOn(!this.on);
  }

  setOn(on: boolean): void {
    if (this.on === on) return;
    this.on = on;
    if (!on) {
      this.status = this.engine ? "ready" : "off";
      this.notify();
      return;
    }
    if (this.engine) {
      this.status = "ready";
      this.notify();
      return;
    }
    void this.start();
  }

  /** The as-of-scene names an editor's scene uses; null when it has none. */
  setViewNames(viewKey: string, names: string[] | null): void {
    if (names && names.length > 0) this.viewNames.set(viewKey, names);
    else if (!this.viewNames.delete(viewKey)) return;
    this.refreshWords();
  }

  cached(text: string): Finding[] | undefined {
    return this.cache.get(text);
  }

  lint(text: string): Promise<Finding[]> {
    const hit = this.cache.get(text);
    if (hit) return Promise.resolve(hit);
    const running = this.pending.get(text);
    if (running) return running;
    const engine = this.engine;
    if (!engine) return Promise.resolve([]);
    const generation = this.generation;
    const run = this.wordsLoad
      .then(() => engine.lint(text))
      .then((findings) => {
        if (generation === this.generation) {
          this.cache.set(text, findings);
          // Typing makes a new text per keystroke pause: forget the oldest.
          if (this.cache.size > CACHE_LIMIT) this.cache.delete(this.cache.keys().next().value as string);
        }
        return findings;
      })
      .finally(() => this.pending.delete(text));
    this.pending.set(text, run);
    return run;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    for (const listener of [...this.listeners]) listener();
  }

  private start(): Promise<void> {
    if (this.loading) return this.loading;
    this.status = "loading";
    this.error = null;
    this.loading = (async () => {
      try {
        this.engine = await withTimeout(this.deps.loadEngine(), this.deps.startTimeoutMs);
        this.stopLore = this.deps.subscribeLore((entries) => {
          this.lore = entries;
          this.refreshWords();
        });
        await this.reloadWords();
        this.status = "ready";
      } catch (err) {
        // Undo the whole start, so switching on again starts from nothing
        // (one lore subscription, not one more per attempt).
        this.stopLore?.();
        this.stopLore = null;
        this.loadedWords = null;
        this.engine = null;
        this.status = "error";
        this.error = err instanceof Error ? err.message : String(err);
        this.on = false;
      } finally {
        this.loading = null;
      }
      this.notify();
    })();
    return this.loading;
  }

  /** Reload the words from a subscription: a failure is not lost (the next
   *  reload retries it) and is not an unhandled rejection. */
  private refreshWords(): void {
    this.reloadWords().catch(() => undefined);
  }

  private async reloadWords(): Promise<void> {
    const engine = this.engine;
    if (!engine) return;
    const words = autoDictionary(this.lore, [...this.viewNames.values()].flat());
    const key = words.join("\n");
    if (key === this.loadedWords) return this.currentLoad;
    this.loadedWords = key;
    this.generation++;
    this.cache.clear();
    this.pending.clear();
    const load = this.wordsLoad.then(() => engine.setWords(words)).catch((err: unknown) => {
      // The engine does not have these words: let the next reload send them
      // again instead of taking them for loaded.
      if (this.loadedWords === key) this.loadedWords = null;
      throw err;
    });
    this.currentLoad = load;
    this.wordsLoad = load.catch(() => undefined);
    await load;
    if (this.status === "ready") this.notify();
  }

  /** Tests only: drop the engine and every subscription. */
  reset(): void {
    this.stopLore?.();
    this.stopLore = null;
    this.engine = null;
    this.loading = null;
    this.cache.clear();
    this.pending.clear();
    this.viewNames.clear();
    this.loadedWords = null;
    this.wordsLoad = Promise.resolve();
    this.currentLoad = Promise.resolve();
    this.on = false;
    this.status = "off";
    this.error = null;
    this.listeners.clear();
  }
}

export const proofreading = new ProofreadingController();

let viewCounter = 0;

/** Call during a prose editor's init: while it lives, its scene's as-of-scene
 *  names (a mid-story rename, #61) are in the dictionary too. */
export function trackProofreadNames(names: () => string[] | null, lens: ProofreadingController = proofreading): void {
  const key = `view-${++viewCounter}`;
  $effect(() => {
    const current = names();
    // Untracked: the lens's own state must not re-run this effect.
    untrack(() => lens.setViewNames(key, current));
  });
  $effect(() => () => lens.setViewNames(key, null));
}
