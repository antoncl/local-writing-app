// Proofreading (ADR-0102 §1, §5): the lens controller. Off at start; the
// engine loads once, on the first switch-on; lore names reach the engine
// before any lint runs; a word change drops what was linted before it.
import { describe, expect, it, vi } from "vitest";
import type { Finding, ProofreadEngine } from "@/lib/proofread/findings";
import type { LoreEntrySummary } from "@/lib/types";
import { ProofreadingController } from "./proofreading.svelte";

const entry = (title: string) => ({ id: `lore_${title}`, title, metadata: {} }) as unknown as LoreEntrySummary;

/** An engine that flags every word not in its dictionary, logging its calls. */
function fakeEngine() {
  let words = new Set<string>();
  const log: string[] = [];
  const engine: ProofreadEngine = {
    id: "fake",
    lint: vi.fn(async (text: string): Promise<Finding[]> => {
      log.push(`lint ${text}`);
      const findings: Finding[] = [];
      for (const m of text.matchAll(/\S+/g)) {
        if (!words.has(m[0])) {
          findings.push({ engine: "fake", from: m.index, to: m.index + m[0].length, kind: "Spelling", ruleId: "Spell", message: "?", fixes: [] });
        }
      }
      return findings;
    }),
    setWords: vi.fn(async (next: string[]) => {
      // Slow enough that a lint issued meanwhile would overtake it, if it could.
      await new Promise((r) => setTimeout(r, 5));
      words = new Set(next);
      log.push("words");
    }),
  };
  return { engine, log };
}

function setup(lore: LoreEntrySummary[] = []) {
  const { engine, log } = fakeEngine();
  let pushLore: (entries: LoreEntrySummary[]) => void = () => undefined;
  const loadEngine = vi.fn(async () => engine);
  const lens = new ProofreadingController({
    loadEngine,
    subscribeLore: (run) => {
      pushLore = run;
      run(lore);
      return () => undefined;
    },
  });
  return { lens, engine, log, loadEngine, pushLore: (e: LoreEntrySummary[]) => pushLore(e) };
}

const settle = () => new Promise((r) => setTimeout(r, 20));

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
    lens.setViewNames("view-1", ["Ashcombe"]);
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
    });
    lens.toggle();
    await settle();
    expect(lens.status).toBe("error");
    expect(lens.error).toBe("no wasm");
    expect(lens.on).toBe(false);
  });
});
