// @vitest-environment happy-dom
// Search pane render contract (#979). The store/query plumbing is trivial, but
// nothing mounted this pane before, so a regression that stopped results
// rendering — the #724 "fetches fine, renders nothing" class — was invisible to
// the logic tests and svelte-check. This asserts hits actually reach the DOM,
// that a click opens one, and that an empty query never wastes a request.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import Search from "./Search.svelte";
import { api } from "@/lib/api";
import type { SearchHit } from "@/lib/types";

// Search imports `api` and calls `api.search` directly; mock the module so the
// pane runs offline and we control the hits.
vi.mock("@/lib/api", () => ({ api: { search: vi.fn() } }));

// App's error-catching async wrapper — here a passthrough that just runs the action.
const run = (action: () => Promise<void>) => action().then(() => true);

function hit(path: string, line: number, excerpt: string): SearchHit {
  return { kind: "manuscript", file_id: `f_${path}`, path, line, excerpt };
}

beforeEach(() => {
  vi.mocked(api.search).mockReset();
});

describe("Search pane — results render", () => {
  it("renders each hit's path:line and excerpt after a search", async () => {
    vi.mocked(api.search).mockResolvedValue({
      query: "arrival",
      hits: [hit("scenes/act-1/arrival.md", 12, "The ship made planetfall at dawn.")],
    });
    render(Search, { props: { run, onOpenHit: () => {} } });

    await fireEvent.input(screen.getByPlaceholderText("Find in scenes and lore"), {
      target: { value: "arrival" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Find" }));
    await tick();

    expect(api.search).toHaveBeenCalledWith("arrival", false);
    // The row actually reaches the DOM — the thing a logic test cannot see.
    expect(screen.getByText("scenes/act-1/arrival.md:12")).toBeInTheDocument();
    expect(screen.getByText("The ship made planetfall at dawn.")).toBeInTheDocument();
  });

  it("searches on Enter in the field, not only on the Find button", async () => {
    // Regression guard: the NodeRow reduction (#1608) briefly relied on native
    // <form> implicit-submission for Enter, which a global key handler blocks in
    // the real app — so Enter found nothing while the Find button worked. Enter
    // is now handled explicitly on the input (SearchInput onEnter).
    vi.mocked(api.search).mockResolvedValue({
      query: "arrival",
      hits: [hit("scenes/act-1/arrival.md", 12, "The ship made planetfall at dawn.")],
    });
    render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in scenes and lore");
    await fireEvent.input(input, { target: { value: "arrival" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    expect(api.search).toHaveBeenCalledWith("arrival", false);
    expect(screen.getByText("scenes/act-1/arrival.md:12")).toBeInTheDocument();
  });

  it("renders hits that share file_id/line/path (regression: each_key_duplicate)", async () => {
    // A lore entry matching in >1 metadata field yields hits identical on
    // (file_id, line=1, path) — metadata hits are always line 1. A keyed each on
    // those fields collides; Svelte throws each_key_duplicate and drops the whole
    // group, so e.g. searching "Implant" (matches its title AND aliases) found
    // nothing. The list is unkeyed.
    vi.mocked(api.search).mockResolvedValue({
      query: "implant",
      hits: [
        hit("Lore / Implant metadata", 1, "title: Implant"),
        hit("Lore / Implant metadata", 1, "aliases: Implants, Neural interface"),
      ],
    });
    render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in scenes and lore");
    await fireEvent.input(input, { target: { value: "implant" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    // Both rows render (title is not highlighted, so the match is clean).
    expect(screen.getAllByText("Lore / Implant metadata:1")).toHaveLength(2);
  });

  it("opens a clicked hit through onOpenHit", async () => {
    const h = hit("lore/places/citadel.md", 3, "The citadel loomed over the plain.");
    vi.mocked(api.search).mockResolvedValue({ query: "citadel", hits: [h] });
    const onOpenHit = vi.fn();
    render(Search, { props: { run, onOpenHit } });

    await fireEvent.input(screen.getByPlaceholderText("Find in scenes and lore"), {
      target: { value: "citadel" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Find" }));
    await tick();

    await fireEvent.click(screen.getByText("lore/places/citadel.md:3"));
    expect(onOpenHit).toHaveBeenCalledWith(h);
  });

  it("does not query on an empty search with TODOs off", async () => {
    render(Search, { props: { run, onOpenHit: () => {} } });
    await fireEvent.click(screen.getByRole("button", { name: "Find" }));
    await tick();
    // The guard `!query.trim() && !includeOpenTodos` returns before any request.
    expect(api.search).not.toHaveBeenCalled();
  });
});
