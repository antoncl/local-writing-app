// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import type { MetadataSchema } from "@/lib/types";

// The modal edits a local draft and writes only on Save, through
// projectSession.setLevels; a conflict (containers renamed or stranded) is put
// to the author through the confirm service before it is forced.
const mock = vi.hoisted(() => ({
  setLevels: vi.fn(),
  request: vi.fn(),
}));
vi.mock("@/lib/stores/projectSession.svelte", () => ({
  projectSession: { setLevels: mock.setLevels },
}));
vi.mock("@/lib/stores/confirmService.svelte", () => ({
  confirmService: { request: mock.request },
}));

import StructureLevelsModal from "@/components/dialogs/StructureLevelsModal.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";

const SCHEMA = {
  version: 1,
  fields: {},
  entry_types: {
    "manuscript:base": { name: "Scene root", kind: "manuscript", abstract: true },
    "manuscript:container": { name: "Container", kind: "manuscript", parent: "manuscript:base" },
    "manuscript:act": { name: "Act", kind: "manuscript", parent: "manuscript:container" },
    "manuscript:scene": { name: "Scene", kind: "manuscript", parent: "manuscript:base" },
  },
} as unknown as MetadataSchema;

function renderModal(onClose = vi.fn()) {
  render(StructureLevelsModal, {
    props: {
      open: true,
      tree: "manuscript",
      containerType: "manuscript:container",
      levels: [{ name: "Act", type: "manuscript:act" }, { name: "Chapter", numbering: "continuous" }],
      onClose,
    },
  });
  return onClose;
}

const nameInput = (level: number) =>
  screen.getByRole("textbox", { name: `Level ${level} name` }) as HTMLInputElement;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
  mock.setLevels.mockReset();
  mock.request.mockReset();
  mock.setLevels.mockResolvedValue({ status: "saved" });
});
afterEach(() => {
  metadataSchemaStore.set(null as unknown as MetadataSchema);
});

describe("StructureLevelsModal", () => {
  it("seeds one row per level, with its type and numbering", () => {
    renderModal();
    expect(nameInput(1).value).toBe("Act");
    expect(nameInput(2).value).toBe("Chapter");
    expect((screen.getByRole("combobox", { name: "Level 1 type" }) as HTMLSelectElement).value).toBe(
      "manuscript:act",
    );
    expect((screen.getByRole("combobox", { name: "Level 2 type" }) as HTMLSelectElement).value).toBe("");
    expect(
      (screen.getByRole("combobox", { name: "Level 2 numbering" }) as HTMLSelectElement).value,
    ).toBe("continuous");
  });

  it("saves the edited list — an added level and an untyped level as null", async () => {
    const onClose = renderModal();
    await fireEvent.click(screen.getByRole("button", { name: "Add level" }));
    await fireEvent.input(nameInput(3), { target: { value: " Sequence " } });
    expect(mock.setLevels).not.toHaveBeenCalled(); // an edit alone never writes

    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(mock.setLevels).toHaveBeenCalledWith("manuscript", [
      { name: "Act", type: "manuscript:act", numbering: "restart" },
      { name: "Chapter", type: null, numbering: "continuous" },
      { name: "Sequence", type: null, numbering: "restart" },
    ]);
  });

  it("reorders and removes rows", async () => {
    renderModal();
    await fireEvent.click(screen.getByRole("button", { name: "Move level 2 up" }));
    expect(nameInput(1).value).toBe("Chapter");
    await fireEvent.click(screen.getByRole("button", { name: "Remove level 1" }));
    expect(nameInput(1).value).toBe("Act");
    expect(screen.getByRole("button", { name: "Remove level 1" })).toBeDisabled(); // never empty
  });

  it("blocks Save while a level has no name", async () => {
    renderModal();
    await fireEvent.input(nameInput(2), { target: { value: "  " } });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("asks before forcing a list that renames containers, then retries forced", async () => {
    mock.setLevels.mockResolvedValueOnce({ status: "conflict", message: "3 containers would move." });
    const onClose = renderModal();
    await fireEvent.click(screen.getByRole("button", { name: "Remove level 1" }));
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await vi.waitFor(() => expect(mock.request).toHaveBeenCalledTimes(1));
    expect(onClose).not.toHaveBeenCalled();
    const request = mock.request.mock.calls[0][0];
    expect(request.message).toContain("3 containers would move.");

    await request.onConfirm();
    expect(mock.setLevels).toHaveBeenLastCalledWith(
      "manuscript",
      [{ name: "Chapter", type: null, numbering: "continuous" }],
      true,
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("stays open when the save fails", async () => {
    mock.setLevels.mockResolvedValue({ status: "failed" });
    const onClose = renderModal();
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(mock.setLevels).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve));
    expect(onClose).not.toHaveBeenCalled();
  });
});
