import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AssistantEntry } from "@/lib/types";

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

beforeEach(() => vi.clearAllMocks());

// #2449: the backend lists a machine create topmost on the machine layer
// itself, so a hire is create + save and nothing else — in particular no
// reorder, which would rewrite some layer's curation.
describe("hireMachineAssistant", () => {
  it("creates on the machine layer and saves the model, without reordering", async () => {
    const created = { id: "new", title: "Muse", revision: "r1", entry_type: "assistant:assistant", metadata: {} } as unknown as AssistantEntry;
    vi.mocked(api.createAssistantEntry).mockResolvedValue(created);

    await hireMachineAssistant("Muse", "anthropic", "fast", "claude-x");

    expect(api.createAssistantEntry).toHaveBeenCalledWith("Muse", "");
    expect(api.saveAssistantEntry).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata: { ai_provider: "anthropic", ai_capability_tier: "fast", ai_model: "claude-x" },
      }),
    );
    expect(api.reorderAssistants).not.toHaveBeenCalled();
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
