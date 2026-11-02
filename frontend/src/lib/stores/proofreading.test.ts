// Proofreading (ADR-0102 §1, §4–§5): the lens controller. Off at start; the
// engine loads once, on the first switch-on; the lore names and the writer's
// setup (words, rules, dialect, ignores) reach the engine before any lint runs;
// a change to either drops what was linted before it; the three permanent
// ignores write through the backend and load its answer.
import { describe, expect, it, vi } from "vitest";
import type { EngineConfig, Finding, ProofreadEngine } from "@/lib/proofread/findings";
import type { LoreEntrySummary, ProofreadingSetup } from "@/lib/types";
import { ProofreadingController, type ProofreadingBackend } from "./proofreading.svelte";

const entry = (title: string) => ({ id: `lore_${title}`, title, metadata: {} }) as unknown as LoreEntrySummary;

/** The hash the fake engine gives a finding: its text and position. */
const hashFor = (text: string, finding: Finding) => String(text.length * 1000 + finding.from);

/** An engine that flags every word not in its dictionary (rule "Spell"),
 *  honouring rule switches and ignore hashes, and logging its calls. */
function fakeEngine() {
  let words = new Set<string>();
  let config: EngineConfig = { rules: {}, dialect: "american", ignored: [] };
  const log: string[] = [];
  const engine = {
    id: "fake",
    lint: vi.fn(async (text: string): Promise<Finding[]> => {
      log.push(`lint ${text}`);
      if (config.rules.Spell === false) return [];
      const findings: Finding[] = [];
      for (const m of text.matchAll(/\S+/g)) {
        const finding: Finding = { engine: "fake", from: m.index, to: m.index + m[0].length, kind: "Spelling", ruleId: "Spell", message: "?", fixes: [] };
        if (!words.has(m[0]) && !config.ignored.includes(hashFor(text, finding))) findings.push(finding);
      }
      return findings;
    }),
    setWords: vi.fn(async (next: string[]) => {
      // Slow enough that a lint issued meanwhile would overtake it, if it could.
      await new Promise((r) => setTimeout(r, 5));
      words = new Set(next);
      log.push("words");
    }),
    configure: vi.fn(async (next: EngineConfig) => {
      await new Promise((r) => setTimeout(r, 5));
      config = next;
      log.push("config");
    }),
    hashOf: vi.fn(async (text: string, finding: Finding): Promise<string | null> => hashFor(text, finding)),
  } satisfies ProofreadEngine;
  return { engine, log };
}

/** A backend holding one project's files in memory: Library, machine, book. */
function fakeBackend(initial: Partial<ProofreadingSetup> = {}) {
  const words: Record<string, string[]> = {};
  const rules: Record<string, boolean> = { ...(initial.rules ?? {}) };
  const ignored: Record<string, string[]> = { ...(initial.ignored ?? {}) };
  for (const word of initial.words ?? []) words[word] = ["book"];
  const read = async (): Promise<ProofreadingSetup> => ({
    words: Object.keys(words).sort(),
    word_layers: { ...words },
    rules: { ...rules },
    rule_layers: {},
    dialect: initial.dialect ?? "american",
    layers: [
      { id: "lib", label: "Library", is_machine: false, is_library: true, is_root: false },
      { id: "machine", label: "Machine", is_machine: true, is_library: false, is_root: false },
      { id: "book", label: "Book 1", is_machine: false, is_library: false, is_root: true },
    ],
    ignored: structuredClone(ignored),
  });
  const backend = {
    read: vi.fn(read),
    addWord: vi.fn(async (word: string, layerId: string) => {
      words[word] = [layerId];
      return read();
    }),
    setRule: vi.fn(async (rule: string, enabled: boolean | null) => {
      if (enabled === null) delete rules[rule];
      else rules[rule] = enabled;
      return read();
    }),
    ignore: vi.fn(async (nodeId: string, hash: string) => {
      (ignored[nodeId] ??= []).push(hash);
      return read();
    }),
  } satisfies ProofreadingBackend;
  return backend;
}

function setup(lore: LoreEntrySummary[] = [], files: Partial<ProofreadingSetup> = {}) {
  const { engine, log } = fakeEngine();
  const backend = fakeBackend(files);
  let pushLore: (entries: LoreEntrySummary[]) => void = () => undefined;
  const loadEngine = vi.fn(async () => engine);
  const lens = new ProofreadingController({
    loadEngine,
    subscribeLore: (run) => {
      pushLore = run;
      run(lore);
      return () => undefined;
    },
    backend,
    startTimeoutMs: 1000,
  });
  return { lens, engine, log, backend, loadEngine, pushLore: (e: LoreEntrySummary[]) => pushLore(e) };
}

// Generous: the fake engine waits per step, and Windows timers round up to ~15 ms.
const settle = () => new Promise((r) => setTimeout(r, 80));

describe("ProofreadingController", () => {
  it("starts off and loads nothing until switched on", () => {
    const { lens, loadEngine } = setup();
    expect(lens.on).toBe(false);
    expect(lens.status).toBe("off");
    expect(loadEngine).not.toHaveBeenCalled();
  });

  it("loads the engine once, and keeps it across off and on", async () => {
    const { lens, loadEngine } = setup();
    const heard = vi.fn();
    lens.subscribe(heard);
    lens.toggle();
    expect(lens.status).toBe("loading");
    expect(lens.active).toBe(false);
    await settle();
    expect(lens.active).toBe(true);
    lens.toggle();
    expect(lens.active).toBe(false);
    lens.toggle();
    expect(lens.active).toBe(true);
    expect(loadEngine).toHaveBeenCalledTimes(1);
    expect(heard).toHaveBeenCalledTimes(3);
  });

  it("is ready only once the lore names are loaded", async () => {
    const { lens } = setup([entry("Kael")]);
    lens.toggle();
    await settle();
    expect(await lens.lint("Kael's")).toEqual([]);
  });

  it("holds a lint until a word reload in flight has finished", async () => {
    const { lens, log, pushLore } = setup();
    lens.toggle();
    await settle();
    log.length = 0;
    pushLore([entry("Kael")]);
    expect(await lens.lint("Kael's")).toEqual([]);
    expect(log).toEqual(["words", "lint Kael's"]);
  });

  it("forgets what was linted when the words change, and lints again", async () => {
    const { lens, engine, pushLore } = setup();
    lens.toggle();
    await settle();
    expect(await lens.lint("Vashti")).toHaveLength(1);
    expect(lens.cached("Vashti")).toHaveLength(1);
    pushLore([entry("Vashti")]);
    expect(lens.cached("Vashti")).toBeUndefined();
    expect(await lens.lint("Vashti")).toEqual([]);
    expect(engine.lint).toHaveBeenCalledTimes(2);
  });

  it("adds an editor's as-of-scene names, and drops them when it goes", async () => {
    const { lens } = setup();
    lens.toggle();
    await settle();
    lens.setViewNames("view-1", [["Ashcombe"]]);
    expect(await lens.lint("Ashcombe")).toEqual([]);
    lens.setViewNames("view-1", null);
    expect(await lens.lint("Ashcombe")).toHaveLength(1);
  });

  it("reports a failed start and switches itself off", async () => {
    const lens = new ProofreadingController({
      loadEngine: async () => {
        throw new Error("no wasm");
      },
      subscribeLore: () => () => undefined,
      backend: fakeBackend(),
      startTimeoutMs: 1000,
    });
    lens.toggle();
    await settle();
    expect(lens.status).toBe("error");
    expect(lens.error).toBe("no wasm");
    expect(lens.on).toBe(false);
  });

  it("retries words that failed to load, without an unhandled rejection", async () => {
    const { lens, engine, pushLore } = setup();
    lens.toggle();
    await settle();
    vi.mocked(engine.setWords).mockRejectedValueOnce(new Error("worker hiccup"));
    pushLore([entry("Kael")]);
    await settle();
    expect(await lens.lint("Kael")).toHaveLength(1);
    // The same roster again: the words go to the engine this time.
    pushLore([entry("Kael")]);
    await settle();
    expect(await lens.lint("Kael")).toEqual([]);
  });

  it("leaves no lore subscription behind after a failed start", async () => {
    const { engine } = fakeEngine();
    vi.mocked(engine.setWords).mockRejectedValueOnce(new Error("worker died"));
    let subscriptions = 0;
    const lens = new ProofreadingController({
      loadEngine: async () => engine,
      subscribeLore: (run) => {
        subscriptions++;
        run([]);
        return () => subscriptions--;
      },
      backend: fakeBackend(),
      startTimeoutMs: 1000,
    });
    lens.toggle();
    await settle();
    expect(lens.status).toBe("error");
    expect(subscriptions).toBe(0);
    lens.toggle();
    await settle();
    expect(lens.status).toBe("ready");
    expect(subscriptions).toBe(1);
  });

  it("loads the writer's words, possessives included, and rules before the first lint", async () => {
    const { lens, engine } = setup([], { words: ["Vashti"], dialect: "british", rules: { Hedging: false } });
    lens.toggle();
    await settle();
    expect(await lens.lint("Vashti's")).toEqual([]);
    expect(engine.configure).toHaveBeenLastCalledWith({ rules: { Hedging: false }, dialect: "british", ignored: [] });
    expect(lens.setup?.words).toEqual(["Vashti"]);
  });

  it("honours a rule switched off in the files", async () => {
    const { lens } = setup([], { rules: { Spell: false } });
    lens.toggle();
    await settle();
    expect(await lens.lint("xyzzy")).toEqual([]);
  });

  it("adds a word through the backend, and the word stops being flagged", async () => {
    const { lens, backend } = setup();
    lens.toggle();
    await settle();
    expect(await lens.lint("Zorn")).toHaveLength(1);
    await lens.addWord("Zorn", "book");
    expect(backend.addWord).toHaveBeenCalledWith("Zorn", "book");
    expect(lens.cached("Zorn")).toBeUndefined();
    expect(await lens.lint("Zorn")).toEqual([]);
  });

  it("stops checking a rule through the backend", async () => {
    const { lens, backend } = setup();
    lens.toggle();
    await settle();
    expect(await lens.lint("xyzzy")).toHaveLength(1);
    await lens.disableRule("Spell", "machine");
    expect(backend.setRule).toHaveBeenCalledWith("Spell", false, "machine");
    expect(await lens.lint("xyzzy")).toEqual([]);
  });

  it("ignores one spot by its hash, and only that spot", async () => {
    const { lens, backend, engine } = setup();
    lens.toggle();
    await settle();
    const [first, second] = await lens.lint("ab cd");
    await lens.ignoreHere("manuscript_1", "ab cd", second);
    expect(engine.hashOf).toHaveBeenCalledWith("ab cd", second);
    expect(backend.ignore).toHaveBeenCalledWith("manuscript_1", "5003");
    expect(await lens.lint("ab cd")).toEqual([first]);
  });

  it("refuses to ignore a finding the engine can't hash", async () => {
    const { lens, backend, engine } = setup();
    lens.toggle();
    await settle();
    const [finding] = await lens.lint("ab");
    engine.hashOf.mockResolvedValueOnce(null);
    await expect(lens.ignoreHere("manuscript_1", "ab", finding)).rejects.toThrow(/can't be ignored/);
    expect(backend.ignore).not.toHaveBeenCalled();
  });

  it("reads the setup again when the lore roster changes, as on a project switch", async () => {
    const { lens, backend, pushLore } = setup();
    lens.toggle();
    await settle();
    expect(backend.read).toHaveBeenCalledTimes(1);
    pushLore([entry("Kael")]);
    await settle();
    expect(backend.read).toHaveBeenCalledTimes(2);
  });

  it("reports a start that never finishes instead of loading forever", async () => {
    const lens = new ProofreadingController({
      loadEngine: () => new Promise<never>(() => undefined),
      subscribeLore: () => () => undefined,
      backend: fakeBackend(),
      startTimeoutMs: 10,
    });
    lens.toggle();
    expect(lens.status).toBe("loading");
    await settle();
    expect(lens.status).toBe("error");
    expect(lens.error).toMatch(/did not start/);
    expect(lens.on).toBe(false);
  });
});
