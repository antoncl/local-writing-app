// @vitest-environment happy-dom
// The Settings → Proofreading tab: the level picker, a rule's inherited value
// and who decided it, and the dictionary's remove button.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import type { ProofreadingLayer, ProofreadingSetup } from "@/lib/types";

const layer = (id: string, label: string, own: Partial<ProofreadingLayer> = {}): ProofreadingLayer => ({
  id,
  label,
  is_machine: id === "machine",
  is_library: id === "lib",
  is_root: id === "book",
  words: [],
  rules: {},
  dialect: null,
  ...own,
});

const mock = vi.hoisted(() => ({
  proofreading: {
    setup: null as unknown,
    catalog: vi.fn(),
    refreshSetup: vi.fn(),
    setRule: vi.fn(),
    setDialect: vi.fn(),
    removeWord: vi.fn(),
  },
}));
vi.mock("@/lib/stores/proofreading.svelte", () => mock);

import ProofreadingSection from "./ProofreadingSection.svelte";

beforeEach(() => {
  const setup: ProofreadingSetup = {
    words: ["Zorn"],
    word_layers: {},
    rules: {},
    rule_layers: {},
    dialect: "american",
    ignored: {},
    layers: [
      layer("lib", "Library", { rules: { Hedging: false } }),
      layer("machine", "Machine"),
      layer("book", "Book 1", { words: ["Zorn"] }),
    ],
  };
  mock.proofreading.setup = setup;
  mock.proofreading.catalog.mockResolvedValue([
    { label: "Style", description: "", rules: [{ name: "Hedging", label: "Hedging", description: "Avoid hedges.", default: true }] },
  ]);
  mock.proofreading.refreshSetup.mockResolvedValue(undefined);
  mock.proofreading.removeWord.mockResolvedValue(undefined);
});

describe("ProofreadingSection", () => {
  it("asks for a project when none is open", () => {
    render(ProofreadingSection, { props: { projectOpen: false } });
    expect(screen.getByText("Open a project to set up proofreading.")).toBeInTheDocument();
    expect(mock.proofreading.catalog).not.toHaveBeenCalled();
  });

  it("lists the layers, defaults to the project, and shows who decided an inherited rule", async () => {
    render(ProofreadingSection, { props: { projectOpen: true } });
    const select = (await screen.findByLabelText("Level")) as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent?.trim())).toEqual(["Library", "Machine", "Book 1"]);
    expect(select.value).toBe("book");
    await fireEvent.click(screen.getByRole("button", { name: /Style/ }));
    expect(screen.getByText("Off — set by Library")).toBeInTheDocument();
  });

  it("shows the Library read-only", async () => {
    render(ProofreadingSection, { props: { projectOpen: true } });
    const select = (await screen.findByLabelText("Level")) as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: "lib" } });
    expect(screen.getByText(/read-only/)).toBeInTheDocument();
    expect(screen.getByLabelText("Dialect")).toBeDisabled();
  });

  it("removes a word at the selected level", async () => {
    render(ProofreadingSection, { props: { projectOpen: true } });
    await fireEvent.click(await screen.findByRole("button", { name: "Remove Zorn" }));
    expect(mock.proofreading.removeWord).toHaveBeenCalledWith("Zorn", "book");
  });

  it("shows a failed write inline", async () => {
    mock.proofreading.removeWord.mockRejectedValue(new Error("disk full"));
    render(ProofreadingSection, { props: { projectOpen: true } });
    await fireEvent.click(await screen.findByRole("button", { name: "Remove Zorn" }));
    expect(await screen.findByText("disk full")).toBeInTheDocument();
  });
});
