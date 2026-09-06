// ADR-0085 §3 (slice 2): the controller's own contract — the empty-query
// short-circuit, the stale-response guard (a fast second keystroke must never
// show the first's hits), and that an option toggle fires with the option set.
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { SearchHit } from "@/lib/types";

vi.mock("@/lib/api", () => ({ api: { search: vi.fn() } }));
import { api } from "@/lib/api";
import { SearchPaneController } from "./searchPane.svelte";

const run = (action: () => Promise<void>) => action().then(() => true);

function hit(file_id: string): SearchHit {
  return {
    kind: "manuscript",
    file_id,
    path: "p",
    line: 1,
    excerpt: "x",
    field: "body",
    start: 0,
    end: 0,
    revision: "",
    owned: true,
  };
}

beforeEach(() => {
  vi.mocked(api.search).mockReset();
});

describe("SearchPaneController", () => {
  it("fire() with an empty query and TODOs off makes no request and clears hits", async () => {
    const c = new SearchPaneController(run);
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

    const c = new SearchPaneController(run);
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

    const c = new SearchPaneController(recordingRun);
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
    const c2 = new SearchPaneController(recordingRun);
    c2.query = "z";
    await c2.fire();

    expect(calls).toEqual(["ok", "ok", "error"]);
  });

  it("setMatchCase(true) fires with match_case: true", async () => {
    vi.mocked(api.search).mockResolvedValue({ query: "a", hits: [] });
    const c = new SearchPaneController(run);
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
