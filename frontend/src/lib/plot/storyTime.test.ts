// Pure story-time helpers (ADR-0097 §5, §8): the swap anchors the card menu offers, the
// anchor that undoes a move, the late-cause flag, and the persisted view choice.
import { describe, expect, it } from "vitest";
import {
  inStoryOrder,
  isStoryNoOp,
  lateCauseTitle,
  lateCausesByEffect,
  loadBoardView,
  saveBoardView,
  storyRestoreAnchor,
  storySwapAnchors,
} from "./storyTime";
import type { PlotBoardCard } from "@/lib/types";

const card = (id: string, story_order: number, over: Partial<PlotBoardCard> = {}): PlotBoardCard => ({
  id,
  title: id.toUpperCase(),
  synopsis: "",
  plotline: null,
  scene: null,
  container: null,
  page_status: null,
  beats: [],
  sequence: null,
  causal_links: [],
  story_order,
  story_movable: true,
  ...over,
});

describe("story order and swaps", () => {
  const cards = [card("c", 2), card("a", 0), card("b", 1), card("x", 3, { story_movable: false })];

  it("orders by story_order", () => {
    expect(inStoryOrder(cards).map((c) => c.id)).toEqual(["a", "b", "c", "x"]);
  });

  it("swaps with the neighbour, hiding an end and an inherited neighbour", () => {
    const ordered = inStoryOrder(cards);
    expect(storySwapAnchors(ordered, "b")).toEqual({ earlier: { before_id: "a" }, later: { after_id: "c" } });
    expect(storySwapAnchors(ordered, "a")).toEqual({ earlier: null, later: { after_id: "b" } });
    expect(storySwapAnchors(ordered, "c")).toEqual({ earlier: { before_id: "b" }, later: null });
    expect(storySwapAnchors(ordered, "x")).toEqual({ earlier: null, later: null });
  });

  it("restores after the predecessor, or before the successor for the first card", () => {
    expect(storyRestoreAnchor(cards, "c")).toEqual({ after_id: "b" });
    expect(storyRestoreAnchor(cards, "a")).toEqual({ before_id: "b" });
    expect(storyRestoreAnchor([card("only", 0)], "only")).toBeNull();
  });

  it("knows a move that changes nothing", () => {
    expect(isStoryNoOp(cards, "b", { after_id: "a" })).toBe(true);
    expect(isStoryNoOp(cards, "b", { before_id: "c" })).toBe(true);
    expect(isStoryNoOp(cards, "b", { after_id: "c" })).toBe(false);
  });
});

describe("late causes", () => {
  it("names the causes that happen after their effect, by effect id", () => {
    const cards = [
      card("e", 0),
      card("late", 2, { causal_links: ["e"] }),
      card("early", 0, { causal_links: ["late"] }),
    ];
    const late = lateCausesByEffect(cards);
    expect([...late.keys()]).toEqual(["e"]);
    expect(late.get("e")).toEqual(["LATE"]);
  });

  it("ignores manuscript order and self links", () => {
    const cards = [card("a", 0, { sequence: 9, causal_links: ["b", "a"] }), card("b", 1, { sequence: 1 })];
    expect(lateCausesByEffect(cards).size).toBe(0);
  });

  it("titles the pill with the cause names", () => {
    expect(lateCauseTitle(["Ledger", ""])).toBe("Caused by “Ledger”, “Untitled card”, which happens later");
  });
});

describe("view preference", () => {
  const memory = () => {
    const map = new Map<string, string>();
    return { getItem: (k: string) => map.get(k) ?? null, setItem: (k: string, v: string) => void map.set(k, v) };
  };

  it("defaults to the board and round-trips the story view", () => {
    const storage = memory();
    expect(loadBoardView(storage)).toBe("board");
    saveBoardView("story", storage);
    expect(loadBoardView(storage)).toBe("story");
  });

  it("degrades to the board when storage throws or is absent", () => {
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    };
    expect(loadBoardView(broken)).toBe("board");
    expect(() => saveBoardView("story", broken)).not.toThrow();
    expect(loadBoardView(null)).toBe("board");
  });
});
