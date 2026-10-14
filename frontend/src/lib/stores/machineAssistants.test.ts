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
const panesMock = vi.hoisted(() => ({
  panes: [] as { id: string; document?: { type: string; id: string } }[],
  close: vi.fn(async (_id: string) => {}),
  closeRemovedNodes: vi.fn(),
}));
vi.mock("@/lib/stores/editorPanes.svelte", () => ({ editorPanes: panesMock }));
import { api } from "@/lib/api";
import {
  deleteMachineAssistant,
  hireMachineAssistant,
  updateMachineAssistant,
} from "@/lib/stores/machineAssistants";

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

// An open editor pane on the assistant must not outlive a Settings write to its
// file: assistant panes are not re-baselined, so it would 409 / 404 next save.
describe("open editor panes", () => {
  beforeEach(() => {
    panesMock.panes = [
      { id: "p1", document: { type: "assistant", id: "x" } },
      { id: "p2", document: { type: "assistant", id: "other" } },
    ];
  });

  it("closes (flushes) only the edited assistant's pane before reading it", async () => {
    const order: string[] = [];
    panesMock.close.mockImplementation(async (id: string) => void order.push(`close:${id}`));
    vi.mocked(api.getAssistantEntry).mockImplementation(async () => {
      order.push("read");
      return { id: "x", title: "X", revision: "r2", entry_type: "assistant:assistant", metadata: {} } as unknown as AssistantEntry;
    });
    await updateMachineAssistant("x", { title: "X2" });
    expect(order).toEqual(["close:p1", "read"]);
  });

  it("tears down the deleted assistant's pane", async () => {
    await deleteMachineAssistant("x");
    expect(panesMock.closeRemovedNodes).toHaveBeenCalledWith(["x"]);
  });
});
