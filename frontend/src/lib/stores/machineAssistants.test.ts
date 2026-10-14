import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AssistantEntry, AssistantEntrySummary } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: {
    listMachineAssistantEntries: vi.fn(),
    listAssistantEntries: vi.fn(async () => ({ entries: [] })),
    createAssistantEntry: vi.fn(),
    saveAssistantEntry: vi.fn(),
    reorderAssistants: vi.fn(async () => ({ entries: [] })),
    getAssistantEntry: vi.fn(),
    deleteAssistantEntry: vi.fn(async () => ({ entries: [] })),
  },
}));
import { api } from "@/lib/api";
import { hireMachineAssistant, updateMachineAssistant } from "@/lib/stores/machineAssistants";

const S = (id: string, listed: string): AssistantEntrySummary =>
  ({ id, title: id, entry_type: "assistant:assistant", metadata: {}, computed_metadata: { listed } }) as AssistantEntrySummary;

beforeEach(() => vi.clearAllMocks());

// #2444: create only writes the OPEN PROJECT's order, so a hire must be listed
// and topmost on the MACHINE layer explicitly.
describe("hireMachineAssistant", () => {
  it("creates on the machine layer, saves the model, and lists the hire topmost", async () => {
    const created = { id: "new", title: "Muse", revision: "r1", entry_type: "assistant:assistant", metadata: {} } as unknown as AssistantEntry;
    vi.mocked(api.createAssistantEntry).mockResolvedValue(created);
    vi.mocked(api.listMachineAssistantEntries).mockResolvedValue({
      entries: [S("a", "listed"), S("hidden", "unlisted"), S("new", "unlisted"), S("b", "listed")],
    });

    await hireMachineAssistant("Muse", "anthropic", "fast", "claude-x");

    expect(api.createAssistantEntry).toHaveBeenCalledWith("Muse", "");
    expect(api.saveAssistantEntry).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata: { ai_provider: "anthropic", ai_capability_tier: "fast", ai_model: "claude-x" },
      }),
    );
    expect(api.reorderAssistants).toHaveBeenCalledWith(["new", "a", "b"], "");
  });
});

describe("updateMachineAssistant", () => {
  it("keeps existing metadata when no provider was picked", async () => {
    vi.mocked(api.getAssistantEntry).mockResolvedValue({
      id: "a", title: "Old", revision: "r2", entry_type: "assistant:assistant", metadata: { ai_model: "m", prompt: "p" },
    } as unknown as AssistantEntry);
    await updateMachineAssistant("a", { title: "New" });
    expect(api.saveAssistantEntry).toHaveBeenCalledWith(
      expect.objectContaining({ title: "New", revision: "r2", metadata: { ai_model: "m", prompt: "p" } }),
    );
  });
});
