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

  it("shows the saved dialect again after a write fails", async () => {
    mock.proofreading.setDialect.mockRejectedValue(new Error("disk full"));
    render(ProofreadingSection, { props: { projectOpen: true } });
    const dialect = (await screen.findByLabelText("Dialect")) as HTMLSelectElement;
    await fireEvent.change(dialect, { target: { value: "british" } });
    expect(await screen.findByText("disk full")).toBeInTheDocument();
    expect(dialect.value).toBe("");
  });

  it("opens every matching group while searching, with heads that don't toggle", async () => {
    render(ProofreadingSection, { props: { projectOpen: true } });
    const head = await screen.findByRole("button", { name: /Style/ });
    expect(head.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.input(screen.getByLabelText("Search rules"), { target: { value: "hedg" } });
    const open = screen.getByRole("button", { name: /Style/ });
    expect(open.getAttribute("aria-expanded")).toBe("true");
    expect(open).toBeDisabled();
    await fireEvent.input(screen.getByLabelText("Search rules"), { target: { value: "" } });
    expect(screen.getByRole("button", { name: /Style/ }).getAttribute("aria-expanded")).toBe("false");
  });

  it("shows a failed write inline", async () => {
    mock.proofreading.removeWord.mockRejectedValue(new Error("disk full"));
    render(ProofreadingSection, { props: { projectOpen: true } });
    await fireEvent.click(await screen.findByRole("button", { name: "Remove Zorn" }));
    expect(await screen.findByText("disk full")).toBeInTheDocument();
  });
});
