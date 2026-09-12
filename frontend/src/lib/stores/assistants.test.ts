import { describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import type { AssistantEntrySummary } from "@/lib/types";

vi.mock("@/lib/api", () => ({ api: { listAssistantEntries: vi.fn() } }));
import { api } from "@/lib/api";
import { assistantEntriesStore, defaultAssistantIdStore, refreshAssistantEntries } from "@/lib/stores/assistants";

const A = (id: string, listed: string): AssistantEntrySummary =>
  ({
    id,
    title: id,
    entry_type: "assistant:assistant",
    metadata: {},
    computed_metadata: { listed, position: 0 },
  }) as AssistantEntrySummary;

// ADR-0024 Amendment 1 (#333). The roster carries un-listed entries so nothing
// becomes unreachable in the Assistants pane, which means `$entries[0]` stopped
// meaning "top of my roster" — and an un-listed assistant sorts first often
// enough that un-listing became a way to make the app START using something.
// A mutation reverting this to `$entries[0]` survived the whole suite until
// this file existed.
describe("defaultAssistantIdStore", () => {
  it("skips an un-listed assistant that sorts first", () => {
    assistantEntriesStore.set([A("gone", "unlisted"), A("keep", "listed")]);
    expect(get(defaultAssistantIdStore)).toBe("keep");
  });

  it("is empty when nothing is listed, rather than guessing", () => {
    assistantEntriesStore.set([A("gone", "unlisted")]);
    expect(get(defaultAssistantIdStore)).toBe("");
  });

  it("is the topmost listed entry, preserving roster order", () => {
    assistantEntriesStore.set([A("first", "listed"), A("second", "listed")]);
    expect(get(defaultAssistantIdStore)).toBe("first");
  });
});

// #1878: the no-project hydration (machine layer only) and the project-open
// refresh can be in flight together. The EARLIER answer must never land over
// the later one, or the pane shows machine-level assistants for a project
// that has its own — the very symptom that needed "Add assistant" to repair.
describe("refreshAssistantEntries stale guard", () => {
  it("drops an earlier response that resolves after a later refresh's", async () => {
    type Roster = { entries: AssistantEntrySummary[] };
    let resolveFirst!: (value: Roster) => void;
    let resolveSecond!: (value: Roster) => void;
    const first = new Promise<Roster>((resolve) => {
      resolveFirst = resolve;
    });
    const second = new Promise<Roster>((resolve) => {
      resolveSecond = resolve;
    });
    vi.mocked(api.listAssistantEntries).mockReturnValueOnce(first).mockReturnValueOnce(second);

    const machineOnly = refreshAssistantEntries();
    const withProject = refreshAssistantEntries();
    resolveSecond({ entries: [A("machine", "listed"), A("project", "listed")] });
    await withProject;
    resolveFirst({ entries: [A("machine", "listed")] });
    await machineOnly;

    expect(get(assistantEntriesStore).map((entry) => entry.id)).toEqual(["machine", "project"]);
  });

  it("keeps the previous roster when the request fails", async () => {
    assistantEntriesStore.set([A("kept", "listed")]);
    vi.mocked(api.listAssistantEntries).mockRejectedValueOnce(new Error("offline"));

    await refreshAssistantEntries();

    expect(get(assistantEntriesStore).map((entry) => entry.id)).toEqual(["kept"]);
  });
});
