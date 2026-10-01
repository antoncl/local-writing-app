// Plot-board content commands (ADR-0053 §7, #902) — the command vocabulary that
// makes every board content op undoable, the plotline/card twin of the graph
// canvas's `graphCommands.ts`. A plotline is a board node now, so its create /
// delete / edit and a card's create / delete / field-edits are all gestures on the
// ONE board caretaker (GraphUndoController.record) — no second undo surface.
//
// Unlike the graph commands (in-memory array swaps over a GraphPort), these reverse
// through the BACKEND: undo/redo await the server inverse, which is why the caretaker
// gained async support. Two shapes carry the whole feature:
//
//   • create / delete — the node returns under its ORIGINAL id (create-with-supplied
//     -id), so refs in other cards reconnect instead of dangling (ADR-0050 §6). A
//     delete also captures every card that referenced the doomed node and restores
//     them on undo — "restore it with its beats and every card badge that pointed at
//     it" (§7). Redo re-deletes; the backend re-purges those refs.
//   • field/beat edit — a whole-state before/after flip (`restore(before)` /
//     `restore(after)`). Whole-state, not per-field, because one op can touch several
//     fields (dropping a beat also adopts a primary, #863); the flip reverses all of it.
//   • story move (ADR-0097 §4) — one `place` call; undo places the card back beside the
//     neighbour it had, redo replays the anchor the writer chose.
//   • card place (ADR-0097 §4, §6) — a drag into a deck, the loose area or a chapter (a
//     plan): ONE `place` call (home + story neighbour); undo restores the old home — deck,
//     loose or the old plan — and the old neighbour.
//   • scene move (ADR-0097 §8) — a written card dragged onto a chapter moves its scene; undo
//     moves it back to its old parent and position.
//   • deck create / delete / edit (ADR-0097 §2) — the deck twins of the plotline commands.
//     A delete frees its cards and child decks (the backend purges the references), so its
//     undo recreates the deck under its id, then puts each member and child back.
//   • deck realize / detach / text edit (ADR-0097 §3, §7) — a realized deck shows its container's
//     text; undoing a realize plans nothing and writes nothing: the cards go home, the deck is
//     detached, and the container the realize made is deleted.
//   • text edit / attach / detach (ADR-0097 §3/§4) — a written card SHOWS its scene's
//     text, so its title/synopsis move through their own endpoints, never a whole-state
//     save (the server refuses a written card's own title/body change). The commands
//     replay those endpoints, and attach / detach remember the text choice the writer
//     made so redo never asks twice.
//
// The pure builders below take a `PlotCommandPort` (store ops behind an interface, so
// they unit-test with a fake); `PlotUndoRecorder` wraps capture-op-record for the
// PlotEditor handlers; `defaultPlotCommandPort` wires the real store ops.

import { type Command, UndoCancelled } from "@/lib/stores/undoCaretaker.svelte";
import type { PlotBoardProjection, StructureDocument } from "@/lib/types";
import {
  type CardState,
  deleteCard,
  detachCardScene,
  deleteScene,
  getCardState,
  readScene,
  realizeCard,
  recreateCard,
  refreshAfterMutation,
  restoreCardState,
  sceneReferents,
  attachCardScene,
  readSceneSummary,
  setCardText,
  containerHoldsNodes,
  deleteContainerNode,
  moveCardInStoryTime,
  placeCardOnBoard,
  currentStructure,
  moveSceneNode,
  type CardTextOutcome,
} from "@/lib/stores/plotBoard";
import type { CardTextChoice, PlaceRequest, PlaceTo, StoryAnchor } from "@/lib/api/plot";
import { isStoryNoOp, storyRestoreAnchor } from "@/lib/plot/storyTime";
import { planSceneMove, type SceneMovePlan, type SceneNear } from "@/lib/plot/sceneMove";
import {
  type PlotlineState,
  deletePlotline,
  getPlotlineState,
  recreatePlotline,
  refreshRoster,
  restorePlotlineState,
} from "@/lib/stores/plotlines";
import {
  type ArcState,
  deleteArc,
  getArcState,
  recreateArc,
  refreshArcRoster,
  restoreArcState,
} from "@/lib/stores/characterArcs";
import {
  type DeckState,
  deleteDeck,
  getDeckState,
  attachDeckContainer,
  detachDeckContainer,
  realizeDeck,
  recreateDeck,
  refreshDeckRoster,
  restoreCardDeck,
  restoreDeckState,
  setDeckText,
} from "@/lib/stores/decks";
import { confirmService } from "@/lib/stores/confirmService.svelte";

// The backend inverses the commands replay through. Every method is async (a server
// round-trip); the builders never touch a store directly, so a test drives them with
// a fake port and asserts the calls.
export interface PlotCommandPort {
  // `refresh` (default true) is passed false inside a batched delete/seed undo, so
  // N restores skip their per-item board refetch and the command does ONE at the
  // end (refreshBoard / refreshRoster) — the refetch-storm fix (#909).
  deleteCard(id: string, refresh?: boolean): Promise<void>;
  getCardState(id: string): Promise<CardState>;
  restoreCardState(id: string, state: CardState, refresh?: boolean): Promise<void>;
  recreateCard(id: string, state: CardState, refresh?: boolean): Promise<void>;
  deletePlotline(id: string): Promise<void>;
  getPlotlineState(id: string): Promise<PlotlineState>;
  restorePlotlineState(id: string, state: PlotlineState, refresh?: boolean): Promise<void>;
  recreatePlotline(id: string, state: PlotlineState, refresh?: boolean): Promise<void>;
  // The character-arc twins (ADR-0080 §5) — a SEPARATE holder kind, never routed
  // through the plotline methods above (which would recreate an arc AS a plotline).
  deleteArc(id: string): Promise<void>;
  getArcState(id: string): Promise<ArcState>;
  restoreArcState(id: string, state: ArcState, refresh?: boolean): Promise<void>;
  recreateArc(id: string, state: ArcState, refresh?: boolean): Promise<void>;
  // The deck twins (ADR-0097 §2) — a SEPARATE node kind, with its own roster.
  deleteDeck(id: string, refresh?: boolean): Promise<void>;
  getDeckState(id: string): Promise<DeckState>;
  restoreDeckState(id: string, state: DeckState, refresh?: boolean): Promise<void>;
  recreateDeck(id: string, state: DeckState, refresh?: boolean): Promise<void>;
  // Put a card back in a deck after the deck's delete was undone (membership only).
  restoreCardDeck(cardId: string, deckId: string, written: boolean, refresh?: boolean): Promise<void>;
  refreshBoard(): Promise<void>;
  refreshRoster(): Promise<void>;
  refreshArcRoster(): Promise<void>;
  refreshDeckRoster(): Promise<void>;
  // Realize (S6b): mint a scene → its id, plus the planned cards the write re-anchored
  // (ADR-0097 §6); the undo/redo scene ops.
  realizeCard(cardId: string, parentId: string | null): Promise<{ sceneId: string; reanchored: string[] }>;
  // The manuscript tree (synchronous) and a node move in it — a written card's drop on a
  // chapter moves its scene (ADR-0097 §8).
  structure(): StructureDocument | null;
  moveScene(nodeId: string, parentId: string, position: number): Promise<void>;
  sceneReferents(sceneId: string): string[];
  readScene(sceneId: string): Promise<{ title: string; body: string }>;
  deleteScene(sceneId: string): Promise<void>;
  // Attach / detach with an optional recorded text choice (null / "cancelled" per
  // `CardTextOutcome`); the store asks the writer only when a choice is needed and
  // none was passed.
  attachCardScene(cardId: string, sceneId: string, text?: CardTextChoice): Promise<CardTextOutcome>;
  detachCardScene(cardId: string, text?: CardTextChoice): Promise<CardTextOutcome>;
  // The displayed title / synopsis edit (the scene's while the card is written).
  setCardText(cardId: string, text: CardText): Promise<void>;
  readSceneSummary(sceneId: string): Promise<string>;
  // Place a card right after / before another in story time (ADR-0097 §4).
  moveCardInStoryTime(cardId: string, anchor: StoryAnchor): Promise<void>;
  // Place a card in a deck / the loose area and/or beside a neighbour (ADR-0097 §4).
  placeCard(cardId: string, place: PlaceRequest): Promise<void>;
  // Suppressible confirm before deleting a written scene; resolves false on cancel.
  confirmSceneDelete(scene: { title: string; body: string }): Promise<boolean>;
  // A deck's realize (ADR-0097 §7): the container made for it + the cards planned in it; the
  // text edit (the container's while realized); attach / detach with the card's text-choice
  // contract; and the container's removal, behind a suppressible confirm when it holds nodes.
  realizeDeck(deckId: string): Promise<{ containerId: string; planned: string[] }>;
  setDeckText(deckId: string, text: CardText): Promise<void>;
  attachDeckContainer(deckId: string, containerId: string, text?: CardTextChoice): Promise<CardTextOutcome>;
  detachDeckContainer(deckId: string, text?: CardTextChoice): Promise<CardTextOutcome>;
  containerHoldsNodes(containerId: string): boolean;
  deleteContainer(containerId: string): Promise<void>;
  confirmContainerDelete(title: string): Promise<boolean>;
}

// The displayed title / synopsis of a card — each key optional so a command replays
// only what its edit changed.
export type CardText = { title?: string; synopsis?: string };

// A captured card (id + whole state) — a deleted node, or a referrer restored
// alongside it.
export type CardRef = { id: string; state: CardState };

// ── Pure referrer finders ────────────────────────────────────────────────────
// Which cards a delete's ref-purge will touch, read off the current projection at
// capture time. Deleting a CARD purges other cards' inbound causal_links to it;
// deleting a PLOTLINE blanks cards' primary `plotline` and drops their beat_links to
// it. Capturing these lets undo restore what the delete cascaded away.

export function cardsReferencingCard(projection: PlotBoardProjection, cardId: string): string[] {
  return projection.cards.filter((c) => c.causal_links.includes(cardId)).map((c) => c.id);
}

export function cardsReferencingPlotline(projection: PlotBoardProjection, plotlineId: string): string[] {
  return projection.cards
    .filter((c) => c.plotline === plotlineId || c.beats.some((b) => b.plotline_id === plotlineId))
    .map((c) => c.id);
}

// ── Pure command builders ────────────────────────────────────────────────────

export function createCardCommand(port: PlotCommandPort, id: string, state: CardState, label = "add card"): Command {
  return {
    label,
    undo: () => port.deleteCard(id),
    redo: () => port.recreateCard(id, state),
  };
}

export function deleteCardCommand(
  port: PlotCommandPort,
  id: string,
  state: CardState,
  referrers: CardRef[],
  label = "delete card",
): Command {
  return {
    label,
    // Node back under its id FIRST (awaited — a ref restored before its target
    // exists would be dangling-healed away), THEN the referrers in parallel with
    // their board refetch suppressed, and ONE refresh at the end (#909).
    undo: async () => {
      await port.recreateCard(id, state, false);
      await Promise.all(referrers.map((r) => port.restoreCardState(r.id, r.state, false)));
      await port.refreshBoard();
    },
    redo: () => port.deleteCard(id),
  };
}

export function cardEditCommand(
  port: PlotCommandPort,
  id: string,
  before: CardState,
  after: CardState,
  label: string,
): Command {
  return {
    label,
    undo: () => port.restoreCardState(id, before),
    redo: () => port.restoreCardState(id, after),
  };
}

// A displayed-text edit (rename / synopsis, written or not): undo and redo replay the
// text endpoint with the before / after values of the keys the edit changed.
export function cardTextCommand(
  port: PlotCommandPort,
  id: string,
  before: CardText,
  after: CardText,
  label: string,
): Command {
  return {
    label,
    undo: () => port.setCardText(id, before),
    redo: () => port.setCardText(id, after),
  };
}

// A deck's displayed-text edit (rename / synopsis): the same replay as a card's, through the
// deck text endpoint — the container's text while the deck is realized.
export function deckTextCommand(
  port: PlotCommandPort,
  id: string,
  before: CardText,
  after: CardText,
  label: string,
): Command {
  return {
    label,
    undo: () => port.setDeckText(id, before),
    redo: () => port.setDeckText(id, after),
  };
}

// A story-time move (ADR-0097 §4): `restore` is where the card sat before — right
// after the card that preceded it, or before the one that followed if it was first.
export function storyMoveCommand(
  port: PlotCommandPort,
  id: string,
  anchor: StoryAnchor,
  restore: StoryAnchor,
  label = "move in story time",
): Command {
  return {
    label,
    undo: () => port.moveCardInStoryTime(id, restore),
    redo: () => port.moveCardInStoryTime(id, anchor),
  };
}

// A card dropped into a deck or the loose area (ADR-0097 §4): `restore` is the same call
// pointed back — the old home, and (when the move changed story time) the old neighbour.
export function cardPlaceCommand(
  port: PlotCommandPort,
  id: string,
  place: PlaceRequest,
  restore: PlaceRequest,
  label = "move card",
): Command {
  return {
    label,
    undo: () => port.placeCard(id, restore),
    redo: () => port.placeCard(id, place),
  };
}

// A written card's scene moved to a chapter (ADR-0097 §8): `from` is where it sat, in the
// same parent / position terms the move API takes, so undo is the same call pointed back.
export function sceneMoveCommand(port: PlotCommandPort, plan: SceneMovePlan, label = "move scene"): Command {
  return {
    label,
    undo: () => port.moveScene(plan.nodeId, plan.from.parentId, plan.from.position),
    redo: () => port.moveScene(plan.nodeId, plan.to.parentId, plan.to.position),
  };
}

// A replay that the writer backs out of must leave the step where it was.
function ensureNotCancelled(outcome: CardTextOutcome): CardTextChoice | null {
  if (outcome === "cancelled") throw new UndoCancelled();
  return outcome;
}

// Detach (ADR-0097 §3): the card leaves `sceneId` and takes its title. `before` is the
// card's own state while it was written. Undo restores that own title + synopsis on the
// now-unwritten card, then re-attaches with "scene" (the scene was never touched, so
// nothing is asked). Redo detaches with the choice recorded at the original op.
export function detachCommand(
  port: PlotCommandPort,
  id: string,
  sceneId: string,
  before: CardState,
  choice: CardTextChoice | null,
  label = "detach scene",
): Command {
  return {
    label,
    undo: async () => {
      await port.setCardText(id, { title: before.title, synopsis: before.body });
      ensureNotCancelled(await port.attachCardScene(id, sceneId, "scene"));
    },
    redo: async () => {
      ensureNotCancelled(await port.detachCardScene(id, choice ?? undefined));
    },
  };
}

// Attach (ADR-0097 §3): `before` is the card's own state, `oldSummary` the scene's
// summary before the attach. Undo puts the scene's summary back if the attach changed
// it (while still written), detaches keeping the card's own synopsis, then restores the
// card's own title + synopsis (a detach would leave it the scene's). Redo attaches with
// the recorded choice.
export function attachCommand(
  port: PlotCommandPort,
  id: string,
  sceneId: string,
  before: CardState,
  oldSummary: string,
  choice: CardTextChoice | null,
  label = "attach scene",
): Command {
  return {
    label,
    undo: async () => {
      if ((await port.readSceneSummary(sceneId)) !== oldSummary) {
        await port.setCardText(id, { synopsis: oldSummary });
      }
      ensureNotCancelled(await port.detachCardScene(id, "card"));
      await port.setCardText(id, { title: before.title, synopsis: before.body });
    },
    redo: async () => {
      ensureNotCancelled(await port.attachCardScene(id, sceneId, choice ?? undefined));
    },
  };
}

// An edit that touches SEVERAL cards as ONE undo step (a beat MOVE card→card, #941:
// unlink off the source + link on the target). Restores every card's before/after,
// suppressing the per-restore board refetch on all but the last so the step rebuilds
// the board ONCE (the #909 storm fix, as deleteCardCommand does for its referrers).
export function cardEditManyCommand(
  port: PlotCommandPort,
  before: CardRef[],
  after: CardRef[],
  label: string,
): Command {
  const restoreAll = async (refs: CardRef[]): Promise<void> => {
    for (let i = 0; i < refs.length; i++) {
      await port.restoreCardState(refs[i].id, refs[i].state, i === refs.length - 1);
    }
  };
  return {
    label,
    undo: () => restoreAll(before),
    redo: () => restoreAll(after),
  };
}

export function createPlotlineCommand(
  port: PlotCommandPort,
  id: string,
  state: PlotlineState,
  label = "add plotline",
): Command {
  return {
    label,
    undo: () => port.deletePlotline(id),
    redo: () => port.recreatePlotline(id, state),
  };
}

export function deletePlotlineCommand(
  port: PlotCommandPort,
  id: string,
  state: PlotlineState,
  referrers: CardRef[],
  label = "delete plotline",
): Command {
  return {
    label,
    undo: async () => {
      await port.recreatePlotline(id, state, false);
      await Promise.all(referrers.map((r) => port.restoreCardState(r.id, r.state, false)));
      // One trailing refresh of BOTH the roster (the plotline is back) and the board.
      await Promise.all([port.refreshRoster(), port.refreshBoard()]);
    },
    redo: () => port.deletePlotline(id),
  };
}

export function plotlineEditCommand(
  port: PlotCommandPort,
  id: string,
  before: PlotlineState,
  after: PlotlineState,
  label: string,
): Command {
  return {
    label,
    undo: () => port.restorePlotlineState(id, before),
    redo: () => port.restorePlotlineState(id, after),
  };
}

// The character-arc twins of the three plotline command builders above (ADR-0080 §5).
// `cardsReferencingPlotline` is reused unchanged for an arc's referrers — it matches on
// a card's `plotline` field / `beats[].plotline_id`, which hold the HOLDER's id
// regardless of subtype (an arc is never a card's primary, so only the beats clause
// ever matches, but the id-matching predicate itself is subtype-agnostic).

export function createArcCommand(port: PlotCommandPort, id: string, state: ArcState, label = "add character arc"): Command {
  return {
    label,
    undo: () => port.deleteArc(id),
    redo: () => port.recreateArc(id, state),
  };
}

export function deleteArcCommand(
  port: PlotCommandPort,
  id: string,
  state: ArcState,
  referrers: CardRef[],
  label = "delete character arc",
): Command {
  return {
    label,
    undo: async () => {
      await port.recreateArc(id, state, false);
      await Promise.all(referrers.map((r) => port.restoreCardState(r.id, r.state, false)));
      await Promise.all([port.refreshArcRoster(), port.refreshBoard()]);
    },
    redo: () => port.deleteArc(id),
  };
}

export function arcEditCommand(
  port: PlotCommandPort,
  id: string,
  before: ArcState,
  after: ArcState,
  label: string,
): Command {
  return {
    label,
    undo: () => port.restoreArcState(id, before),
    redo: () => port.restoreArcState(id, after),
  };
}

export function createDeckCommand(port: PlotCommandPort, id: string, state: DeckState, label = "add deck"): Command {
  return {
    label,
    undo: () => port.deleteDeck(id),
    redo: () => port.recreateDeck(id, state),
  };
}

// A deck's members and child decks, captured at delete time: the cards whose home it was
// (`written` — a written card cannot be `place`d, so its home is restored another way), and
// the decks nested directly inside it with their whole state (their parent rides in it).
export type DeckMember = { id: string; written: boolean };
export type DeckChild = { id: string; state: DeckState };

export function deleteDeckCommand(
  port: PlotCommandPort,
  id: string,
  state: DeckState,
  members: DeckMember[],
  children: DeckChild[],
  container: string | null = null,
  label = "delete deck",
): Command {
  return {
    label,
    // The deck back under its id FIRST (a reference restored before its target exists would
    // be dangling-healed away), then its child decks and member cards — membership only, so
    // story time, untouched by the delete, brings the order back by itself — with the
    // per-item refetch suppressed and ONE refresh at the end (#909).
    undo: async () => {
      await port.recreateDeck(id, state, false);
      await Promise.all(children.map((c) => port.restoreDeckState(c.id, c.state, false)));
      // A realized deck is linked back to its container (the container's text was never touched,
      // so nothing is asked), and every member — each planned there — is restored by a save, not
      // a `place`, which would clear the plan.
      if (container) ensureNotCancelled(await port.attachDeckContainer(id, container, "scene"));
      await Promise.all(members.map((m) => port.restoreCardDeck(m.id, id, m.written || !!container, false)));
      await Promise.all([port.refreshDeckRoster(), port.refreshBoard()]);
    },
    redo: () => port.deleteDeck(id),
  };
}

export function deckEditCommand(
  port: PlotCommandPort,
  id: string,
  before: DeckState,
  after: DeckState,
  label: string,
): Command {
  return {
    label,
    undo: () => port.restoreDeckState(id, before),
    redo: () => port.restoreDeckState(id, after),
  };
}

// Seed mints one card per un-carded scene — undo deletes them all, redo recreates
// them under their ids. One command (the caretaker treats it as one step), not a
// per-card transaction: the whole batch reverses or replays together.
export function seedCommand(port: PlotCommandPort, created: CardRef[], label = "seed cards"): Command {
  return {
    label,
    // The whole batch in parallel with per-item refetch suppressed, one refresh at
    // the end — a 40-card seed reverses in ~1 board refetch, not 40 (#909).
    undo: async () => {
      await Promise.all(created.map((c) => port.deleteCard(c.id, false)));
      await port.refreshBoard();
    },
    redo: async () => {
      await Promise.all(created.map((c) => port.recreateCard(c.id, c.state, false)));
      await port.refreshBoard();
    },
  };
}

// Realize minted a scene FILE and attached it (S6b) — the one op with a file side
// effect. Undo deletes that scene — the card is its sole referent (one card per scene,
// ADR-0097 §1) — behind a suppressible confirm when the scene holds prose. Redo
// re-mints, capturing the NEW scene id (mutable closure state) so the next undo targets
// it. The check that the card still holds the scene reads the LIVE board at undo time.
// A card realized from a PLAN (ADR-0097 §6) also gets its plan back on undo — `plan` — and
// so does every planned card the write re-anchored — `reanchored`, each with the anchor it
// had — since realize cleared and moved them.
export type PlannedPlace = { planned_in: string; planned_after: string | null };
export type ReanchoredCard = { id: string; planned_after: string | null };

export function realizeCommand(
  port: PlotCommandPort,
  cardId: string,
  parentId: string | null,
  sceneId: string,
  plan: PlannedPlace | null = null,
  reanchored: ReanchoredCard[] = [],
  label = "write card as scene",
): Command {
  let scene = sceneId;
  return {
    label,
    undo: async () => {
      const referents = port.sceneReferents(scene);
      if (!referents.includes(cardId)) return; // realize already reversed elsewhere — no-op
      const read = await port.readScene(scene); // the scene will be deleted
      if (read.body.trim().length > 0 && !(await port.confirmSceneDelete(read))) {
        // Declined a written scene's deletion: throw BEFORE mutating so the caretaker
        // leaves this single-command step undoable (UndoCancelled → "Undo cancelled").
        throw new UndoCancelled();
      }
      await port.deleteScene(scene); // deletes the scene + purges the card's ref (detaches)
      if (!plan) return;
      await port.placeCard(cardId, { to: plan });
      for (const other of reanchored) {
        await port.placeCard(other.id, { to: { planned_in: plan.planned_in, planned_after: other.planned_after } });
      }
    },
    redo: async () => {
      scene = (await port.realizeCard(cardId, parentId)).sceneId; // re-mint; track the new scene id
    },
  };
}

// A deck's realize (ADR-0097 §7) made a container and planned the deck's unwritten cards in it —
// no scene. Undo takes it back in the order that loses nothing: each planned card goes home to
// the deck (membership; the plan clears), the deck is detached keeping its own synopsis and its
// own title is put back, then the container the realize made is deleted — behind a suppressible
// confirm when something has been put under it since. Redo realizes again; the new container's
// id (and plan) replace the old in the closure, so the next undo targets them.
export function realizeDeckCommand(
  port: PlotCommandPort,
  deckId: string,
  containerId: string,
  planned: string[],
  before: CardText,
  label = "realize deck",
): Command {
  let container = containerId;
  let cards = planned;
  return {
    label,
    undo: async () => {
      if (port.containerHoldsNodes(container) && !(await port.confirmContainerDelete(before.title ?? ""))) {
        throw new UndoCancelled(); // before mutating, so the step stays undoable
      }
      for (const id of cards) await port.placeCard(id, { to: { deck: deckId } });
      ensureNotCancelled(await port.detachDeckContainer(deckId, "card"));
      await port.setDeckText(deckId, before);
      await port.deleteContainer(container);
    },
    redo: async () => {
      ({ containerId: container, planned: cards } = await port.realizeDeck(deckId));
    },
  };
}

// Detach a realized deck (ADR-0097 §7): the container stays. `before` is the deck's own title
// and synopsis, held while it was realized. Undo puts them back on the now-unrealized deck, then
// re-attaches with "scene" (the container was never touched, so nothing is asked). Redo
// detaches with the choice recorded at the original op.
export function detachDeckCommand(
  port: PlotCommandPort,
  deckId: string,
  containerId: string,
  before: CardText,
  choice: CardTextChoice | null,
  label = "detach deck",
): Command {
  return {
    label,
    undo: async () => {
      await port.setDeckText(deckId, before);
      ensureNotCancelled(await port.attachDeckContainer(deckId, containerId, "scene"));
    },
    redo: async () => {
      ensureNotCancelled(await port.detachDeckContainer(deckId, choice ?? undefined));
    },
  };
}

// ── Recorder ─────────────────────────────────────────────────────────────────
// Wraps the capture → run-forward-op → record pattern for the PlotEditor handlers,
// so the component stays thin and the orchestration is unit-testable with a fake
// port + record sink. A field edit that changed nothing records nothing (the
// "a drag that went nowhere records no command" rule).

// Whole-state equality (a no-op edit records nothing). One helper for every node
// kind — a CardState / PlotlineState / ArcState / DeckState is a JSON-serializable
// {title, body, metadata}.
function statesEqual(
  a: CardState | PlotlineState | ArcState | DeckState,
  b: CardState | PlotlineState | ArcState | DeckState,
): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export class PlotUndoRecorder {
  readonly #port: PlotCommandPort;
  readonly #record: (command: Command) => void;
  readonly #getProjection: () => PlotBoardProjection | null;
  // Resolves once no undo/redo is in flight (#909). Awaited at the START of every
  // op so a gesture fired during a still-running undo QUEUES behind it and records
  // cleanly, instead of hitting `record()` mid-replay (which throws). Defaults to a
  // resolved promise so a caller that doesn't wire it (tests, a layout-only surface)
  // is unaffected. Residual: an op already in flight when an undo STARTS isn't
  // gated — rare, same non-corrupting throw.
  readonly #whenIdle: () => Promise<void>;

  constructor(
    port: PlotCommandPort,
    record: (command: Command) => void,
    getProjection: () => PlotBoardProjection | null,
    whenIdle: () => Promise<void> = () => Promise.resolve(),
  ) {
    this.#port = port;
    this.#record = record;
    this.#getProjection = getProjection;
    this.#whenIdle = whenIdle;
  }

  async #captureCards(ids: string[]): Promise<CardRef[]> {
    return Promise.all(ids.map(async (id) => ({ id, state: await this.#port.getCardState(id) })));
  }

  /** A card metadata/synopsis/title edit (reassign, page-status, beat link/unlink,
   *  causal link/unlink): capture the whole card before + after the
   *  forward op; record only a real change. Returns the op's own result. */
  async cardEdit<T>(id: string, label: string, op: () => Promise<T>): Promise<T> {
    await this.#whenIdle();
    const before = await this.#port.getCardState(id);
    const result = await op();
    const after = await this.#port.getCardState(id);
    if (!statesEqual(before, after)) {
      this.#record(cardEditCommand(this.#port, id, before, after, label));
    }
    return result;
  }

  /** An edit spanning several cards recorded as ONE step (a beat MOVE card→card, #941).
   *  Captures every id's before + after around the op; records only if something
   *  changed. Ids should be distinct (the move passes [from, to]). */
  async cardEditMany(ids: string[], label: string, op: () => Promise<void>): Promise<void> {
    await this.#whenIdle();
    const before = await this.#captureCards(ids);
    await op();
    const after = await this.#captureCards(ids);
    if (before.some((b, i) => !statesEqual(b.state, after[i].state))) {
      this.#record(cardEditManyCommand(this.#port, before, after, label));
    }
  }

  /** A card's displayed title and/or synopsis edit (ADR-0097 §3). The before values
   *  come from the board's card data — what the card SHOWS, the scene's while written —
   *  so one command covers written and unwritten cards. Records only a real change. */
  async cardTextEdit(id: string, label: string, edit: CardText): Promise<void> {
    await this.#whenIdle();
    const shown = this.#getProjection()?.cards.find((c) => c.id === id);
    await this.#port.setCardText(id, edit);
    if (!shown) return;
    const before: CardText = {};
    const after: CardText = {};
    if (edit.title !== undefined && edit.title !== shown.title) {
      before.title = shown.title;
      after.title = edit.title;
    }
    if (edit.synopsis !== undefined && edit.synopsis !== shown.synopsis) {
      before.synopsis = shown.synopsis;
      after.synopsis = edit.synopsis;
    }
    if (Object.keys(after).length > 0) this.#record(cardTextCommand(this.#port, id, before, after, label));
  }

  /** Move a card in story time, recorded as ONE step. The card's neighbour is read off
   *  the projection BEFORE the move so undo can put it back beside it; a move to where
   *  the card already is records (and sends) nothing. */
  async storyMove(cardId: string, anchor: StoryAnchor, label: string): Promise<void> {
    await this.#whenIdle();
    const cards = this.#getProjection()?.cards ?? [];
    if (isStoryNoOp(cards, cardId, anchor)) return;
    const restore = storyRestoreAnchor(cards, cardId);
    await this.#port.moveCardInStoryTime(cardId, anchor);
    if (restore) this.#record(storyMoveCommand(this.#port, cardId, anchor, restore, label));
  }

  /** Place a card in a deck or the loose area, and/or beside a neighbour in story time
   *  (ADR-0097 §4), recorded as ONE step. The old home and the old neighbour are read off
   *  the projection BEFORE the move so undo can put them back; whichever half would change
   *  nothing is not sent, and a drop that changes neither records nothing. */
  async cardPlace(cardId: string, place: PlaceRequest, label = "move card"): Promise<void> {
    await this.#whenIdle();
    const cards = this.#getProjection()?.cards ?? [];
    const card = cards.find((c) => c.id === cardId);
    // Where the card is NOW, as a `place` target: its plan when it has one (ADR-0097 §6),
    // else its home deck, else the loose area.
    const homeNow: PlaceTo =
      card?.planned_in && !card.scene
        ? { planned_in: card.planned_in, planned_after: card.planned_after ?? null }
        : card?.deck
          ? { deck: card.deck }
          : { loose: true };
    const sameHome = !place.to || JSON.stringify(place.to) === JSON.stringify(homeNow);
    const sameStory = !place.story || isStoryNoOp(cards, cardId, place.story);
    if (sameHome && sameStory) return;
    const forward: PlaceRequest = {
      ...(sameHome ? {} : { to: place.to }),
      ...(sameStory ? {} : { story: place.story }),
    };
    const anchor = forward.story ? storyRestoreAnchor(cards, cardId) : null;
    const restore: PlaceRequest = { ...(forward.to ? { to: homeNow } : {}), ...(anchor ? { story: anchor } : {}) };
    await this.#port.placeCard(cardId, forward);
    if (restore.to || restore.story) this.#record(cardPlaceCommand(this.#port, cardId, forward, restore, label));
  }

  /** Detach a card from its scene, recorded. The store asks which synopsis survives
   *  when it must; backing out records nothing. */
  async detach(cardId: string): Promise<void> {
    await this.#whenIdle();
    const before = await this.#port.getCardState(cardId);
    const scene = before.metadata.scene;
    if (typeof scene !== "string" || !scene) return;
    const outcome = await this.#port.detachCardScene(cardId);
    if (outcome === "cancelled") return;
    this.#record(detachCommand(this.#port, cardId, scene, before, outcome));
  }

  /** Attach a card to an existing scene, recorded (the Attach picker). */
  async attach(cardId: string, sceneId: string): Promise<void> {
    await this.#whenIdle();
    const before = await this.#port.getCardState(cardId);
    const oldSummary = await this.#port.readSceneSummary(sceneId);
    const outcome = await this.#port.attachCardScene(cardId, sceneId);
    if (outcome === "cancelled") return;
    this.#record(attachCommand(this.#port, cardId, sceneId, before, oldSummary, outcome));
  }

  /** A plotline rename / recolour / beat-roster edit. Returns the op's own result
   *  (the saved entry the node resyncs its revision from). */
  async plotlineEdit<T>(id: string, label: string, op: () => Promise<T>): Promise<T> {
    await this.#whenIdle();
    const before = await this.#port.getPlotlineState(id);
    const result = await op();
    const after = await this.#port.getPlotlineState(id);
    if (!statesEqual(before, after)) {
      this.#record(plotlineEditCommand(this.#port, id, before, after, label));
    }
    return result;
  }

  /** A character-arc rename / recolour / rebind-character / beat-roster edit
   *  (ADR-0080 §5). Returns the op's own result, mirroring `plotlineEdit`. */
  async arcEdit<T>(id: string, label: string, op: () => Promise<T>): Promise<T> {
    await this.#whenIdle();
    const before = await this.#port.getArcState(id);
    const result = await op();
    const after = await this.#port.getArcState(id);
    if (!statesEqual(before, after)) {
      this.#record(arcEditCommand(this.#port, id, before, after, label));
    }
    return result;
  }

  /** A deck rename / synopsis / re-parent edit (ADR-0097 §2). Returns the op's own result
   *  (the saved entry), mirroring `plotlineEdit`. */
  async deckEdit<T>(id: string, label: string, op: () => Promise<T>): Promise<T> {
    await this.#whenIdle();
    const before = await this.#port.getDeckState(id);
    const result = await op();
    const after = await this.#port.getDeckState(id);
    if (!statesEqual(before, after)) {
      this.#record(deckEditCommand(this.#port, id, before, after, label));
    }
    return result;
  }

  /** Create a deck via the given forward op (returns the new id); record it. */
  async createDeck(create: () => Promise<string>, label?: string): Promise<string> {
    await this.#whenIdle();
    const id = await create();
    const state = await this.#port.getDeckState(id);
    this.#record(createDeckCommand(this.#port, id, state, label));
    return id;
  }

  /** Delete a deck. Called AFTER the user confirmed — captures the deck, the cards that
   *  call it home and the decks nested directly in it (read off the projection), runs the
   *  delete, records. */
  async deleteDeck(id: string, del: () => Promise<void>): Promise<void> {
    await this.#whenIdle();
    const state = await this.#port.getDeckState(id);
    const projection = this.#getProjection();
    const members = (projection?.cards ?? [])
      .filter((c) => c.deck === id)
      .map((c) => ({ id: c.id, written: c.scene != null }));
    const children = await Promise.all(
      (projection?.decks ?? [])
        .filter((d) => d.parent === id)
        .map(async (d) => ({ id: d.id, state: await this.#port.getDeckState(d.id) })),
    );
    const container = projection?.decks.find((d) => d.id === id)?.realized_container ?? null;
    await del();
    this.#record(deleteDeckCommand(this.#port, id, state, members, children, container));
  }

  /** A deck's displayed title and/or synopsis edit (ADR-0097 §3) — the container's while the
   *  deck is realized. Before values come from what the board shows; records only a real change. */
  async deckTextEdit(id: string, label: string, edit: CardText): Promise<void> {
    await this.#whenIdle();
    const shown = this.#getProjection()?.decks.find((d) => d.id === id);
    await this.#port.setDeckText(id, edit);
    if (!shown) return;
    const before: CardText = {};
    const after: CardText = {};
    if (edit.title !== undefined && edit.title !== shown.title) {
      before.title = shown.title;
      after.title = edit.title;
    }
    if (edit.synopsis !== undefined && edit.synopsis !== shown.synopsis) {
      before.synopsis = shown.synopsis;
      after.synopsis = edit.synopsis;
    }
    if (Object.keys(after).length > 0) this.#record(deckTextCommand(this.#port, id, before, after, label));
  }

  /** Realize a deck as a manuscript container, recorded (ADR-0097 §7). A refused realize
   *  (the level list allows none here) throws before anything is recorded. */
  async realizeDeck(deckId: string): Promise<void> {
    await this.#whenIdle();
    const shown = this.#getProjection()?.decks.find((d) => d.id === deckId);
    const { containerId, planned } = await this.#port.realizeDeck(deckId);
    const before = { title: shown?.title ?? "", synopsis: shown?.synopsis ?? "" };
    this.#record(realizeDeckCommand(this.#port, deckId, containerId, planned, before));
  }

  /** Detach a realized deck from its container, recorded. The store asks which synopsis the
   *  deck keeps when it must; backing out records nothing. */
  async detachDeck(deckId: string): Promise<void> {
    await this.#whenIdle();
    const container = this.#getProjection()?.decks.find((d) => d.id === deckId)?.realized_container;
    if (!container) return;
    const own = await this.#port.getDeckState(deckId);
    const outcome = await this.#port.detachDeckContainer(deckId);
    if (outcome === "cancelled") return;
    this.#record(detachDeckCommand(this.#port, deckId, container, { title: own.title, synopsis: own.body }, outcome));
  }

  /** Create a card via the given forward op (returns the new id); record it. */
  async createCard(create: () => Promise<string>, label?: string): Promise<string> {
    await this.#whenIdle();
    const id = await create();
    const state = await this.#port.getCardState(id);
    this.#record(createCardCommand(this.#port, id, state, label));
    return id;
  }

  /** Create a plotline (ad-hoc or instantiated from a template) via the forward op;
   *  record it. Undo/redo restore the whole plotline (beats + lineage), so the
   *  template behind it is irrelevant to the reversal. */
  async createPlotline(create: () => Promise<string>, label?: string): Promise<string> {
    await this.#whenIdle();
    const id = await create();
    const state = await this.#port.getPlotlineState(id);
    this.#record(createPlotlineCommand(this.#port, id, state, label));
    return id;
  }

  /** Create a character arc via the given forward op (returns the new id, already
   *  minted — e.g. by the shared template-instantiate call, ADR-0080 §5); record it.
   *  Mirrors `createPlotline` but on the ARC port methods, so undo/redo never route
   *  through the plotline substrate (which would recreate it as a plotline). */
  async createArc(create: () => Promise<string>, label?: string): Promise<string> {
    await this.#whenIdle();
    const id = await create();
    const state = await this.#port.getArcState(id);
    this.#record(createArcCommand(this.#port, id, state, label));
    return id;
  }

  /** Delete a card. Called AFTER the user confirmed — captures the card + its
   *  inbound referrers, runs the delete, records. */
  async deleteCard(id: string, del: () => Promise<void>): Promise<void> {
    await this.#whenIdle();
    const state = await this.#port.getCardState(id);
    const projection = this.#getProjection();
    const referrers = projection ? await this.#captureCards(cardsReferencingCard(projection, id)) : [];
    await del();
    this.#record(deleteCardCommand(this.#port, id, state, referrers));
  }

  async deletePlotline(id: string, del: () => Promise<void>): Promise<void> {
    await this.#whenIdle();
    const state = await this.#port.getPlotlineState(id);
    const projection = this.#getProjection();
    const referrers = projection ? await this.#captureCards(cardsReferencingPlotline(projection, id)) : [];
    await del();
    this.#record(deletePlotlineCommand(this.#port, id, state, referrers));
  }

  /** Delete a character arc (ADR-0080 §5). Mirrors `deletePlotline`: captures the arc
   *  + every card that fulfils one of its change-beats (never its primary — an arc is
   *  never primary), runs the delete, records. */
  async deleteArc(id: string, del: () => Promise<void>): Promise<void> {
    await this.#whenIdle();
    const state = await this.#port.getArcState(id);
    const projection = this.#getProjection();
    const referrers = projection ? await this.#captureCards(cardsReferencingPlotline(projection, id)) : [];
    await del();
    this.#record(deleteArcCommand(this.#port, id, state, referrers));
  }

  /** Seed cards from the manuscript. The forward op returns the ids it CREATED (the
   *  store diffs the seed endpoint's result against the board's current cards), so this
   *  never depends on a lagging projection prop; capture their state + record one step.
   *  Nothing created (an idempotent re-run) records nothing. */
  async seed(seedOp: () => Promise<string[]>): Promise<void> {
    await this.#whenIdle();
    const created = await seedOp();
    if (created.length === 0) return;
    this.#record(seedCommand(this.#port, await this.#captureCards(created)));
  }

  /** Realize a card into a scene, recorded (S6b). Mints the scene via the port,
   *  records a command whose undo deletes it (sole referent, suppressible confirm).
   *  A realize that produced no scene (a 409 already-attached, or an error) records
   *  nothing. */
  async realize(cardId: string, parentId: string | null): Promise<void> {
    await this.#whenIdle();
    // A planned card's plan, and every card's anchor, as they are BEFORE the write: realize
    // clears the plan and re-anchors the cards that followed (ADR-0097 §6), undo restores both.
    const cards = this.#getProjection()?.cards ?? [];
    const card = cards.find((c) => c.id === cardId);
    const plan: PlannedPlace | null =
      card?.planned_in && !card.scene ? { planned_in: card.planned_in, planned_after: card.planned_after ?? null } : null;
    const anchors = new Map(cards.map((c) => [c.id, c.planned_after ?? null]));
    const { sceneId, reanchored } = await this.#port.realizeCard(cardId, parentId);
    if (!sceneId) return;
    const moved = reanchored.map((id) => ({ id, planned_after: anchors.get(id) ?? null }));
    this.#record(realizeCommand(this.#port, cardId, parentId, sceneId, plan, plan ? moved : []));
  }

  /** Move a written card's scene to a chapter (ADR-0097 §8), recorded as ONE step. The slot
   *  is worked out from the manuscript tree as it is now; a move to where the scene already
   *  sits records (and sends) nothing. */
  async sceneMove(sceneId: string, parentId: string, near: SceneNear, label = "move scene"): Promise<void> {
    await this.#whenIdle();
    const plan = planSceneMove(this.#port.structure(), sceneId, parentId, near);
    if (!plan) return;
    await this.#port.moveScene(plan.nodeId, plan.to.parentId, plan.to.position);
    this.#record(sceneMoveCommand(this.#port, plan, label));
  }
}

// The real port: the plotBoard / plotlines store ops behind the interface.
export function defaultPlotCommandPort(): PlotCommandPort {
  return {
    deleteCard,
    getCardState,
    restoreCardState,
    recreateCard,
    deletePlotline,
    getPlotlineState,
    restorePlotlineState,
    recreatePlotline,
    deleteArc,
    getArcState,
    restoreArcState,
    recreateArc,
    deleteDeck,
    getDeckState,
    restoreDeckState,
    recreateDeck,
    restoreCardDeck,
    refreshBoard: refreshAfterMutation,
    refreshRoster,
    refreshArcRoster,
    refreshDeckRoster,
    realizeCard,
    structure: currentStructure,
    moveScene: moveSceneNode,
    sceneReferents,
    readScene,
    deleteScene,
    attachCardScene,
    detachCardScene,
    setCardText,
    readSceneSummary,
    moveCardInStoryTime,
    placeCard: placeCardOnBoard,
    realizeDeck,
    setDeckText,
    attachDeckContainer,
    detachDeckContainer,
    containerHoldsNodes,
    deleteContainer: deleteContainerNode,
    confirmContainerDelete: (title) =>
      new Promise<boolean>((resolve) => {
        confirmService.request({
          title: "Delete chapter?",
          message: `Undoing realize will delete the chapter “${title || "Untitled"}” and what has been put in it.`,
          confirmLabel: "Delete chapter",
          destructive: true,
          cannotBeUndone: true,
          dontShowAgainKey: "plot-realize-deck-undo-delete-container",
          onConfirm: async () => resolve(true),
          onCancel: () => resolve(false),
        });
      }),
    // The suppressible confirm before deleting a written scene, as a Promise<boolean>:
    // confirm → true, cancel/backdrop → false (via the confirmService onCancel added
    // for this), and a suppressed prior "don't show again" resolves true immediately.
    confirmSceneDelete: (scene) =>
      new Promise<boolean>((resolve) => {
        confirmService.request({
          title: "Delete scene?",
          message: `Undoing realize will delete the scene “${scene.title || "Untitled"}” and its prose.`,
          confirmLabel: "Delete scene",
          destructive: true,
          cannotBeUndone: true,
          dontShowAgainKey: "plot-realize-undo-delete-scene",
          onConfirm: async () => resolve(true),
          onCancel: () => resolve(false),
        });
      }),
  };
}
