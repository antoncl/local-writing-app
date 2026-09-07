// @vitest-environment happy-dom
// Search pane render contract (#979), rewritten for as-you-type (ADR-0085 §3,
// slice 2) and replace (§4/§5, slice 3): the Find button is gone, so every
// search trigger below is either typing (debounced by `SearchInput`, advanced
// with fake timers) or Enter (immediate). This still guards the #724 "fetches
// fine, renders nothing" class — hits must actually reach the DOM, a click
// must open one, and an empty query must never waste a request.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import Search from "./Search.svelte";
import { api } from "@/lib/api";
import type { SearchHit } from "@/lib/types";

// Search imports `api` and calls `api.search`/`api.replace` directly; mock the
// module so the pane runs offline and we control the hits/outcomes.
vi.mock("@/lib/api", () => ({ api: { search: vi.fn(), replace: vi.fn() } }));
// The pane's replace deps (ADR-0085 §5) resolve through these two stores —
// mocked the same way `api` is, so the render tests never touch the real
// editor-pane surface or the confirm modal.
vi.mock("@/lib/stores/editorPanes.svelte", () => ({
  editorPanes: {
    isNodeOpenDirty: vi.fn(() => false),
    reconcileNodeFromServer: vi.fn(async () => {}),
  },
}));
vi.mock("@/lib/stores/confirmService.svelte", () => ({
  confirmService: { request: vi.fn() },
}));

// App's error-catching async wrapper — here a passthrough that just runs the action.
const run = (action: () => Promise<void>) => action().then(() => true);

function hit(
  path: string,
  line: number,
  excerpt: string,
  kind = "manuscript",
  overrides: Partial<SearchHit> = {},
): SearchHit {
  return {
    kind,
    file_id: `f_${path}`,
    path,
    line,
    excerpt,
    field: "body",
    start: 0,
    end: excerpt.length,
    revision: "rev1",
    owned: true,
    text: excerpt,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.search).mockReset();
  vi.mocked(api.replace).mockReset();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  delete (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;
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

  it("Enter cancels the pending debounce so the delayed onChange never double-fires", async () => {
    vi.mocked(api.search).mockResolvedValue({ query: "arrival", hits: [] });
    render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "arrival" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    // No tick between input and Enter: the debounced onChange is still
    // pending when Enter fires. It must be cancelled, not merely raced.
    vi.advanceTimersByTime(300);
    await tick();

    expect(api.search).toHaveBeenCalledTimes(1);
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

    // `getAllByText` already matches on the element's OWN text nodes (not its
    // descendants, per dom-testing-library's `getNodeText`), so it still finds
    // exactly the label divs and ignores the count span (#1868) added inside
    // them. `.textContent`, unlike the query, DOES include that span's text
    // (e.g. "Scenes 1"), so the assertion reads the same own-text-only slice
    // the query used, instead of the label element's full `textContent`.
    const labels = screen
      .getAllByText(/^(Scenes|Plot|Research|Project|Widget)$/)
      .map((el) =>
        Array.from(el.childNodes)
          .filter((n) => n.nodeType === Node.TEXT_NODE)
          .map((n) => n.textContent)
          .join("")
          .trim(),
      );
    expect(labels).toEqual(["Scenes", "Plot", "Research", "Widget", "Project"]);
  });

  it("highlights only the exact match under Match case + Whole word (ADR-0085 §3)", async () => {
    // "Aetherian" contains "Aetheria" as a prefix — Match case alone would
    // still mark it, so this exercises both toggles together.
    const excerpt = "Aetheria rose. aetheria fell. The Aetherian guard slept.";
    vi.mocked(api.search).mockResolvedValue({
      query: "Aetheria",
      hits: [hit("scenes/act-1/arrival.md", 12, excerpt)],
    });
    const { container } = render(Search, { props: { run, onOpenHit: () => {} } });

    await fireEvent.click(screen.getByRole("checkbox", { name: "Match case" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Whole word" }));
    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "Aetheria" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(1);
    expect(marks[0].textContent).toBe("Aetheria");
  });

  it("highlights every case/prefix variant with neither toggle on", async () => {
    const excerpt = "Aetheria rose. aetheria fell. The Aetherian guard slept.";
    vi.mocked(api.search).mockResolvedValue({
      query: "aetheria",
      hits: [hit("scenes/act-1/arrival.md", 12, excerpt)],
    });
    const { container } = render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "aetheria" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(3);
  });

  it("does not query on an empty search with TODOs off", async () => {
    render(Search, { props: { run, onOpenHit: () => {} } });
    vi.advanceTimersByTime(300);
    await tick();
    expect(api.search).not.toHaveBeenCalled();
  });
});

describe("Search pane — replace (ADR-0085 §4/§5)", () => {
  it("shows the eligible count on Replace all and disables it at zero", async () => {
    render(Search, { props: { run, onOpenHit: () => {} } });
    expect(screen.getByRole("button", { name: "Replace all (0)" })).toBeDisabled();

    vi.mocked(api.search).mockResolvedValue({
      query: "aetheria",
      hits: [hit("scenes/act-1/arrival.md", 12, "Aetheria at dawn.")],
    });
    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "aetheria" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    expect(screen.getByRole("button", { name: "Replace all (1)" })).not.toBeDisabled();
  });

  it("previews <del>+<ins> for an eligible hit and leaves <mark> for an inherited one", async () => {
    vi.mocked(api.search).mockResolvedValue({
      query: "aetheria",
      hits: [
        hit("scenes/act-1/arrival.md", 12, "Aetheria at dawn.", "manuscript"),
        hit("lore/places/aetheria.md", 1, "Aetheria the city", "lore", { owned: false }),
      ],
    });
    const { container } = render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "aetheria" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    await fireEvent.input(screen.getByPlaceholderText("Replace with"), {
      target: { value: "Aetherion" },
    });
    await tick();

    expect(container.querySelectorAll(".search-ins")).toHaveLength(1);
    expect(container.querySelector(".search-ins")?.textContent).toBe("Aetherion");
    expect(container.querySelectorAll(".search-del")).toHaveLength(1);
    // The inherited hit still shows the plain highlight, not a preview.
    expect(container.querySelectorAll("mark")).toHaveLength(1);
  });

  it("shows the inherited note instead of a Replace button", async () => {
    vi.mocked(api.search).mockResolvedValue({
      query: "aetheria",
      hits: [hit("lore/places/aetheria.md", 1, "Aetheria the city", "lore", { owned: false })],
    });
    render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "aetheria" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    expect(screen.getByText("inherited — not replaceable here")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Replace" })).not.toBeInTheDocument();
  });

  it("clicking a hit's Replace posts to api.replace and does not open the hit", async () => {
    const h = hit("scenes/act-1/arrival.md", 12, "Aetheria at dawn.");
    vi.mocked(api.search).mockResolvedValue({ query: "aetheria", hits: [h] });
    vi.mocked(api.replace).mockResolvedValue({
      outcomes: [{ file_id: h.file_id, start: h.start, end: h.end, status: "replaced", revision: "rev2" }],
      replaced_nodes: 1,
    });
    const onOpenHit = vi.fn();
    render(Search, { props: { run, onOpenHit } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "aetheria" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    vi.mocked(api.search).mockResolvedValue({ query: "aetheria", hits: [] });
    await fireEvent.click(screen.getByRole("button", { name: "Replace" }));
    await tick();

    expect(api.replace).toHaveBeenCalledWith({
      replacement: "",
      hits: [{ file_id: h.file_id, field: "body", start: h.start, end: h.end, text: h.text, revision: h.revision }],
    });
    expect(onOpenHit).not.toHaveBeenCalled();
  });

  it("shows a rejected outcome's detail in the summary line", async () => {
    // Fix 2 (#1846): a save's own refusal (e.g. a 422 the scene's own save
    // raised) becomes a `not_replaceable/rejected` outcome, with the save's
    // human message as `detail` — surfaced in the summary line, not swallowed
    // into the generic "not replaceable" count.
    const h = hit("scenes/act-1/arrival.md", 12, "Aetheria at dawn.");
    vi.mocked(api.search).mockResolvedValue({ query: "aetheria", hits: [h] });
    vi.mocked(api.replace).mockResolvedValue({
      outcomes: [
        { file_id: h.file_id, start: h.start, end: h.end, status: "not_replaceable", reason: "rejected", detail: "Scene Markdown must not contain raw HTML." },
      ],
      replaced_nodes: 0,
    });
    render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "aetheria" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    vi.mocked(api.search).mockResolvedValue({ query: "aetheria", hits: [] });
    await fireEvent.click(screen.getByRole("button", { name: "Replace" }));
    await tick();

    expect(
      screen.getByText("1 rejected: Scene Markdown must not contain raw HTML."),
    ).toBeInTheDocument();
  });
});

describe("Search pane — lazy reveal (#1868)", () => {
  function manyHits(n: number): SearchHit[] {
    return Array.from({ length: n }, (_, i) => hit(`s${i}`, i, `excerpt ${i}`, "manuscript"));
  }

  // A minimal IntersectionObserver stub: the constructor stores the callback
  // and every instance is tracked, so a test can grab the LATEST one (the
  // pane's effect re-creates the observer after every reveal) and fire it by
  // hand — happy-dom has no real IntersectionObserver.
  class FakeIntersectionObserver {
    static instances: FakeIntersectionObserver[] = [];
    callback: (entries: { isIntersecting: boolean }[]) => void;
    constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
      this.callback = callback;
      FakeIntersectionObserver.instances.push(this);
    }
    observe(): void {}
    disconnect(): void {}
  }

  it("renders only the first 100 rows of 250 hits, with the counts visible", async () => {
    vi.mocked(api.search).mockResolvedValue({ query: "s", hits: manyHits(250) });
    const { container } = render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "s" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    expect(screen.getAllByText(/^s\d+:\d+$/)).toHaveLength(100);
    expect(container.querySelectorAll(".node-row")).toHaveLength(100);
    expect(screen.getByText("250 matches")).toBeInTheDocument();
    expect(screen.getByText("Showing 100 of 250")).toBeInTheDocument();
    expect(container.querySelector(".search-group-count")?.textContent).toBe("250");
  });

  it("Show more reveals the next batch, then the rest, and the sentinel/button disappears", async () => {
    vi.mocked(api.search).mockResolvedValue({ query: "s", hits: manyHits(250) });
    const { container } = render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "s" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    await fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await tick();
    expect(container.querySelectorAll(".node-row")).toHaveLength(200);
    expect(screen.getByText("Showing 200 of 250")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await tick();
    expect(container.querySelectorAll(".node-row")).toHaveLength(250);
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
    expect(container.querySelector(".search-more")).not.toBeInTheDocument();
  });

  it("a single hit shows '1 match' and no Show more", async () => {
    vi.mocked(api.search).mockResolvedValue({ query: "s", hits: manyHits(1) });
    render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "s" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    expect(screen.getByText("1 match")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("reveals the next batch when the sentinel intersects, via IntersectionObserver", async () => {
    FakeIntersectionObserver.instances = [];
    (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver = FakeIntersectionObserver;
    vi.mocked(api.search).mockResolvedValue({ query: "s", hits: manyHits(250) });
    const { container } = render(Search, { props: { run, onOpenHit: () => {} } });

    const input = screen.getByPlaceholderText("Find in the project");
    await fireEvent.input(input, { target: { value: "s" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    await tick();

    const latest = FakeIntersectionObserver.instances[FakeIntersectionObserver.instances.length - 1];
    latest.callback([{ isIntersecting: true }]);
    await tick();

    expect(container.querySelectorAll(".node-row")).toHaveLength(200);
  });
});
