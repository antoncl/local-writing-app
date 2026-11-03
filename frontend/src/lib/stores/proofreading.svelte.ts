// Proofreading (ADR-0102 §1, §4–§5): the lens. One app-wide switch, off at every
// start and never persisted: a revision pass is a sitting, and a lens that came
// back on by itself would underline the next first draft.
//
// Switching it on the first time loads the engine (a dynamic import, so the
// binary never loads before the writer asks for it). Switching it off keeps the
// engine for the session, so the next switch-on is immediate.
//
// The engine is loaded with two things: the words — the lore auto-dictionary
// plus the writer's dictionary files — and the config — the rule switches, the
// dialect and the ignore-here hashes, all read from the backend's merged setup.
// The setup is fetched again whenever the lore roster changes, which it does on
// every project switch. The popover's three permanent ignores write through the
// backend and load the answer.
//
// Each prose editor's highlight plugin asks this controller to lint a block's
// text and subscribes to hear when its findings may have changed. Results are
// cached by text and dropped whenever the words or the config change.
import { untrack } from "svelte";
import { api } from "@/lib/api";
import { scopeHeaders } from "@/lib/api/core";
import { loreEntriesStore } from "@/lib/stores/lore";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { firstInEntryTypeChain } from "@/lib/utils/colors";
import { autoDictionary, withPossessives, type SceneNameSet } from "@/lib/proofread/dictionary";
import type { EngineConfig, Finding, ProofreadEngine, RuleGroup } from "@/lib/proofread/findings";
import type { LoreEntrySummary, MetadataSchema, ProofreadingDialect, ProofreadingSetup } from "@/lib/types";

const CACHE_LIMIT = 4000;

export type LensStatus = "off" | "loading" | "ready" | "error";

/** What the highlight extension needs of the lens. */
export interface ProofreadLens {
  readonly active: boolean;
  /** The merged setup: the layers the ignores can be written to. */
  readonly setup: ProofreadingSetup | null;
  /** The findings for `text` if already linted, else undefined. */
  cached(text: string): Finding[] | undefined;
  /** Lint `text` (from the cache when it can). Rejects only on engine failure. */
  lint(text: string): Promise<Finding[]>;
  /** Hear when findings may have changed; returns the unsubscribe. */
  subscribe(listener: () => void): () => void;
  /** Add to dictionary: `word` is spelled right at `layerId` and below. */
  addWord(word: string, layerId: string): Promise<void>;
  /** Stop checking this rule at `layerId` and below. */
  disableRule(rule: string, layerId: string): Promise<void>;
  /** Ignore here: this one finding in `nodeId`, made from `text`, its block. */
  ignoreHere(nodeId: string, text: string, finding: Finding): Promise<void>;
}

/** The backend calls the lens makes (the real ones are `api`'s). */
export interface ProofreadingBackend {
  read(): Promise<ProofreadingSetup>;
  addWord(word: string, layerId: string): Promise<ProofreadingSetup>;
  removeWord(word: string, layerId: string): Promise<ProofreadingSetup>;
  setRule(rule: string, enabled: boolean | null, layerId: string): Promise<ProofreadingSetup>;
  setDialect(dialect: ProofreadingDialect | null, layerId: string): Promise<ProofreadingSetup>;
  ignore(nodeId: string, hashes: string[]): Promise<ProofreadingSetup>;
}

export interface ProofreadingDeps {
  loadEngine: () => Promise<ProofreadEngine>;
  /** Subscribe to the lore roster; returns the unsubscribe. */
  subscribeLore: (run: (entries: LoreEntrySummary[]) => void) => () => void;
  /** Subscribe to the merged metadata schema (its entry types' `proper_names`);
   *  returns the unsubscribe. */
  subscribeSchema: (run: (schema: MetadataSchema | null) => void) => () => void;
  backend: ProofreadingBackend;
  /** The open project's root, to tell a project switch from a lore edit. */
  projectRoot: () => string | null;
  /** How long the engine may take to start before the lens reports an error. */
  startTimeoutMs: number;
}

const defaultDeps: ProofreadingDeps = {
  loadEngine: async () => (await import("@/lib/proofread/harperEngine")).createHarperEngine(),
  subscribeLore: (run) => loreEntriesStore.subscribe(run),
  subscribeSchema: (run) => metadataSchemaStore.subscribe(run),
  backend: {
    read: () => api.getProofreading(),
    addWord: (word, layerId) => api.addProofreadingWord(word, layerId),
    removeWord: (word, layerId) => api.removeProofreadingWord(word, layerId),
    setRule: (rule, enabled, layerId) => api.setProofreadingRule(rule, enabled, layerId),
    setDialect: (dialect, layerId) => api.setProofreadingDialect(dialect, layerId),
    ignore: (nodeId, hashes) => api.ignoreProofreadingSpot(nodeId, hashes),
  },
  projectRoot: () => scopeHeaders()["X-Project-Root"] ?? null,
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

/** The engine config the setup asks for. */
function engineConfig(setup: ProofreadingSetup | null): EngineConfig {
  return {
    rules: setup?.rules ?? {},
    dialect: setup?.dialect ?? "american",
    ignored: Object.values(setup?.ignored ?? {}).flat(),
  };
}

/** One kind of engine state (the words, or the config) loaded at most once
 *  per distinct value: a repeat of what is loaded or loading waits on that
 *  load, failure included, and a failed load is sent again next time. */
class EngineSlot {
  private loaded: string | null = null;
  private current: Promise<void> = Promise.resolve();

  /** `queue` runs a step on the engine in order; `onChange` hears a new value. */
  constructor(
    private queue: (step: () => Promise<void>) => Promise<void>,
    private onChange: () => void,
  ) {}

  /** Load `key`'s value with `run` unless it is already loaded or loading. */
  load(key: string, run: () => Promise<void>): Promise<void> {
    if (key === this.loaded) return this.current;
    this.loaded = key;
    this.onChange();
    this.current = this.queue(run).catch((err: unknown) => {
      // The engine does not have this value: send it again next time instead
      // of taking it for loaded.
      if (this.loaded === key) this.loaded = null;
      throw err;
    });
    return this.current;
  }

  reset(): void {
    this.loaded = null;
    this.current = Promise.resolve();
  }
}

export class ProofreadingController implements ProofreadLens {
  on = $state(false);
  status = $state<LensStatus>("off");
  error = $state<string | null>(null);
  setup = $state.raw<ProofreadingSetup | null>(null);

  private engine: ProofreadEngine | null = null;
  private loading: Promise<void> | null = null;
  private listeners = new Set<() => void>();
  private cache = new Map<string, Finding[]>();
  private pending = new Map<string, Promise<Finding[]>>();
  private lore: LoreEntrySummary[] = [];
  private stopLore: (() => void) | null = null;
  private schema: MetadataSchema | null = null;
  private stopSchema: (() => void) | null = null;
  /** As-of-scene name sets per editor (a scene's mid-story renames, #61),
   *  each `[entityId, [title, ...aliases]]`. */
  private viewNames = new Map<string, SceneNameSet[]>();
  private words: EngineSlot;
  private config: EngineSlot;
  /** Bumped whenever the words or config change, so a lint that started
   *  before is not cached. */
  private generation = 0;
  /** The engine's queue: words and config are each two or more engine calls,
   *  and no lint may run between them. Never rejects. */
  private engineWork: Promise<void> = Promise.resolve();
  /** Setup requests are numbered when sent; an answer older than one already
   *  applied is dropped, so a read sent before a write can't undo it. */
  private setupSent = 0;
  private setupApplied = 0;
  /** The project the loaded setup belongs to. */
  private setupRoot: string | null = null;

  constructor(private deps: ProofreadingDeps = defaultDeps) {
    const queue = (step: () => Promise<void>) => this.queue(step);
    const changed = () => this.changed();
    this.words = new EngineSlot(queue, changed);
    this.config = new EngineSlot(queue, changed);
  }

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
    // Set here, not in `start`: a start the settings tab made while the lens
    // was off shows nothing on the lens.
    this.status = "loading";
    this.error = null;
    void this.start();
  }

  /** The as-of-scene name sets an editor's scene uses; null when it has none. */
  setViewNames(viewKey: string, names: SceneNameSet[] | null): void {
    if (names && names.length > 0) this.viewNames.set(viewKey, names);
    else if (!this.viewNames.delete(viewKey)) return;
    this.reloadWords().catch(() => undefined);
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
    const run = this.engineWork
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

  async addWord(word: string, layerId: string): Promise<void> {
    await this.load(() => this.deps.backend.addWord(word, layerId));
  }

  async disableRule(rule: string, layerId: string): Promise<void> {
    await this.setRule(rule, false, layerId);
  }

  /** Settings tab: `enabled` null sets the rule back to "as inherited". */
  async setRule(rule: string, enabled: boolean | null, layerId: string): Promise<void> {
    await this.load(() => this.deps.backend.setRule(rule, enabled, layerId));
  }

  /** Settings tab: `dialect` null sets the dialect back to "as inherited". */
  async setDialect(dialect: ProofreadingDialect | null, layerId: string): Promise<void> {
    await this.load(() => this.deps.backend.setDialect(dialect, layerId));
  }

  async removeWord(word: string, layerId: string): Promise<void> {
    await this.load(() => this.deps.backend.removeWord(word, layerId));
  }

  /** Settings tab: Harper's rules in its groups, with the setup read fresh.
   *  Starts the engine if need be (that start reads the setup), without
   *  switching the lens on. */
  async catalog(): Promise<RuleGroup[]> {
    if (this.engine) await this.refresh();
    else await this.start();
    const engine = this.engine;
    if (!engine) throw new Error(this.error ?? "the checker is not running");
    return engine.catalog();
  }

  async ignoreHere(nodeId: string, text: string, finding: Finding): Promise<void> {
    const hashes = (await this.engine?.hashesOf(text, finding)) ?? [];
    if (hashes.length === 0) throw new Error("This finding can't be ignored here.");
    await this.load(() => this.deps.backend.ignore(nodeId, hashes));
  }

  private notify(): void {
    for (const listener of [...this.listeners]) listener();
  }

  private start(): Promise<void> {
    if (this.engine) return Promise.resolve();
    if (this.loading) return this.loading;
    this.loading = (async () => {
      try {
        this.engine = await withTimeout(this.deps.loadEngine(), this.deps.startTimeoutMs);
        let starting = true;
        this.stopLore = this.deps.subscribeLore((entries) => {
          this.lore = entries;
          if (starting) return;
          // The new names are known now: load them before anything else lints.
          this.reloadWords().catch(() => undefined);
          // A project switch replaces the roster: read that project's setup.
          // A lore edit within the project doesn't change it.
          if (this.deps.projectRoot() !== this.setupRoot) this.refresh().catch(() => undefined);
        });
        // Names are case-sensitive until the schema says an entry's type
        // isn't a proper noun, so nothing loosens before it arrives.
        this.stopSchema = this.deps.subscribeSchema((schema) => {
          this.schema = schema;
          if (starting) return;
          this.reloadWords().catch(() => undefined);
        });
        starting = false;
        await this.refresh();
        // Started for the settings tab alone, the lens stays off ("ready" is
        // what a switched-off lens with an engine reads, as in `setOn`).
        this.status = "ready";
      } catch (err) {
        // Undo the whole start, so switching on again starts from nothing
        // (one lore subscription, not one more per attempt).
        this.stopLore?.();
        this.stopLore = null;
        this.stopSchema?.();
        this.stopSchema = null;
        this.words.reset();
        this.config.reset();
        this.engine = null;
        // A start for the settings tab alone fails there, not on the lens.
        this.status = this.on ? "error" : "off";
        this.error = err instanceof Error ? err.message : String(err);
        this.on = false;
      } finally {
        this.loading = null;
      }
      this.notify();
    })();
    return this.loading;
  }

  /** Read the open project's setup and load it. */
  private async refresh(): Promise<void> {
    this.setupRoot = this.deps.projectRoot();
    await this.load(() => this.deps.backend.read());
  }

  /** Send a setup request and load its answer, unless an answer to a later
   *  request was loaded first. */
  private async load(request: () => Promise<ProofreadingSetup>): Promise<void> {
    const sent = ++this.setupSent;
    const setup = await request();
    if (sent < this.setupApplied) return;
    this.setupApplied = sent;
    this.setup = setup;
    await Promise.all([this.reloadConfig(), this.reloadWords()]);
  }

  /** Queue `step` on the engine. */
  private queue(step: () => Promise<void>): Promise<void> {
    const run = this.engineWork.then(step);
    this.engineWork = run.catch(() => undefined);
    return run;
  }

  /** The words or config changed: nothing linted before still holds. */
  private changed(): void {
    this.generation++;
    this.cache.clear();
    this.pending.clear();
  }

  private async reloadWords(): Promise<void> {
    const engine = this.engine;
    if (!engine) return;
    const schema = this.schema;
    // No schema yet → every type is a proper name (case-sensitive titles).
    const properName = (entryType: string) =>
      schema ? (firstInEntryTypeChain(entryType, schema, (t) => t.proper_names) ?? false) : true;
    const auto = autoDictionary(this.lore, [...this.viewNames.values()].flat(1), properName);
    // A word the writer added is spelled as written, possessives included.
    const own = (this.setup?.words ?? []).flatMap(withPossessives);
    const words = [...new Set([...auto, ...own])].sort();
    await this.words.load(words.join("\n"), () => engine.setWords(words));
    if (this.status === "ready") this.notify();
  }

  private async reloadConfig(): Promise<void> {
    const engine = this.engine;
    if (!engine) return;
    const config = engineConfig(this.setup);
    await this.config.load(JSON.stringify(config), () => engine.configure(config));
    if (this.status === "ready") this.notify();
  }

  /** Tests only: drop the engine and every subscription. */
  reset(): void {
    this.stopLore?.();
    this.stopLore = null;
    this.stopSchema?.();
    this.stopSchema = null;
    this.schema = null;
    this.engine = null;
    this.loading = null;
    this.cache.clear();
    this.pending.clear();
    this.viewNames.clear();
    this.words.reset();
    this.config.reset();
    this.engineWork = Promise.resolve();
    this.setup = null;
    this.setupSent = 0;
    this.setupApplied = 0;
    this.setupRoot = null;
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
export function trackProofreadNames(names: () => SceneNameSet[] | null, lens: ProofreadingController = proofreading): void {
  const key = `view-${++viewCounter}`;
  $effect(() => {
    const current = names();
    // Untracked: the lens's own state must not re-run this effect.
    untrack(() => lens.setViewNames(key, current));
  });
  $effect(() => () => lens.setViewNames(key, null));
}
