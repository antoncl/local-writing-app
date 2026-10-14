// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";

// Navigation reads the backend for ancestor candidates (the Location step);
// stub the calls so the mount is hermetic.
vi.mock("@/lib/api", () => ({
  api: {
    prospectiveAncestorCandidates: vi.fn(async () => []),
    prospectiveProjectNode: vi.fn(async () => ({ metadata_schema: { fields: [] }, metadata: {}, field_sources: {} })),
    checkOllamaHost: vi.fn(),
  },
}));
// machineAssistants.ts pulls in the editor-pane controller; the wizard only
// needs the store here.
vi.mock("@/lib/stores/editorPanes.svelte", () => ({ editorPanes: { panes: [] } }));

import type { AssistantEntrySummary, MachineSettingsView } from "@/lib/types";
import CreateProjectWizard from "@/components/dialogs/CreateProjectWizard.svelte";
import { createWizard } from "@/lib/stores/createWizard.svelte";
import { assistantEntriesStore } from "@/lib/stores/assistants";
import { machineAssistantEntriesStore } from "@/lib/stores/machineAssistants";

const row = (id: string, title: string): AssistantEntrySummary =>
  ({ id, title, entry_type: "assistant:assistant", metadata: {}, computed_metadata: { listed: "listed" } }) as AssistantEntrySummary;

afterEach(() => createWizard.close());

// #2448: the AI step acts on the MACHINE layer, so it must list the machine
// roster — never the merged one, which is whatever project happens to be open
// (its own files and curation). Seed the two stores differently and assert
// which one renders.
describe("CreateProjectWizard AI step", () => {
  it("lists the machine roster, not the open project's merged roster", async () => {
    createWizard.getMachineSettings = () =>
      ({ providers: {}, default_provider: "" }) as unknown as MachineSettingsView;
    createWizard.defaultProjectsFolder = "C:/projects"; // returning user ⇒ starts on location
    machineAssistantEntriesStore.set([row("m1", "Machine One")]);
    assistantEntriesStore.set([row("local", "Book A Local"), row("m1", "Machine One")]);

    createWizard.start();
    createWizard.title = "Book B";
    createWizard.pickedFolder = "C:/projects";
    for (let i = 0; i < 4 && createWizard.currentStep.id !== "ai"; i++) await createWizard.next();
    expect(createWizard.currentStep.id).toBe("ai");
    createWizard.setAiPolicy("local-only");

    render(CreateProjectWizard);

    expect(await screen.findByText("Machine One")).toBeTruthy();
    expect(screen.queryByText("Book A Local")).toBeNull();
  });
});
