// The project-open fan-out (#1878): `loadProjectData` must re-read every
// roster that is project-scoped OR layered (machine + project). The assistant
// roster was hydrated only by the no-project `loadMachineSettings` pass, so a
// cold start showed machine-level assistants alone until some mutation
// happened to refresh the list. Every per-domain module is mocked to a no-op
// so this asserts the fan-out itself, not any store's own behaviour. (The
// factories are inlined: vi.mock is hoisted above any module-level helper.)
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/stores/structure", () => ({
  refreshStructure: vi.fn(async () => {}),
  refreshResearchStructure: vi.fn(async () => {}),
  clearStructure: vi.fn(),
}));
vi.mock("@/lib/stores/lore", () => ({ refreshLoreEntries: vi.fn(async () => {}), clearLore: vi.fn() }));
vi.mock("@/lib/stores/prompts", () => ({ refreshPromptEntries: vi.fn(async () => {}), clearPrompts: vi.fn() }));
vi.mock("@/lib/stores/plotTemplates", () => ({ refreshPlotTemplates: vi.fn(async () => {}), clearPlotTemplates: vi.fn() }));
vi.mock("@/lib/stores/plotlines", () => ({ refreshPlotlines: vi.fn(async () => {}), clearPlotlines: vi.fn() }));
vi.mock("@/lib/stores/plotCards", () => ({ refreshCards: vi.fn(async () => {}), clearCards: vi.fn() }));
vi.mock("@/lib/stores/plotBoard", () => ({ clearPlotBoard: vi.fn() }));
vi.mock("@/lib/stores/mutationSets", () => ({ refreshMutationSetEntries: vi.fn(async () => {}), clearMutationSets: vi.fn() }));
vi.mock("@/lib/stores/schema", () => ({ refreshSchema: vi.fn(async () => {}), clearSchema: vi.fn() }));
vi.mock("@/lib/stores/references", () => ({ refreshReferenceIndex: vi.fn(async () => {}), clearReferenceIndex: vi.fn() }));
vi.mock("@/lib/stores/tagNodes", () => ({ refreshTagNodes: vi.fn(async () => {}), clearTagNodes: vi.fn() }));
vi.mock("@/lib/stores/todos", () => ({ refreshTodos: vi.fn(async () => {}), refreshEmbeddedTodos: vi.fn(async () => {}), clearTodos: vi.fn() }));
vi.mock("@/lib/stores/validation", () => ({ clearValidation: vi.fn() }));
vi.mock("@/lib/stores/chats", () => ({ clearChats: vi.fn() }));
vi.mock("@/lib/stores/assistants", () => ({ refreshAssistantEntries: vi.fn(async () => {}), clearAssistants: vi.fn() }));
vi.mock("@/lib/stores/aiSpend.svelte", () => ({ aiSpend: { reset: vi.fn() } }));

import { clearAssistants, refreshAssistantEntries } from "@/lib/stores/assistants";
import { clearTagNodes, refreshTagNodes } from "@/lib/stores/tagNodes";
import { clearStructure, refreshStructure } from "@/lib/stores/structure";
import { clearChats } from "@/lib/stores/chats";
import { aiSpend } from "@/lib/stores/aiSpend.svelte";
import { clearProjectData, loadProjectData } from "@/lib/stores/index";

describe("loadProjectData (project-open fan-out)", () => {
  it("re-reads the layered rosters — assistants (#1878) and tags — under the project's scope", async () => {
    await loadProjectData();

    expect(refreshAssistantEntries).toHaveBeenCalledTimes(1);
    expect(refreshTagNodes).toHaveBeenCalledTimes(1);
    expect(refreshStructure).toHaveBeenCalledTimes(1);
  });
});

// #1881: the switch half. Before it, this had no caller and App hand-cleared
// tags, chats and spend on a switch — but not assistants, so project A's
// roster stayed on offer under project B until B's GET landed.
describe("clearProjectData (project-switch fan-out)", () => {
  it("clears every domain slice including both layered rosters, and refreshes nothing", () => {
    vi.mocked(refreshTagNodes).mockClear();
    vi.mocked(refreshAssistantEntries).mockClear();

    clearProjectData();

    expect(clearAssistants).toHaveBeenCalledTimes(1);
    expect(clearTagNodes).toHaveBeenCalledTimes(1);
    expect(clearChats).toHaveBeenCalledTimes(1);
    expect(clearStructure).toHaveBeenCalledTimes(1);
    expect(aiSpend.reset).toHaveBeenCalledTimes(1);
    // The open path re-reads everything next; a stray refresh here would race it.
    expect(refreshTagNodes).not.toHaveBeenCalled();
    expect(refreshAssistantEntries).not.toHaveBeenCalled();
  });
});
