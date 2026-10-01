/**
 * Plot content commands (ADR-0053 §7, #902) — the undoable board ops. Driven
 * through a fake `PlotCommandPort` (an in-memory card/plotline store + a call log),
 * so the builders and the recorder are exercised exactly as the caretaker + PlotEditor
 * drive them, without a backend. The pure referrer finders take a plain projection.
 */
import { describe, expect, it } from "vitest";
import {
  type CardRef,
  type PlotCommandPort,
  PlotUndoRecorder,
  attachCommand,
  cardEditCommand,
  cardTextCommand,
  detachCommand,
  cardEditManyCommand,
  cardsReferencingCard,
  cardsReferencingPlotline,
  createArcCommand,
  createCardCommand,
  createDeckCommand,
  createPlotlineCommand,
  deleteArcCommand,
  deleteCardCommand,
  deleteDeckCommand,
  deletePlotlineCommand,
  arcEditCommand,
  plotlineEditCommand,
  realizeCommand,
  seedCommand,
} from "./plotCommands";
import { UndoCancelled } from "@/lib/stores/undoCaretaker.svelte";
import type { CardState } from "@/lib/stores/plotBoard";
import type { PlotlineState } from "@/lib/stores/plotlines";
import type { ArcState } from "@/lib/stores/characterArcs";
import type { DeckState } from "@/lib/stores/decks";
import type { PlotBoardCard, PlotBoardProjection, StructureDocument, StructureNode } from "@/lib/types";

const cardState = (title: string, metadata: CardState["metadata"] = {}, body = ""): CardState => ({
  title,
  body,
  metadata,
});
const plotlineState = (title: string, metadata: PlotlineState["metadata"] = {}, body = ""): PlotlineState => ({
  title,
  body,
  metadata,
});
const arcState = (title: string, metadata: ArcState["metadata"] = {}, body = ""): ArcState => ({
  title,
  body,
  metadata,
});
const deckState = (title: string, metadata: DeckState["metadata"] = {}, body = ""): DeckState => ({
  title,
  body,
  metadata,
});

function fakePort() {
  const cards = new Map<string, CardState>();
  const plotlines = new Map<string, PlotlineState>();
  const arcs = new Map<string, ArcState>();
  const decks = new Map<string, DeckState>();
  // Scene model for the realize tests: body per scene + which cards reference each.
  const scenes = new Map<string, { title: string; body: string }>();
  const sceneRefs = new Map<string, Set<string>>();
  // Scene summaries, and what the next attach / detach reports back (null = no text
  // choice was needed; "cancelled" = the writer backed out of the ask).
  const summaries = new Map<string, string>();
  const outcome: { attach: "scene" | "card" | null | "cancelled"; detach: "scene" | "card" | null | "cancelled" } = {
    attach: null,
    detach: null,
  };
  let sceneCounter = 0;
  // The planned cards the next realize re-anchors, and the manuscript tree scene moves read.
  const realized: { reanchored: string[] } = { reanchored: [] };
  const manuscript: { doc: StructureDocument | null } = { doc: null };
  // What the (mocked) suppressible confirm resolves; flip per test.
  const confirm = { result: true };
  const calls: string[] = [];
  const port: PlotCommandPort = {
    deleteCard: async (id) => {
      calls.push(`deleteCard:${id}`);
      cards.delete(id);
    },
    getCardState: async (id) => structuredClone(cards.get(id)!),
    restoreCardState: async (id, s) => {
      calls.push(`restoreCard:${id}`);
      cards.set(id, structuredClone(s));
    },
    recreateCard: async (id, s) => {
      calls.push(`recreateCard:${id}`);
      cards.set(id, structuredClone(s));
    },
    deletePlotline: async (id) => {
      calls.push(`deletePlotline:${id}`);
      plotlines.delete(id);
    },
    getPlotlineState: async (id) => structuredClone(plotlines.get(id)!),
    restorePlotlineState: async (id, s) => {
      calls.push(`restorePlotline:${id}`);
      plotlines.set(id, structuredClone(s));
    },
    recreatePlotline: async (id, s) => {
      calls.push(`recreatePlotline:${id}`);
      plotlines.set(id, structuredClone(s));
    },
    deleteArc: async (id) => {
      calls.push(`deleteArc:${id}`);
      arcs.delete(id);
    },
    getArcState: async (id) => structuredClone(arcs.get(id)!),
    restoreArcState: async (id, s) => {
      calls.push(`restoreArc:${id}`);
      arcs.set(id, structuredClone(s));
    },
    recreateArc: async (id, s) => {
      calls.push(`recreateArc:${id}`);
      arcs.set(id, structuredClone(s));
    },
    deleteDeck: async (id) => {
      calls.push(`deleteDeck:${id}`);
      decks.delete(id);
    },
    getDeckState: async (id) => structuredClone(decks.get(id)!),
    restoreDeckState: async (id, s) => {
      calls.push(`restoreDeck:${id}`);
      decks.set(id, structuredClone(s));
    },
    recreateDeck: async (id, s) => {
      calls.push(`recreateDeck:${id}`);
      decks.set(id, structuredClone(s));
    },
    restoreCardDeck: async (cardId, deckId, written) => {
      calls.push(`cardDeck:${cardId}:${deckId}:${written ? "written" : "unwritten"}`);
    },
    refreshBoard: async () => {
      calls.push("refreshBoard");
    },
    refreshDeckRoster: async () => {
      calls.push("refreshDeckRoster");
    },
    refreshRoster: async () => {
      calls.push("refreshRoster");
    },
    refreshArcRoster: async () => {
      calls.push("refreshArcRoster");
    },
    realizeCard: async (cardId, _parentId) => {
      const id = `scene_${++sceneCounter}`;
      calls.push(`realize:${cardId}->${id}`);
      scenes.set(id, { title: `Scene for ${cardId}`, body: "" });
      sceneRefs.set(id, new Set([cardId]));
      return { sceneId: id, reanchored: realized.reanchored };
    },
    structure: () => manuscript.doc,
    moveScene: async (nodeId, parentId, position) => {
      calls.push(`move:${nodeId}:${parentId}:${position}`);
    },
    sceneReferents: (sceneId) => [...(sceneRefs.get(sceneId) ?? [])],
    readScene: async (sceneId) => structuredClone(scenes.get(sceneId)!),
    deleteScene: async (sceneId) => {
      calls.push(`deleteScene:${sceneId}`);
      scenes.delete(sceneId);
      sceneRefs.delete(sceneId);
    },
    attachCardScene: async (cardId, sceneId, text) => {
      calls.push(`attach:${cardId}:${sceneId}:${text ?? "-"}`);
      return outcome.attach === null && text ? text : outcome.attach;
    },
    detachCardScene: async (cardId, text) => {
      calls.push(`detach:${cardId}:${text ?? "-"}`);
      for (const refs of sceneRefs.values()) refs.delete(cardId);
      return outcome.detach === null && text ? text : outcome.detach;
    },
    setCardText: async (cardId, text) => {
      calls.push(`text:${cardId}:${JSON.stringify(text)}`);
    },
    readSceneSummary: async (sceneId) => summaries.get(sceneId) ?? "",
    moveCardInStoryTime: async (cardId, anchor) => {
      calls.push(`story:${cardId}:${JSON.stringify(anchor)}`);
    },
    placeCard: async (cardId, place) => {
      calls.push(`place:${cardId}:${JSON.stringify(place)}`);
    },
    confirmSceneDelete: async () => {
      calls.push("confirm");
      return confirm.result;
    },
  };
  return { port, cards, plotlines, arcs, decks, scenes, sceneRefs, summaries, outcome, confirm, calls, realized, manuscript };
}

// A projection with just the fields the finders / recorder read.
function card(id: string, extra: Partial<PlotBoardCard> = {}): PlotBoardCard {
  return {
    id,
    title: id,
    synopsis: "",
    plotline: null,
    scene: null,
    container: null,
    deck: null,
    planned_in: null,
    planned_after: null,
    container_order: null,
    page_status: null,
    beats: [],
    sequence: null,
    causal_links: [],
    story_order: 0,
    story_movable: true,
    ...extra,
  };
}
function projection(cards: PlotBoardCard[]): PlotBoardProjection {
  return { board_id: "b", board_revision: "r", layout: {}, plotlines: [], arcs: [], containers: [], decks: [], cards, diagnostics: [] };
}

describe("referrer finders", () => {
  it("finds cards whose causal_links point at a card", () => {
    const proj = projection([
      card("a", { causal_links: ["target"] }),
      card("b", { causal_links: ["other"] }),
      card("target"),
    ]);
    expect(cardsReferencingCard(proj, "target")).toEqual(["a"]);
  });

  it("finds cards whose primary plotline OR a beat points at a plotline", () => {
    const proj = projection([
      card("primary", { plotline: "P" }),
      card("beat-only", {
        beats: [
          {
            plotline_id: "P",
            plotline_title: "",
            plotline_color: null,
            beat_id: "b1",
            title: "",
            number: 1,
            holder_kind: "plot:plotline",
            character_id: null,
            character_name: null,
            character_initial: null,
          },
        ],
      }),
      card("elsewhere", { plotline: "Q" }),
    ]);
    expect(cardsReferencingPlotline(proj, "P")).toEqual(["primary", "beat-only"]);
  });
});

describe("create / delete card commands", () => {
  it("createCard: undo deletes, redo recreates under the id", async () => {
    const { port, cards, calls } = fakePort();
    cards.set("c1", cardState("Card"));
    const cmd = createCardCommand(port, "c1", cardState("Card"));
    await cmd.undo();
    expect(cards.has("c1")).toBe(false);
    await cmd.redo();
    expect(cards.get("c1")).toEqual(cardState("Card"));
    expect(calls).toEqual(["deleteCard:c1", "recreateCard:c1"]);
  });

  it("deleteCard: undo recreates the node THEN restores referrers, redo re-deletes", async () => {
    const { port, calls } = fakePort();
    const referrers: CardRef[] = [
      { id: "refA", state: cardState("A", { causal_links: [{ target: "gone" }] }) },
      { id: "refB", state: cardState("B", { causal_links: [{ target: "gone" }] }) },
    ];
    const cmd = deleteCardCommand(port, "gone", cardState("Gone"), referrers);
    await cmd.undo();
    // Node first (so the referrers' refs are not dangling-healed), then the referrers
    // (their per-item refetch suppressed), then ONE board refresh (#909 batch).
    expect(calls).toEqual(["recreateCard:gone", "restoreCard:refA", "restoreCard:refB", "refreshBoard"]);
    calls.length = 0;
    await cmd.redo();
    expect(calls).toEqual(["deleteCard:gone"]);
  });
});

describe("card edit command", () => {
  it("flips whole card state before/after", async () => {
    const { port, cards, calls } = fakePort();
    cards.set("c1", cardState("after", { plotline: "P2" }));
    const cmd = cardEditCommand(port, "c1", cardState("before", { plotline: "P1" }), cardState("after", { plotline: "P2" }), "reassign plotline");
    await cmd.undo();
    expect(cards.get("c1")).toEqual(cardState("before", { plotline: "P1" }));
    await cmd.redo();
    expect(cards.get("c1")).toEqual(cardState("after", { plotline: "P2" }));
    expect(cmd.label).toBe("reassign plotline");
    expect(calls).toEqual(["restoreCard:c1", "restoreCard:c1"]);
  });

  it("restores SEVERAL cards as one step (a beat move card→card, #941)", async () => {
    const { port, cards, calls } = fakePort();
    const before: CardRef[] = [
      { id: "from", state: cardState("From", { beat_links: [{ plotline: "P", beat_id: "b1" }] }) },
      { id: "to", state: cardState("To", { beat_links: [] }) },
    ];
    const after: CardRef[] = [
      { id: "from", state: cardState("From", { beat_links: [] }) },
      { id: "to", state: cardState("To", { beat_links: [{ plotline: "P", beat_id: "b1" }] }) },
    ];
    const cmd = cardEditManyCommand(port, before, after, "move beat");
    await cmd.undo();
    expect(cards.get("from")).toEqual(before[0].state);
    expect(cards.get("to")).toEqual(before[1].state);
    await cmd.redo();
    expect(cards.get("from")).toEqual(after[0].state);
    expect(cards.get("to")).toEqual(after[1].state);
    // One step touches both cards on undo and again on redo (two restores each).
    expect(calls).toEqual(["restoreCard:from", "restoreCard:to", "restoreCard:from", "restoreCard:to"]);
  });
});

describe("plotline commands", () => {
  it("create: undo deletes, redo recreates with beats + lineage", async () => {
    const { port, plotlines } = fakePort();
    const state = plotlineState("Thread", { color: "rose", instance_beats: [{ beat_id: "b1", title: "Meet" }] });
    plotlines.set("p1", state);
    const cmd = createPlotlineCommand(port, "p1", state);
    await cmd.undo();
    expect(plotlines.has("p1")).toBe(false);
    await cmd.redo();
    expect(plotlines.get("p1")).toEqual(state);
  });

  it("delete: undo recreates the plotline then restores its cards", async () => {
    const { port, calls } = fakePort();
    const referrers: CardRef[] = [{ id: "card1", state: cardState("On thread", { plotline: "p1" }) }];
    const cmd = deletePlotlineCommand(port, "p1", plotlineState("Thread"), referrers);
    await cmd.undo();
    // Plotline first, then its cards (refetch suppressed), then ONE roster+board
    // refresh at the end (#909 batch).
    expect(calls).toEqual(["recreatePlotline:p1", "restoreCard:card1", "refreshRoster", "refreshBoard"]);
  });

  it("edit: flips whole plotline state", async () => {
    const { port, plotlines } = fakePort();
    plotlines.set("p1", plotlineState("Renamed", { color: "moss" }));
    const cmd = plotlineEditCommand(port, "p1", plotlineState("Old", { color: "rose" }), plotlineState("Renamed", { color: "moss" }), "recolour plotline");
    await cmd.undo();
    expect(plotlines.get("p1")).toEqual(plotlineState("Old", { color: "rose" }));
    await cmd.redo();
    expect(plotlines.get("p1")).toEqual(plotlineState("Renamed", { color: "moss" }));
  });
});

describe("character-arc commands (ADR-0080 §5)", () => {
  it("create: undo deletes, redo recreates with beats + lineage — through the ARC port methods", async () => {
    const { port, arcs, calls } = fakePort();
    const state = arcState("Elena's redemption", { color: "rose", character: "char_elena", instance_beats: [{ beat_id: "b1", title: "Denial" }] });
    arcs.set("arc1", state);
    const cmd = createArcCommand(port, "arc1", state);
    await cmd.undo();
    expect(arcs.has("arc1")).toBe(false);
    await cmd.redo();
    expect(arcs.get("arc1")).toEqual(state);
    // The #3b-i correctness point: an arc's undo/redo call the ARC port methods, never
    // deletePlotline/recreatePlotline (which would recreate it AS a plotline).
    expect(calls).toEqual(["deleteArc:arc1", "recreateArc:arc1"]);
  });

  it("delete: undo recreates the arc then restores its cards' change-beat links", async () => {
    const { port, calls } = fakePort();
    const referrers: CardRef[] = [{ id: "card1", state: cardState("Fulfils a change-beat", { beat_links: [{ plotline: "arc1", beat_id: "b1" }] }) }];
    const cmd = deleteArcCommand(port, "arc1", arcState("Elena's redemption"), referrers);
    await cmd.undo();
    expect(calls).toEqual(["recreateArc:arc1", "restoreCard:card1", "refreshArcRoster", "refreshBoard"]);
    calls.length = 0;
    await cmd.redo();
    expect(calls).toEqual(["deleteArc:arc1"]);
  });

  it("edit: flips whole arc state (a rebind or recolour)", async () => {
    const { port, arcs } = fakePort();
    arcs.set("arc1", arcState("Elena's redemption", { character: "char_elena" }));
    const cmd = arcEditCommand(
      port,
      "arc1",
      arcState("Elena's redemption", { character: "" }),
      arcState("Elena's redemption", { character: "char_elena" }),
      "bind character",
    );
    await cmd.undo();
    expect(arcs.get("arc1")).toEqual(arcState("Elena's redemption", { character: "" }));
    await cmd.redo();
    expect(arcs.get("arc1")).toEqual(arcState("Elena's redemption", { character: "char_elena" }));
  });
});

describe("seed command", () => {
  it("undo deletes every seeded card, redo recreates them all", async () => {
    const { port, cards, calls } = fakePort();
    const created: CardRef[] = [
      { id: "s1", state: cardState("Scene 1", { scene: "sc1" }) },
      { id: "s2", state: cardState("Scene 2", { scene: "sc2" }) },
    ];
    created.forEach((c) => cards.set(c.id, c.state));
    const cmd = seedCommand(port, created);
    await cmd.undo();
    expect(cards.size).toBe(0);
    await cmd.redo();
    expect(cards.size).toBe(2);
    // The whole batch in parallel + ONE refresh per direction (#909), not N.
    expect(calls).toEqual([
      "deleteCard:s1",
      "deleteCard:s2",
      "refreshBoard",
      "recreateCard:s1",
      "recreateCard:s2",
      "refreshBoard",
    ]);
  });
});

describe("realize command (S6b)", () => {
  it("undo deletes a sole-referent EMPTY scene silently (no confirm)", async () => {
    const { port, scenes, sceneRefs, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "" });
    sceneRefs.set("sc1", new Set(["c1"]));
    const cmd = realizeCommand(port, "c1", null, "sc1");
    await cmd.undo();
    expect(calls).toEqual(["deleteScene:sc1"]); // no "confirm" — empty scene
    expect(scenes.has("sc1")).toBe(false);
  });

  it("undo confirms before deleting a sole-referent scene that holds prose", async () => {
    const { port, scenes, sceneRefs, confirm, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "She admits it." });
    sceneRefs.set("sc1", new Set(["c1"]));
    confirm.result = true;
    await realizeCommand(port, "c1", null, "sc1").undo();
    expect(calls).toEqual(["confirm", "deleteScene:sc1"]);
    expect(scenes.has("sc1")).toBe(false);
  });

  it("undo of a written scene ABORTS (throws UndoCancelled, nothing mutated) when declined", async () => {
    const { port, scenes, sceneRefs, confirm, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "Precious prose." });
    sceneRefs.set("sc1", new Set(["c1"]));
    confirm.result = false;
    await expect(realizeCommand(port, "c1", null, "sc1").undo()).rejects.toBeInstanceOf(UndoCancelled);
    expect(calls).toEqual(["confirm"]); // no delete — the scene (and the realize) survive
    expect(scenes.has("sc1")).toBe(true);
  });

  it("undo always deletes the scene — the card is its one referent (ADR-0097 §1)", async () => {
    const { port, scenes, sceneRefs, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "" });
    sceneRefs.set("sc1", new Set(["c1"]));
    await realizeCommand(port, "c1", null, "sc1").undo();
    expect(calls).toEqual(["deleteScene:sc1"]); // never a detach
  });

  it("undo is a no-op when this card no longer references the scene", async () => {
    const { port, scenes, sceneRefs, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "" });
    sceneRefs.set("sc1", new Set(["other"])); // c1 was detached/re-realized elsewhere
    await realizeCommand(port, "c1", null, "sc1").undo();
    expect(calls).toEqual([]); // nothing to reverse
    expect(scenes.has("sc1")).toBe(true);
  });

  it("redo re-mints a fresh scene, and the next undo targets THAT scene", async () => {
    const { port, scenes, sceneRefs, calls } = fakePort();
    scenes.set("sc1", { title: "S", body: "" });
    sceneRefs.set("sc1", new Set(["c1"]));
    const cmd = realizeCommand(port, "c1", null, "sc1");
    await cmd.undo(); // deletes sc1
    await cmd.redo(); // re-mints → scene_1 (fake counter), attached to c1
    expect(calls).toEqual(["deleteScene:sc1", "realize:c1->scene_1"]);
    await cmd.undo(); // must delete the NEW scene, not the gone sc1
    expect(calls).toEqual(["deleteScene:sc1", "realize:c1->scene_1", "deleteScene:scene_1"]);
  });
});

describe("PlotUndoRecorder", () => {
  it("cardEdit records a command only when the op actually changed the card", async () => {
    const { port, cards } = fakePort();
    cards.set("c1", cardState("Card", { plotline: "P1" }));
    const recorded: { label?: string }[] = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));

    // No-op: the op leaves the card unchanged → nothing recorded.
    await recorder.cardEdit("c1", "reassign plotline", async () => {});
    expect(recorded).toEqual([]);

    // Real change: the op mutates the fake's stored state → one command.
    await recorder.cardEdit("c1", "reassign plotline", async () => {
      cards.set("c1", cardState("Card", { plotline: "P2" }));
    });
    expect(recorded.map((c) => c.label)).toEqual(["reassign plotline"]);
  });

  it("arcEdit records a command only when the op actually changed the arc", async () => {
    const { port, arcs } = fakePort();
    arcs.set("arc1", arcState("Elena's redemption", { character: "char_elena" }));
    const recorded: { label?: string }[] = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));

    // No-op.
    await recorder.arcEdit("arc1", "bind character", async () => {});
    expect(recorded).toEqual([]);

    // Real change.
    await recorder.arcEdit("arc1", "bind character", async () => {
      arcs.set("arc1", arcState("Elena's redemption", { character: "char_marcus" }));
    });
    expect(recorded.map((c) => c.label)).toEqual(["bind character"]);
  });

  it("createCard runs the forward op and records the new id + captured state", async () => {
    const { port, cards, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));

    const id = await recorder.createCard(async () => {
      cards.set("new1", cardState("Fresh"));
      return "new1";
    });
    expect(id).toBe("new1");
    // The recorded command's undo deletes the just-created card.
    await recorded[0].undo();
    expect(cards.has("new1")).toBe(false);
    expect(calls).toContain("deleteCard:new1");
  });

  it("createArc runs the forward op and records the new id + captured state — never through createPlotline", async () => {
    const { port, arcs, plotlines, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));

    // Mirrors the instantiate-branch routing in PlotEditor: the ONE instantiate call
    // already minted the entry (arcs.set below stands in for that), so the `create`
    // callback just hands back the id already returned — it does not mint again.
    arcs.set("arc1", arcState("Elena's redemption"));
    const id = await recorder.createArc(async () => "arc1");
    expect(id).toBe("arc1");
    await recorded[0].undo();
    expect(arcs.has("arc1")).toBe(false);
    expect(plotlines.size).toBe(0); // never touched the plotline substrate
    expect(calls).toEqual(["deleteArc:arc1"]);
  });

  it("deleteArc captures the projection's referrers (cards fulfilling a change-beat) before deleting", async () => {
    const { port, arcs, cards } = fakePort();
    arcs.set("gone", arcState("Gone"));
    cards.set("card1", cardState("Fulfils a change-beat", { beat_links: [{ plotline: "gone", beat_id: "b1" }] }));
    const proj = projection([
      card("card1", {
        beats: [
          {
            plotline_id: "gone",
            plotline_title: "",
            plotline_color: null,
            beat_id: "b1",
            title: "",
            number: 1,
            holder_kind: "plot:character_arc",
            character_id: null,
            character_name: null,
            character_initial: null,
          },
        ],
      }),
    ]);
    const recorded: Array<{ undo: () => Promise<void> }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c as { undo: () => Promise<void> }), () => proj);

    await recorder.deleteArc("gone", async () => {
      arcs.delete("gone");
    });
    // Undo restores the arc AND the card that fulfilled its change-beat.
    cards.set("card1", cardState("Fulfils a change-beat", {})); // simulate the backend having purged the link
    await recorded[0].undo();
    expect(arcs.get("gone")).toEqual(arcState("Gone"));
    expect(cards.get("card1")).toEqual(cardState("Fulfils a change-beat", { beat_links: [{ plotline: "gone", beat_id: "b1" }] }));
  });

  it("deleteCard captures the projection's referrers before deleting", async () => {
    const { port, cards } = fakePort();
    cards.set("gone", cardState("Gone"));
    cards.set("refA", cardState("A", { causal_links: [{ target: "gone" }] }));
    const proj = projection([card("gone"), card("refA", { causal_links: ["gone"] })]);
    const recorded: Array<{ undo: () => Promise<void> }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c as { undo: () => Promise<void> }), () => proj);

    await recorder.deleteCard("gone", async () => {
      cards.delete("gone");
    });
    // Undo the recorded delete: node back, then the captured referrer restored.
    cards.set("refA", cardState("A", {})); // simulate the backend having purged the ref
    await recorded[0].undo();
    expect(cards.get("gone")).toEqual(cardState("Gone"));
    expect(cards.get("refA")).toEqual(cardState("A", { causal_links: [{ target: "gone" }] }));
  });

  it("seed captures the ids the op reports as created, and undo deletes just them", async () => {
    const { port, cards } = fakePort();
    cards.set("existing", cardState("Existing"));
    const recorded: Array<{ undo: () => Promise<void> }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c as { undo: () => Promise<void> }), () => null);

    await recorder.seed(async () => {
      cards.set("seed1", cardState("Seed 1", { scene: "sc1" }));
      return ["seed1"]; // the store reports the created id
    });
    expect(recorded).toHaveLength(1);
    await recorded[0].undo();
    expect(cards.has("seed1")).toBe(false);
    expect(cards.has("existing")).toBe(true); // the pre-existing card is untouched
  });

  it("seed records nothing when the op reports no created cards (idempotent re-seed)", async () => {
    const { port } = fakePort();
    const recorded: unknown[] = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => null);
    await recorder.seed(async () => []);
    expect(recorded).toEqual([]);
  });

  it("realize mints the scene and records a command; its undo deletes that scene", async () => {
    const { port, scenes, calls } = fakePort();
    const recorded: Array<{ undo: () => Promise<void> }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c as { undo: () => Promise<void> }), () => null);

    await recorder.realize("c1", null);
    expect(calls).toEqual(["realize:c1->scene_1"]);
    expect(scenes.has("scene_1")).toBe(true);
    await recorded[0].undo(); // the just-minted empty scene deletes silently
    expect(scenes.has("scene_1")).toBe(false);
  });

  it("realize records nothing when the op mints no scene (e.g. a 409 already-attached)", async () => {
    const { port } = fakePort();
    const recorded: unknown[] = [];
    // A port whose realizeCard yields no scene id (the 409 / error case).
    const noScenePort = { ...port, realizeCard: async () => ({ sceneId: "", reanchored: [] }) };
    const recorder = new PlotUndoRecorder(noScenePort, (c) => recorded.push(c), () => null);
    await recorder.realize("c1", null);
    expect(recorded).toEqual([]);
  });

  it("awaits whenIdle before running an op — queues behind an in-flight undo (#909)", async () => {
    const { port, cards } = fakePort();
    cards.set("c1", cardState("Card", { plotline: "P1" }));
    const gate: { release?: () => void } = {};
    const whenIdle = () => new Promise<void>((resolve) => (gate.release = resolve));
    const recorder = new PlotUndoRecorder(port, () => {}, () => null, whenIdle);

    let opRan = false;
    const done = recorder.cardEdit("c1", "reassign", async () => {
      opRan = true;
    });
    await Promise.resolve();
    expect(opRan).toBe(false); // parked on whenIdle — not racing the in-flight undo

    gate.release!();
    await done;
    expect(opRan).toBe(true); // ran once idle
  });
});

// ── Text edit / attach / detach (ADR-0097 §3/§4) ─────────────────────────────

describe("card text command", () => {
  it("undo and redo replay the text endpoint with the before / after values", async () => {
    const { port, calls } = fakePort();
    const cmd = cardTextCommand(port, "c1", { title: "Old" }, { title: "New" }, "rename card");
    await cmd.undo();
    await cmd.redo();
    expect(calls).toEqual(['text:c1:{"title":"Old"}', 'text:c1:{"title":"New"}']);
  });

  it("cardTextEdit records the DISPLAYED before text, and nothing for a no-op", async () => {
    const { port, calls } = fakePort();
    const recorded: { label?: string }[] = [];
    // The board shows the scene's text for a written card: that is the "before".
    const proj = projection([card("c1", { title: "Scene title", synopsis: "Scene summary", scene: "sc1" })]);
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => proj);
    await recorder.cardTextEdit("c1", "edit synopsis", { synopsis: "Scene summary" }); // same → no step
    expect(recorded).toEqual([]);
    await recorder.cardTextEdit("c1", "edit synopsis", { synopsis: "Better" });
    expect(recorded.map((c) => c.label)).toEqual(["edit synopsis"]);
    await (recorded[0] as { undo: () => Promise<void> }).undo();
    expect(calls.at(-1)).toBe('text:c1:{"synopsis":"Scene summary"}');
  });
});

describe("detach command", () => {
  const before: CardState = { title: "Own title", body: "Own synopsis", metadata: { scene: "sc1" } };

  it("undo restores the card's own text while unwritten, then re-attaches with 'scene'", async () => {
    const { port, calls } = fakePort();
    await detachCommand(port, "c1", "sc1", before, "card").undo();
    expect(calls).toEqual(['text:c1:{"title":"Own title","synopsis":"Own synopsis"}', "attach:c1:sc1:scene"]);
  });

  it("redo detaches with the recorded choice (no second ask)", async () => {
    const { port, calls } = fakePort();
    await detachCommand(port, "c1", "sc1", before, "card").redo();
    expect(calls).toEqual(["detach:c1:card"]);
  });

  it("redo with no choice recorded passes none", async () => {
    const { port, calls } = fakePort();
    await detachCommand(port, "c1", "sc1", before, null).redo();
    expect(calls).toEqual(["detach:c1:-"]);
  });

  it("a replay the writer cancels throws UndoCancelled", async () => {
    const { port, outcome } = fakePort();
    outcome.detach = "cancelled";
    await expect(detachCommand(port, "c1", "sc1", before, null).redo()).rejects.toBeInstanceOf(UndoCancelled);
  });

  it("the recorder records the choice made, and nothing when cancelled", async () => {
    const { port, cards, outcome } = fakePort();
    cards.set("c1", cardState("Own title", { scene: "sc1" }, "Own synopsis"));
    const recorded: { label?: string; redo: () => Promise<void> }[] = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c as never), () => projection([]));
    outcome.detach = "cancelled";
    await recorder.detach("c1");
    expect(recorded).toEqual([]);
    outcome.detach = "scene";
    await recorder.detach("c1");
    expect(recorded.map((c) => c.label)).toEqual(["detach scene"]);
  });
});

describe("attach command", () => {
  const before: CardState = { title: "Own title", body: "Own synopsis", metadata: {} };

  it("undo puts the scene's old summary back (while written), then detaches keeping the card's synopsis", async () => {
    const { port, summaries, calls } = fakePort();
    summaries.set("sc1", "Own synopsis"); // the attach overwrote the scene's "Old summary"
    await attachCommand(port, "c1", "sc1", before, "Old summary", "card").undo();
    expect(calls).toEqual([
      'text:c1:{"synopsis":"Old summary"}',
      "detach:c1:card",
      'text:c1:{"title":"Own title","synopsis":"Own synopsis"}',
    ]);
  });

  it("undo leaves the scene's summary alone when the attach did not change it", async () => {
    const { port, summaries, calls } = fakePort();
    summaries.set("sc1", "Same");
    await attachCommand(port, "c1", "sc1", before, "Same", "scene").undo();
    expect(calls[0]).toBe("detach:c1:card");
  });

  it("redo attaches with the recorded choice", async () => {
    const { port, calls } = fakePort();
    await attachCommand(port, "c1", "sc1", before, "Old", "scene").redo();
    expect(calls).toEqual(["attach:c1:sc1:scene"]);
  });

  it("the recorder reads the scene's summary first, and records nothing when cancelled", async () => {
    const { port, cards, summaries, outcome, calls } = fakePort();
    cards.set("c1", cardState("Own title", {}, "Own synopsis"));
    summaries.set("sc1", "Old summary");
    const recorded: { label?: string }[] = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));
    outcome.attach = "cancelled";
    await recorder.attach("c1", "sc1");
    expect(recorded).toEqual([]);
    outcome.attach = "card";
    await recorder.attach("c1", "sc1");
    expect(recorded.map((c) => c.label)).toEqual(["attach scene"]);
    expect(calls).toEqual(["attach:c1:sc1:-", "attach:c1:sc1:-"]);
  });
});

describe("delete undo of a written card", () => {
  it("recreates the card through the port with its state (story rank included)", async () => {
    const { port, cards, calls } = fakePort();
    const state: CardState = { title: "T", body: "B", metadata: { scene: "sc1" }, story_rank: 3 };
    cards.set("c1", state);
    await deleteCardCommand(port, "c1", state, []).undo();
    expect(calls).toContain("recreateCard:c1");
    expect(cards.get("c1")?.story_rank).toBe(3);
  });
});

describe("story move (ADR-0097 §4)", () => {
  // Three cards a, b, c in story time.
  const ordered = () =>
    projection([card("a", { story_order: 0 }), card("b", { story_order: 1 }), card("c", { story_order: 2 })]);
  const recorderFor = (port: PlotCommandPort, recorded: Array<{ undo: () => unknown; redo: () => unknown }>) =>
    new PlotUndoRecorder(port, (c) => recorded.push(c), ordered);

  it("records one step: undo puts the card back after its old predecessor, redo replays the anchor", async () => {
    const { port, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    await recorderFor(port, recorded).storyMove("c", { before_id: "a" }, "move in story time");
    expect(recorded).toHaveLength(1);
    await recorded[0].undo();
    await recorded[0].redo();
    expect(calls).toEqual([
      'story:c:{"before_id":"a"}',
      'story:c:{"after_id":"b"}',
      'story:c:{"before_id":"a"}',
    ]);
  });

  it("a card that was first is restored before its old successor", async () => {
    const { port, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    await recorderFor(port, recorded).storyMove("a", { after_id: "c" }, "move in story time");
    await recorded[0].undo();
    expect(calls[1]).toBe('story:a:{"before_id":"b"}');
  });

  it("a move to where the card already is sends and records nothing", async () => {
    const { port, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    const recorder = recorderFor(port, recorded);
    await recorder.storyMove("b", { after_id: "a" }, "move in story time");
    await recorder.storyMove("b", { before_id: "c" }, "move in story time");
    expect(calls).toEqual([]);
    expect(recorded).toEqual([]);
  });
});

describe("card place (ADR-0097 §4)", () => {
  // a, b, c in story time; b lives in deck "d1", the rest are loose.
  const board = () =>
    projection([
      card("a", { story_order: 0 }),
      card("b", { story_order: 1, deck: "d1" }),
      card("c", { story_order: 2 }),
    ]);
  const recorderFor = (port: PlotCommandPort, recorded: Array<{ undo: () => unknown; redo: () => unknown }>) =>
    new PlotUndoRecorder(port, (c) => recorded.push(c), board);

  it("records ONE step: undo sends the old home and old neighbour, redo replays the drop", async () => {
    const { port, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    await recorderFor(port, recorded).cardPlace("c", { to: { deck: "d1" }, story: { before_id: "b" } });
    expect(recorded).toHaveLength(1);
    await recorded[0].undo();
    await recorded[0].redo();
    expect(calls).toEqual([
      'place:c:{"to":{"deck":"d1"},"story":{"before_id":"b"}}',
      'place:c:{"to":{"loose":true},"story":{"after_id":"b"}}',
      'place:c:{"to":{"deck":"d1"},"story":{"before_id":"b"}}',
    ]);
  });

  it("a card leaving a deck is restored into it", async () => {
    const { port, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    await recorderFor(port, recorded).cardPlace("b", { to: { loose: true } });
    await recorded[0].undo();
    // Membership only: no story half in either direction.
    expect(calls).toEqual(['place:b:{"to":{"loose":true}}', 'place:b:{"to":{"deck":"d1"}}']);
  });

  it("sends only the half that changes: a reorder inside the same deck is story-only", async () => {
    const { port, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    await recorderFor(port, recorded).cardPlace("b", { to: { deck: "d1" }, story: { after_id: "c" } });
    expect(calls).toEqual(['place:b:{"story":{"after_id":"c"}}']);
    await recorded[0].undo();
    expect(calls[1]).toBe('place:b:{"story":{"after_id":"a"}}');
  });

  it("a drop that changes neither home nor order sends and records nothing", async () => {
    const { port, calls } = fakePort();
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    await recorderFor(port, recorded).cardPlace("b", { to: { deck: "d1" }, story: { after_id: "a" } });
    expect(calls).toEqual([]);
    expect(recorded).toEqual([]);
  });
});

describe("deck commands (ADR-0097 §2)", () => {
  it("create: undo deletes the deck, redo recreates it under its id", async () => {
    const { port, decks, calls } = fakePort();
    decks.set("d1", deckState("Backstory"));
    const command = createDeckCommand(port, "d1", deckState("Backstory"));
    await command.undo();
    expect(decks.has("d1")).toBe(false);
    await command.redo();
    expect(decks.get("d1")).toEqual(deckState("Backstory"));
    expect(calls).toEqual(["deleteDeck:d1", "recreateDeck:d1"]);
  });

  it("delete: undo recreates the deck, restores child decks and each member, then refreshes once", async () => {
    const { port, calls } = fakePort();
    const command = deleteDeckCommand(
      port,
      "d1",
      deckState("Backstory", {}, "Mara's past"),
      [
        { id: "c1", written: false },
        { id: "c2", written: true },
      ],
      [{ id: "d2", state: deckState("Childhood", { plot_deck: "d1" }) }],
    );
    await command.undo();
    // The deck first (a restored reference to a missing deck would be healed away).
    expect(calls[0]).toBe("recreateDeck:d1");
    expect(calls.slice(1, 4).sort()).toEqual(
      ["cardDeck:c1:d1:unwritten", "cardDeck:c2:d1:written", "restoreDeck:d2"].sort(),
    );
    expect(calls.slice(4).sort()).toEqual(["refreshBoard", "refreshDeckRoster"]);
    await command.redo();
    expect(calls.at(-1)).toBe("deleteDeck:d1");
  });

  it("deleteDeck records the deck, its members and its child decks off the projection", async () => {
    const { port, decks, calls } = fakePort();
    decks.set("d1", deckState("Backstory"));
    decks.set("d2", deckState("Childhood", { plot_deck: "d1" }));
    const proj: PlotBoardProjection = {
      ...projection([
        card("a", { deck: "d1" }),
        card("w", { deck: "d1", scene: "scene_1" }),
        card("z", { deck: "other" }),
      ]),
      decks: [
        { id: "d1", title: "Backstory", synopsis: "", parent: null, movable: true },
        { id: "d2", title: "Childhood", synopsis: "", parent: "d1", movable: true },
      ],
    };
    const recorded: Array<{ undo: () => unknown; redo: () => unknown }> = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => proj);
    await recorder.deleteDeck("d1", async () => {
      decks.delete("d1");
    });
    expect(recorded).toHaveLength(1);
    await recorded[0].undo();
    expect(calls).toContain("cardDeck:a:d1:unwritten");
    expect(calls).toContain("cardDeck:w:d1:written");
    expect(calls).not.toContain("cardDeck:z:d1:unwritten");
    expect(calls).toContain("restoreDeck:d2");
  });

  it("deckEdit records a command only when the op changed the deck", async () => {
    const { port, decks } = fakePort();
    decks.set("d1", deckState("Backstory"));
    const recorded: { label?: string }[] = [];
    const recorder = new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection([]));
    await recorder.deckEdit("d1", "rename deck", async () => {});
    expect(recorded).toEqual([]);
    await recorder.deckEdit("d1", "rename deck", async () => {
      decks.set("d1", deckState("Mara's backstory"));
    });
    expect(recorded.map((c) => c.label)).toEqual(["rename deck"]);
  });
});

describe("planned cards (ADR-0097 §6)", () => {
  type Rec = Array<{ undo: () => unknown; redo: () => unknown }>;
  const plan = (planned_in: string, planned_after: string | null) => ({ planned_in, planned_after });
  const recorderFor = (port: PlotCommandPort, recorded: Rec, cards: PlotBoardCard[]) =>
    new PlotUndoRecorder(port, (c) => recorded.push(c), () => projection(cards));

  it("a plan drop undoes back to the deck the card came from", async () => {
    const { port, calls } = fakePort();
    const recorded: Rec = [];
    await recorderFor(port, recorded, [card("a", { deck: "d1" })]).cardPlace("a", { to: plan("ch", "s1") });
    await recorded[0].undo();
    await recorded[0].redo();
    expect(calls).toEqual([
      'place:a:{"to":{"planned_in":"ch","planned_after":"s1"}}',
      'place:a:{"to":{"deck":"d1"}}',
      'place:a:{"to":{"planned_in":"ch","planned_after":"s1"}}',
    ]);
  });

  it("a plan drop undoes back to the loose area", async () => {
    const { port, calls } = fakePort();
    const recorded: Rec = [];
    await recorderFor(port, recorded, [card("a")]).cardPlace("a", { to: plan("ch", null) });
    await recorded[0].undo();
    expect(calls[1]).toBe('place:a:{"to":{"loose":true}}');
  });

  it("re-planning undoes back to the previous plan, and re-dropping in place records nothing", async () => {
    const { port, calls } = fakePort();
    const recorded: Rec = [];
    const cards = [card("a", { planned_in: "ch1", planned_after: "s1", container: "ch1" })];
    await recorderFor(port, recorded, cards).cardPlace("a", { to: plan("ch2", null) });
    await recorded[0].undo();
    expect(calls[1]).toBe('place:a:{"to":{"planned_in":"ch1","planned_after":"s1"}}');
    await recorderFor(port, [], cards).cardPlace("a", { to: plan("ch1", "s1") });
    expect(calls).toHaveLength(2);
  });

  const node = (id: string, children: StructureNode[] = []): StructureNode =>
    ({ id: `n_${id}`, scene_id: id, type: "x", title: id, children }) as StructureNode;
  const tree = (): StructureDocument =>
    ({
      root: { id: "root", type: "root", title: "Book", children: [
        { id: "ch1", type: "c", title: "One", children: [node("s1"), node("s2")] },
        { id: "ch2", type: "c", title: "Two", children: [node("s3")] },
      ] },
    }) as unknown as StructureDocument;

  it("a scene move undoes to its old parent and position, redo replays it", async () => {
    const { port, calls, manuscript } = fakePort();
    manuscript.doc = tree();
    const recorded: Rec = [];
    await recorderFor(port, recorded, []).sceneMove("s1", "ch2", { after: "s3" });
    await recorded[0].undo();
    await recorded[0].redo();
    expect(calls).toEqual(["move:n_s1:ch2:1", "move:n_s1:ch1:0", "move:n_s1:ch2:1"]);
  });

  it("a scene move to where the scene already sits records nothing", async () => {
    const { port, calls, manuscript } = fakePort();
    manuscript.doc = tree();
    const recorded: Rec = [];
    await recorderFor(port, recorded, []).sceneMove("s1", "ch1", { before: "s2" });
    expect(calls).toEqual([]);
    expect(recorded).toEqual([]);
  });

  it("writing a planned card: undo deletes the scene, restores the plan and the re-anchored cards", async () => {
    const { port, calls, scenes, realized } = fakePort();
    realized.reanchored = ["b"];
    const recorded: Rec = [];
    const cards = [
      card("a", { planned_in: "ch", planned_after: "s0", container: "ch" }),
      card("b", { planned_in: "ch", planned_after: "s0", container: "ch" }),
    ];
    await recorderFor(port, recorded, cards).realize("a", null);
    expect(scenes.has("scene_1")).toBe(true);
    await recorded[0].undo();
    expect(calls).toEqual([
      "realize:a->scene_1",
      "deleteScene:scene_1",
      'place:a:{"to":{"planned_in":"ch","planned_after":"s0"}}',
      'place:b:{"to":{"planned_in":"ch","planned_after":"s0"}}',
    ]);
    // Redo realizes again (the backend re-anchors again).
    await recorded[0].redo();
    expect(calls.at(-1)).toBe("realize:a->scene_2");
  });

  it("writing an unplanned card restores no plan on undo", async () => {
    const { port, calls } = fakePort();
    const recorded: Rec = [];
    await recorderFor(port, recorded, [card("a")]).realize("a", "ch");
    await recorded[0].undo();
    expect(calls).toEqual(["realize:a->scene_1", "deleteScene:scene_1"]);
  });
});
