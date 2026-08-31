// forkPrompt clone (ADR-0049 §5). Unlike `forkLore`, cloning a built-in Library
// prompt mints a NEW id and leaves the shipped original in place, so there is no
// in-place pane reconcile — the fresh editable copy is opened in its own pane.
//
// What these tests pin: forkPrompt clones via the API, then opens the returned
// copy (its new id, not the shipped original's), and opens it only after the
// clone exists.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { editorPanes } from "./editorPanes.svelte";
import { api } from "@/lib/api";
import type { PromptEntry } from "@/lib/types";

const LIBRARY: PromptEntry = {
  id: "prompt_test_roleplay",
  title: "Roleplay",
  body: "shipped body",
  revision: "",
  // ADR-0065 S3: roleplay collapsed to prompt:general, its old behavior now an
  // instance context_strategy (inline + the accept-time character mark-stamp).
  entry_type: "prompt:general",
  context_strategy: {
    output: { handler: "inline", on_accept: { mark: "character", from_input: "character" } },
  },
  metadata: {},
  inputs: [],
  computed_metadata: {},
  source_layer_id: "layer_library",
  source_layer_label: "Library",
  is_library: true,
};

const CLONE: PromptEntry = {
  ...LIBRARY,
  id: "prompt_new",
  revision: "r1",
  source_layer_id: "layer_project",
  source_layer_label: "",
  is_library: false,
};

describe("editorPanes.forkPrompt (ADR-0049 §5 clone)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    editorPanes.reset();
    // refreshPromptEntries() runs inside forkPrompt; keep it off the network.
    vi.spyOn(api, "listPromptEntries").mockResolvedValue({ entries: [] });
    vi.spyOn(api, "forkPromptEntry").mockResolvedValue(CLONE);
  });

  afterEach(() => editorPanes.reset());

  it("clones the Library prompt and opens the new copy (its new id)", async () => {
    const open = vi.spyOn(editorPanes, "openPrompt").mockResolvedValue(undefined);

    await editorPanes.forkPrompt(LIBRARY.id);

    expect(api.forkPromptEntry).toHaveBeenCalledWith(LIBRARY.id);
    // Opens the fresh copy, not the shipped original.
    expect(open).toHaveBeenCalledWith(CLONE.id);
    expect(open).not.toHaveBeenCalledWith(LIBRARY.id);
    // The clone must exist before we try to open it.
    expect(
      (api.forkPromptEntry as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0],
    ).toBeLessThan((open as ReturnType<typeof vi.fn>).mock.invocationCallOrder[0]);
  });
});
