// BodyMemory (#2013): session-only per-node tab + scroll memory. Plain class,
// no DOM — `createBodyMemory()` gives each test its own instance rather than
// sharing the module singleton.
import { describe, expect, it } from "vitest";
import { createBodyMemory } from "./bodyMemory.svelte";

describe("BodyMemory", () => {
  it("remembers and recalls a tab per node", () => {
    const memory = createBodyMemory();
    memory.rememberTab("node_a", "list:kin");
    memory.rememberTab("node_b", "body");
    expect(memory.tabFor("node_a")).toBe("list:kin");
    expect(memory.tabFor("node_b")).toBe("body");
  });

  it("an unknown node's tab is undefined", () => {
    const memory = createBodyMemory();
    expect(memory.tabFor("node_never_seen")).toBeUndefined();
  });

  it("remembers scroll per surface, independently per node", () => {
    const memory = createBodyMemory();
    memory.rememberScroll("node_a", "body", 120);
    memory.rememberScroll("node_a", "list:kin", 40);
    memory.rememberScroll("node_b", "body", 0);
    expect(memory.scrollFor("node_a", "body")).toBe(120);
    expect(memory.scrollFor("node_a", "list:kin")).toBe(40);
    expect(memory.scrollFor("node_b", "body")).toBe(0);
  });

  it("an unknown (node, surface) pair's scroll is undefined", () => {
    const memory = createBodyMemory();
    memory.rememberScroll("node_a", "body", 120);
    expect(memory.scrollFor("node_a", "list:kin")).toBeUndefined();
    expect(memory.scrollFor("node_never_seen", "body")).toBeUndefined();
  });

  it("forget clears both the tab and every scroll surface for that node, leaving others untouched", () => {
    const memory = createBodyMemory();
    memory.rememberTab("node_a", "list:kin");
    memory.rememberScroll("node_a", "body", 120);
    memory.rememberScroll("node_a", "list:kin", 40);
    memory.rememberTab("node_b", "body");
    memory.rememberScroll("node_b", "body", 7);

    memory.forget("node_a");

    expect(memory.tabFor("node_a")).toBeUndefined();
    expect(memory.scrollFor("node_a", "body")).toBeUndefined();
    expect(memory.scrollFor("node_a", "list:kin")).toBeUndefined();
    expect(memory.tabFor("node_b")).toBe("body");
    expect(memory.scrollFor("node_b", "body")).toBe(7);
  });
});
