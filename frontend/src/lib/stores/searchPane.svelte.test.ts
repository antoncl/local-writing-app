// ADR-0085 §3 (slice 2): the controller's own contract — the empty-query
// short-circuit, the stale-response guard (a fast second keystroke must never
// show the first's hits), and that an option toggle fires with the option set.
// §4/§5 (slice 3): eligibility, replace/replaceOne/replaceAll, and the counts
// summary — against `deps` stubs, never the real editorPanes/confirmService.
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { ReplaceResponse, SearchHit } from "@/lib/types";

vi.mock("@/lib/api", () => ({ api: { search: vi.fn(), replace: vi.fn() } }));
import { api } from "@/lib/api";
import { SearchPaneController, type SearchPaneDeps } from "./searchPane.svelte";

const run = (action: () => Promise<void>) => action().then(() => true);

function hit(file_id: string, overrides: Partial<SearchHit> = {}): SearchHit {
  return {
    kind: "manuscript",
    file_id,
    path: "p",
    line: 1,
    excerpt: "x",
    field: "body",
    start: 0,
    end: 3,
    revision: "rev1",
    owned: true,
    text: "abc",
    ...overrides,
  };
}

function fakeDeps(overrides: Partial<SearchPaneDeps> = {}): SearchPaneDeps {
  return {
    isDirtyOpen: vi.fn(() => false),
    reconcile: vi.fn(async () => {}),
    confirm: vi.fn(async () => true),
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.search).mockReset();
  vi.mocked(api.replace).mockReset();
});

describe("SearchPaneController", () => {
  it("fire() with an empty query and TODOs off makes no request and clears hits", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    c.hits = [hit("stale")];

    await c.fire();

    expect(api.search).not.toHaveBeenCalled();
    expect(c.hits).toEqual([]);
    expect(c.lastQuery).toBe("");
    expect(c.searched).toBe(false);
  });

  it("drops a stale response that resolves after a later query's response", async () => {
    let resolveFirst!: (value: { query: string; hits: SearchHit[] }) => void;
    let resolveSecond!: (value: { query: string; hits: SearchHit[] }) => void;
    const first = new Promise<{ query: string; hits: SearchHit[] }>((resolve) => {
      resolveFirst = resolve;
    });
    const second = new Promise<{ query: string; hits: SearchHit[] }>((resolve) => {
      resolveSecond = resolve;
    });
    vi.mocked(api.search).mockReturnValueOnce(first).mockReturnValueOnce(second);

    const c = new SearchPaneController(run, fakeDeps());
    c.query = "a";
    void c.fire();
    c.query = "ab";
    void c.fire();

    // The SECOND fire's response lands first...
    resolveSecond({ query: "ab", hits: [hit("y")] });
    await Promise.resolve();
    await Promise.resolve();
    // ...then the FIRST (superseded) fire's response lands late.
    resolveFirst({ query: "a", hits: [hit("x")] });
    await Promise.resolve();
    await Promise.resolve();

    expect(c.hits).toEqual([hit("y")]);
  });

  it("swallows a superseded rejection but rethrows a current one to run", async () => {
    // `run` here is a wrapper that catches and records, so the assertions can
    // tell "no error reached run" apart from "an error reached run".
    const calls: Array<"ok" | "error"> = [];
    const recordingRun = async (action: () => Promise<void>) => {
      try {
        await action();
        calls.push("ok");
        return true;
      } catch {
        calls.push("error");
        return false;
      }
    };

    let rejectFirst!: (error: Error) => void;
    let resolveSecond!: (value: { query: string; hits: SearchHit[] }) => void;
    const first = new Promise<{ query: string; hits: SearchHit[] }>((_resolve, reject) => {
      rejectFirst = reject;
    });
    const second = new Promise<{ query: string; hits: SearchHit[] }>((resolve) => {
      resolveSecond = resolve;
    });
    vi.mocked(api.search).mockReturnValueOnce(first).mockReturnValueOnce(second);

    const c = new SearchPaneController(recordingRun, fakeDeps());
    c.query = "a";
    const firstFire = c.fire();
    c.query = "ab";
    const secondFire = c.fire();

    // The current (second) query resolves...
    resolveSecond({ query: "ab", hits: [hit("y")] });
    await secondFire;
    // ...then the superseded (first) query rejects late — swallowed, not
    // surfaced through `run`.
    rejectFirst(new Error("boom"));
    await firstFire;

    expect(calls).toEqual(["ok", "ok"]);

    // A rejection of the CURRENT call still reaches `run`.
    vi.mocked(api.search).mockReset();
    vi.mocked(api.search).mockRejectedValueOnce(new Error("boom again"));
    const c2 = new SearchPaneController(recordingRun, fakeDeps());
    c2.query = "z";
    await c2.fire();

    expect(calls).toEqual(["ok", "ok", "error"]);
  });

  it("setMatchCase(true) fires with match_case: true", async () => {
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: [] });
    const c = new SearchPaneController(run, fakeDeps());
    c.query = "a";

    c.setMatchCase(true);
    await Promise.resolve();
    await Promise.resolve();

    expect(api.search).toHaveBeenCalledWith({
      query: "a",
      match_case: true,
      whole_word: false,
      kinds: null,
      include_open_todos: false,
    });
  });
});

describe("SearchPaneController.eligibility (ADR-0085 §4/§5)", () => {
  it("an owned body hit is ok", () => {
    const c = new SearchPaneController(run, fakeDeps());
    expect(c.eligibility(hit("a"))).toBe("ok");
  });

  it("an unowned (inherited) hit is inherited", () => {
    const c = new SearchPaneController(run, fakeDeps());
    expect(c.eligibility(hit("a", { owned: false }))).toBe("inherited");
  });

  it("a metadata-field hit is metadata", () => {
    const c = new SearchPaneController(run, fakeDeps());
    expect(c.eligibility(hit("a", { field: "metadata" }))).toBe("metadata");
  });

  it("a hit open dirty in an editor pane is dirty", () => {
    const deps = fakeDeps({ isDirtyOpen: vi.fn(() => true) });
    const c = new SearchPaneController(run, deps);
    const h = hit("a");
    expect(c.eligibility(h)).toBe("dirty");
    expect(deps.isDirtyOpen).toHaveBeenCalledWith(h.file_id, h.kind, h.entry_type);
  });

  it("a TODO hit is todo, regardless of field/owned", () => {
    const c = new SearchPaneController(run, fakeDeps());
    expect(c.eligibility(hit("a", { todo_id: "todo_1" }))).toBe("todo");
  });
});

describe("SearchPaneController.replaceOne / replace (ADR-0085 §4)", () => {
  function response(overrides: Partial<ReplaceResponse> = {}): ReplaceResponse {
    return { outcomes: [], replaced_nodes: 0, ...overrides };
  }

  it("posts exactly {replacement, hits:[ref]} with text/revision from the hit", async () => {
    const deps = fakeDeps();
    const c = new SearchPaneController(run, deps);
    c.replacement = "Aetherion";
    vi.mocked(api.replace).mockResolvedValue(response());
    vi.mocked(api.search).mockResolvedValue({ query: "", hits: [] });
    const h = hit("a", { start: 5, end: 8, text: "Aet", revision: "rev5" });

    await c.replaceOne(h);

    expect(api.replace).toHaveBeenCalledWith({
      replacement: "Aetherion",
      hits: [{ file_id: "a", field: "body", start: 5, end: 8, text: "Aet", revision: "rev5" }],
    });
  });

  it("reconciles a replaced node exactly once and not a stale one, then re-fires the search", async () => {
    const deps = fakeDeps();
    const c = new SearchPaneController(run, deps);
    c.query = "old";
    vi.mocked(api.search).mockResolvedValue({ query: "old", hits: [] });
    vi.mocked(api.replace).mockResolvedValue(
      response({
        outcomes: [
          { file_id: "a", start: 0, end: 3, status: "replaced", revision: "rev2" },
          { file_id: "b", start: 0, end: 3, status: "stale", reason: "changed" },
        ],
        replaced_nodes: 1,
      }),
    );

    await c.replace([hit("a", { kind: "lore", entry_type: "lore:character" }), hit("b")]);

    expect(deps.reconcile).toHaveBeenCalledTimes(1);
    expect(deps.reconcile).toHaveBeenCalledWith("a", "lore", "lore:character");
    expect(api.search).toHaveBeenCalled();
    expect(c.lastReplace).toEqual({ replaced: 1, stale: 1, skipped: 0, rejected: 0, detail: null, nodes: 1 });
  });

  it("counts a not_replaceable outcome as skipped", async () => {
    const deps = fakeDeps();
    const c = new SearchPaneController(run, deps);
    c.query = "old";
    vi.mocked(api.search).mockResolvedValue({ query: "old", hits: [] });
    vi.mocked(api.replace).mockResolvedValue(
      response({
        outcomes: [{ file_id: "a", start: 0, end: 3, status: "not_replaceable", reason: "kind" }],
        replaced_nodes: 0,
      }),
    );

    await c.replaceOne(hit("a"));

    expect(c.lastReplace).toEqual({ replaced: 0, stale: 0, skipped: 1, rejected: 0, detail: null, nodes: 0 });
    expect(deps.reconcile).not.toHaveBeenCalled();
  });

  it("counts a not_replaceable/rejected outcome separately and carries its detail", async () => {
    const deps = fakeDeps();
    const c = new SearchPaneController(run, deps);
    c.query = "old";
    vi.mocked(api.search).mockResolvedValue({ query: "old", hits: [] });
    vi.mocked(api.replace).mockResolvedValue(
      response({
        outcomes: [
          { file_id: "a", start: 0, end: 3, status: "not_replaceable", reason: "rejected", detail: "no" },
        ],
        replaced_nodes: 0,
      }),
    );

    await c.replaceOne(hit("a"));

    expect(c.lastReplace).toEqual({ replaced: 0, stale: 0, skipped: 0, rejected: 1, detail: "no", nodes: 0 });
  });

  it("carries the FIRST rejected outcome's detail when several nodes are rejected", async () => {
    const deps = fakeDeps();
    const c = new SearchPaneController(run, deps);
    c.query = "old";
    vi.mocked(api.search).mockResolvedValue({ query: "old", hits: [] });
    vi.mocked(api.replace).mockResolvedValue(
      response({
        outcomes: [
          { file_id: "a", start: 0, end: 3, status: "not_replaceable", reason: "rejected", detail: "first" },
          { file_id: "b", start: 0, end: 3, status: "not_replaceable", reason: "rejected", detail: "second" },
        ],
        replaced_nodes: 0,
      }),
    );

    await c.replace([hit("a"), hit("b")]);

    expect(c.lastReplace).toEqual({ replaced: 0, stale: 0, skipped: 0, rejected: 2, detail: "first", nodes: 0 });
  });

  it("replace([]) is a no-op", async () => {
    const deps = fakeDeps();
    const c = new SearchPaneController(run, deps);
    await c.replace([]);
    expect(api.replace).not.toHaveBeenCalled();
  });
});

describe("SearchPaneController.replaceAll (ADR-0085 §4)", () => {
  it("confirms before replacing when more than one hit is eligible", async () => {
    const deps = fakeDeps({ confirm: vi.fn(async () => true) });
    const c = new SearchPaneController(run, deps);
    c.lastQuery = "Aetheria";
    c.hits = [hit("a"), hit("b")];
    vi.mocked(api.search).mockResolvedValue({ query: "Aetheria", hits: [] });
    vi.mocked(api.replace).mockResolvedValue({ outcomes: [], replaced_nodes: 0 });

    await c.replaceAll();

    expect(deps.confirm).toHaveBeenCalledWith(2, 2, "Aetheria");
    expect(api.replace).toHaveBeenCalled();
  });

  it("posts nothing when the confirm is declined", async () => {
    const deps = fakeDeps({ confirm: vi.fn(async () => false) });
    const c = new SearchPaneController(run, deps);
    c.hits = [hit("a"), hit("b")];

    await c.replaceAll();

    expect(api.replace).not.toHaveBeenCalled();
  });

  it("does not confirm for a single eligible hit", async () => {
    const deps = fakeDeps();
    const c = new SearchPaneController(run, deps);
    c.hits = [hit("a")];
    vi.mocked(api.search).mockResolvedValue({ query: "", hits: [] });
    vi.mocked(api.replace).mockResolvedValue({ outcomes: [], replaced_nodes: 0 });

    await c.replaceAll();

    expect(deps.confirm).not.toHaveBeenCalled();
    expect(api.replace).toHaveBeenCalled();
  });

  it("only sends currently-eligible hits (dirty/inherited/metadata/todo excluded)", async () => {
    const deps = fakeDeps({ isDirtyOpen: vi.fn((id: string) => id === "dirty1") });
    const c = new SearchPaneController(run, deps);
    c.hits = [
      hit("ok1"),
      hit("dirty1"),
      hit("inherited1", { owned: false }),
      hit("meta1", { field: "metadata" }),
      hit("todo1", { todo_id: "t1" }),
    ];
    vi.mocked(api.search).mockResolvedValue({ query: "", hits: [] });
    vi.mocked(api.replace).mockResolvedValue({ outcomes: [], replaced_nodes: 0 });

    await c.replaceAll();

    expect(api.replace).toHaveBeenCalledWith(
      expect.objectContaining({ hits: [expect.objectContaining({ file_id: "ok1" })] }),
    );
  });
});

describe("SearchPaneController reveal window (#1868)", () => {
  // 150 manuscript + 5 lore hits — manuscript's own window fills a full
  // REVEAL_BATCH, lore's window (5) doesn't, so lore is fully visible from
  // the first render (review finding A).
  function mixedHits(): SearchHit[] {
    return [
      ...Array.from({ length: 150 }, (_, i) => hit("m" + i)),
      ...Array.from({ length: 5 }, (_, i) => hit("l" + i, { kind: "lore" })),
    ];
  }

  it("every kind gets its own group + window from the first render", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: mixedHits() });
    c.query = "a";

    await c.fire();

    // `orderKinds`' KIND_ORDER lists lore before manuscript; the order isn't
    // the point of this test — both groups being present with the right
    // per-group window/total is.
    expect(c.groups.map((g) => g.kind).sort()).toEqual(["lore", "manuscript"]);
    const manuscript = c.groups.find((g) => g.kind === "manuscript");
    const lore = c.groups.find((g) => g.kind === "lore");
    expect(manuscript?.hits.length).toBe(100);
    expect(manuscript?.total).toBe(150);
    expect(lore?.hits.length).toBe(5);
    expect(lore?.total).toBe(5);
    expect(c.eligibleHits.length).toBe(155);
  });

  it("revealMore(kind) extends only that kind's window and clamps; a further call and an already-full kind are no-ops", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: mixedHits() });
    c.query = "a";
    await c.fire();

    c.revealMore("manuscript");
    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(150);
    expect(c.groups.find((g) => g.kind === "lore")?.hits.length).toBe(5);

    c.revealMore("manuscript");
    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(150);

    c.revealMore("lore");
    expect(c.groups.find((g) => g.kind === "lore")?.hits.length).toBe(5);
  });

  it("revealMore(kind) extends by REVEAL_BATCH, not to everything at once", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: Array.from({ length: 250 }, (_, i) => hit("f" + i)) });
    c.query = "a";
    await c.fire();

    c.revealMore("manuscript");
    expect(c.groups[0].hits.length).toBe(200);
    c.revealMore("manuscript");
    expect(c.groups[0].hits.length).toBe(250);
  });

  it("a changed query resets every group's window back to REVEAL_BATCH", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: mixedHits() });
    c.query = "a";
    await c.fire();
    c.revealMore("manuscript");
    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(150);

    vi.mocked(api.search).mockResolvedValue({ query: "b", hits: mixedHits() });
    c.query = "b";
    await c.fire();

    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(100);
  });

  it("re-firing the SAME query/options (a replace re-run) keeps the revealed window", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: mixedHits() });
    c.query = "a";
    await c.fire();
    c.revealMore("manuscript");
    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(150);

    // Same query text and options as the previous fire.
    await c.fire();

    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(150);
  });

  it("setMatchCase(true) with the same text resets the revealed window", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: mixedHits() });
    c.query = "a";
    await c.fire();
    c.revealMore("manuscript");
    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(150);

    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: mixedHits() });
    c.setMatchCase(true);
    await Promise.resolve();
    await Promise.resolve();

    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(100);
  });

  it("setIncludeOpenTodos(true) with the same text resets the revealed window (finding C)", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: mixedHits() });
    c.query = "a";
    await c.fire();
    c.revealMore("manuscript");
    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(150);

    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: mixedHits() });
    c.setIncludeOpenTodos(true);
    await Promise.resolve();
    await Promise.resolve();

    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(100);
  });

  it("the empty-query short-circuit branch resets visibleByKind and groups", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: mixedHits() });
    c.query = "a";
    await c.fire();
    c.revealMore("manuscript");
    expect(c.groups.find((g) => g.kind === "manuscript")?.hits.length).toBe(150);

    c.query = "";
    await c.fire();

    expect(c.visibleByKind).toEqual({});
    expect(c.groups).toEqual([]);
  });

  it("the project kind sorts last even when its hits come first in the response", async () => {
    const c = new SearchPaneController(run, fakeDeps());
    vi.mocked(api.search).mockResolvedValue({
      query: "a",
      // "widget" is unknown to orderKinds and sorts after "project" alphabetically,
      // so only the explicit project-last rule puts project at the end.
      hits: [hit("p1", { kind: "project" }), hit("w1", { kind: "widget" }), hit("m1", { kind: "manuscript" })],
    });
    c.query = "a";

    await c.fire();

    expect(c.groups.map((g) => g.kind)).toEqual(["manuscript", "widget", "project"]);
  });
});
