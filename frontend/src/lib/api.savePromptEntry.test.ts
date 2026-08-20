// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { PromptContextStrategy, PromptEntry } from "@/lib/types";

// The wire-level guard for the data-loss bug D3 closes (ADR-0062 D3): the backend
// rebuilds a prompt's front matter from the PUT body's arguments (not a merge), so
// savePromptEntry MUST put `context_strategy` on the wire on every save — omitting
// it strips a forked prompt's output/commit config. The editorPanes regression test
// pins that the store hands the strategy to savePromptEntry; this pins that
// savePromptEntry actually serialises it into the request body, so deleting the
// `context_strategy: entry.context_strategy ?? null` line can't pass silently.

function stubFetch(json: unknown) {
  const mock = vi.fn().mockResolvedValue({ ok: true, json: async () => json } as Response);
  vi.stubGlobal("fetch", mock);
  return mock;
}

function bodyOf(mock: ReturnType<typeof vi.fn>, callIndex: number): Record<string, unknown> {
  const init = mock.mock.calls[callIndex][1] as RequestInit;
  return JSON.parse(init.body as string);
}

const STRATEGY: PromptContextStrategy = {
  output: { handler: "extract_to_node", commit: { review: "replace" } },
};

function promptEntry(over: Partial<PromptEntry> = {}): PromptEntry {
  return {
    id: "prompt_1",
    title: "Summarize scene",
    entry_type: "prompt:general",
    revision: "r1",
    metadata: {},
    inputs: [],
    offer_on: [],
    context_strategy: STRATEGY,
    ...over,
  } as unknown as PromptEntry;
}

describe("api.savePromptEntry context_strategy round-trip (ADR-0062 D3)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("puts the prompt's context_strategy on the wire", async () => {
    const mock = stubFetch(promptEntry());
    const { api } = await import("@/lib/api");
    await api.savePromptEntry(promptEntry(), "the body");
    expect(bodyOf(mock, 0).context_strategy).toEqual(STRATEGY);
  });

  it("sends context_strategy: null (present, not omitted) when the prompt has none", async () => {
    // A prompt with no strategy must still send the key so a save is an explicit
    // clear, never a silent drop the field-absence guard would then wipe.
    const mock = stubFetch(promptEntry({ context_strategy: null }));
    const { api } = await import("@/lib/api");
    await api.savePromptEntry(promptEntry({ context_strategy: null }), "the body");
    const body = bodyOf(mock, 0);
    expect("context_strategy" in body).toBe(true);
    expect(body.context_strategy).toBeNull();
  });
});
