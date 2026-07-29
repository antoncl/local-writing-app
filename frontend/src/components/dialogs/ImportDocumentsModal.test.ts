// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ImportDocumentsModal from "@/components/dialogs/ImportDocumentsModal.svelte";

// A fully controlled modal: the host feeds `looseScenes` and owns the import.
// The seeding reactivity is what regressed in #639 — the last test is the
// regression guard the harness exists to make possible.
const docs = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    id: `s${i}`,
    title: `Scene ${i}`,
    filename: `s${i}.md`,
  }));

// The label wraps the checkbox, so a row's accessible name is "Scene i si.md".
const rowBox = (i: number) =>
  screen.getByRole("checkbox", { name: new RegExp(`Scene ${i}\\b`) }) as HTMLInputElement;

describe("ImportDocumentsModal", () => {
  it("renders nothing while closed", () => {
    render(ImportDocumentsModal, { props: { open: false, looseScenes: docs(3) } });
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("seeds every document selected on open", () => {
    render(ImportDocumentsModal, { props: { open: true, looseScenes: docs(3) } });
    // one select-all checkbox + three rows, all checked
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes).toHaveLength(4);
    expect(boxes.every((b) => b.checked)).toBe(true);
    expect(screen.getByRole("button", { name: /Add 3 to manuscript/ })).toBeEnabled();
  });

  it("reports the selected ids to onImport in order", async () => {
    const onImport = vi.fn();
    render(ImportDocumentsModal, { props: { open: true, looseScenes: docs(2), onImport } });
    await fireEvent.click(screen.getByRole("button", { name: /Add 2 to manuscript/ }));
    expect(onImport).toHaveBeenCalledWith(["s0", "s1"]);
  });

  it("disables the import button once nothing is selected", async () => {
    render(ImportDocumentsModal, { props: { open: true, looseScenes: docs(1) } });
    await fireEvent.click(rowBox(0));
    expect(screen.getByRole("button", { name: /Add 0 to manuscript/ })).toBeDisabled();
  });

  // #639: a post-import refresh reassigns `looseScenes`, which must NOT reseed
  // the selection. A deselected-but-still-loose row stays deselected; the
  // imported ids are pruned out.
  it("does not reseed a deselected row across a partial import", async () => {
    const { rerender } = render(ImportDocumentsModal, {
      props: { open: true, looseScenes: docs(3) },
    });

    await fireEvent.click(rowBox(1)); // user deselects Scene 1
    expect(rowBox(1).checked).toBe(false);

    // Partial import: s0 imported and leaves the loose list; s1 & s2 remain.
    await rerender({
      open: true,
      looseScenes: [
        { id: "s1", title: "Scene 1", filename: "s1.md" },
        { id: "s2", title: "Scene 2", filename: "s2.md" },
      ],
    });

    expect(rowBox(1).checked).toBe(false); // stayed deselected — not reseeded
    expect(rowBox(2).checked).toBe(true); // still selected
    expect(screen.getByRole("button", { name: /Add 1 to manuscript/ })).toBeInTheDocument();
  });
});
