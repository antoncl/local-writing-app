// @vitest-environment happy-dom
// Search pane render contract (#979), rewritten for as-you-type (ADR-0085 §3,
// slice 2): the Find button is gone, so every trigger below is either typing
// (debounced by `SearchInput`, advanced with fake timers) or Enter (immediate).
// This still guards the #724 "fetches fine, renders nothing" class — hits must
// actually reach the DOM, a click must open one, and an empty query must never
// waste a request.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

function hit(path: string, line: number, excerpt: string, kind = "manuscript"): SearchHit {
  return {
    kind,
    file_id: `f_${path}`,
    path,
    line,
    excerpt,
    field: "body",
    start: 0,
    end: 0,
    revision: "",
    owned: true,
  };
}

beforeEach(() => {
  vi.mocked(api.search).mockReset();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Search pane — results render", () => {
  it("fires a debounced search as the writer types and renders the hits", async () => {
    vi.mocked(api.search).mockResolvedValue({
      query: "arrival",
      hits: [hit("scenes/act-1/arrival.md", 12, "The ship made planetfall at dawn.")],
    });
    render(Search, { props: { run, onOpenHit: () => {} } });

    await fireEvent.input(screen.getByPlaceholderText("Find in the project"), {
      target: { value: "arrival" },
    });
    vi.advanceTimersByTime(200);
    await tick();
    await tick();

    expect(api.search).toHaveBeenCalledWith({
      query: "arrival",
      match_case: false,
      whole_word: false,
      kinds: null,
      include_open_todos: false,
    });
    // The row actually reaches the DOM — the thing a logic test cannot see.
    expect(screen.getByText("scenes/act-1/arrival.md:12")).toBeInTheDocument();
    expect(screen.getByText("The ship made planetfall at dawn.")).toBeInTheDocument();
  });

  it("searches on Enter in the field without waiting for the debounce", async () => {
    vi.mocked(api.search).mockResolvedValue({
      query: "arrival",
      hits: [hit("scenes/act-1/arrival.md", 12, "The ship made planetfall at dawn.")],
    });
    render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "arrival" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    // No vi.advanceTimersByTime: Enter must not depend on the debounce firing.
    await tick();

    expect(api.search).toHaveBeenCalledWith({
      query: "arrival",
      match_case: false,
      whole_word: false,
      kinds: null,
      include_open_todos: false,
    });
    expect(screen.getByText("scenes/act-1/arrival.md:12")).toBeInTheDocument();
  });

  it("re-fires with match_case: true when Match case is toggled", async () => {
    vi.mocked(api.search).mockResolvedValue({ query: "arrival", hits: [] });
    render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "arrival" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();
    vi.mocked(api.search).mockClear();

    await fireEvent.click(screen.getByRole("checkbox", { name: "Match case" }));
    await tick();

    expect(api.search).toHaveBeenCalledWith({
      query: "arrival",
      match_case: true,
      whole_word: false,
      kinds: null,
      include_open_todos: false,
    });
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

    const input = screen.getByPlaceholderText("Find in the project");
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

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "citadel" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    await fireEvent.click(screen.getByText("lore/places/citadel.md:3"));
    expect(onOpenHit).toHaveBeenCalledWith(h);
  });

  it("groups hits by kind, data-driven, with project last and an unknown kind still shown", async () => {
    // ADR-0085 §2: `kind` is the index's kind, not a closed three-entry set —
    // a plot/research/other hit must render under its own group, and an
    // entirely unrecognised kind must still show up (title-cased) rather than
    // vanish, with "project" (the synthetic TODO bucket) always last.
    vi.mocked(api.search).mockResolvedValue({
      query: "aetheria",
      hits: [
        hit("Project TODO", 1, "Ship the thing", "project"),
        hit("scenes/act-1/arrival.md", 12, "Aetheria at dawn.", "manuscript"),
        hit("Plot / Card A", 1, "Aetheria happens here", "plot"),
        hit("Research / Notes", 1, "Aetheria research", "research"),
        hit("Widget / Thing", 1, "Aetheria widget", "widget"),
      ],
    });
    render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "aetheria" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    const labels = screen.getAllByText(/^(Scenes|Plot|Research|Project|Widget)$/).map((el) => el.textContent);
    expect(labels).toEqual(["Scenes", "Plot", "Research", "Widget", "Project"]);
  });

  it("does not query on an empty search with TODOs off", async () => {
    render(Search, { props: { run, onOpenHit: () => {} } });
    vi.advanceTimersByTime(300);
    await tick();
    expect(api.search).not.toHaveBeenCalled();
  });
});
