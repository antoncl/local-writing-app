// The context picker's Plot axis containers (ADR-0074 slice 6, #2439). Each is
// a live selector over plot cards — the stored spec carries the `plot:card`
// constraint, so a picked container expands to its current cards at invocation.
//
//   - a plotline: the cards whose `plotline` points at it;
//   - a deck (ADR-0097 §2): the cards whose home deck (`plot_deck`) is it;
//   - "Loose cards": the cards in neither — no plotline AND no deck.
//
// Plotlines alone left every card without a plotline unreachable (#2439) —
// typically the off-page cards: backstory in a deck, or a loose idea. With
// decks + loose, every card has a row. A card in a deck that is also on a
// plotline shows under both, like a lore entry under two tags.
import type { NodePickerRef } from "@/lib/pickerTypes";
import type { PlotlineSummary } from "@/lib/plotCardTypes";
import type { ViewSpec } from "@/lib/types";

export const LOOSE_CARDS_REF_ID = "plotcards:loose";

function cardsWhere(...fields: object[]): ViewSpec {
  return { kind: "plot", expr: { intersect: [{ type: "plot:card" }, ...fields.map((field) => ({ field }))] } } as ViewSpec;
}

// Plotlines first, then decks, then the loose bucket. Empty plotlines and decks
// stay (authored containers, like an act with no scenes yet); the caller drops
// an empty loose bucket, which is not authored.
export function plotPickerSelectorRefs(plotEntries: PlotlineSummary[]): NodePickerRef[] {
  const plotlines = plotEntries
    .filter((p) => p.entry_type === "plot:plotline")
    .map<NodePickerRef>((p) => ({
      id: `plotline:${p.id}`,
      kind: "plot",
      title: p.title,
      entry_type: "plot:plotline",
      selector: cardsWhere({ key: "plotline", op: "overlap", value: p.id }),
    }));
  const decks = plotEntries
    .filter((p) => p.entry_type === "plot:deck")
    .map<NodePickerRef>((p) => ({
      id: `deck:${p.id}`,
      kind: "plot",
      title: p.title,
      entry_type: "plot:deck",
      selector: cardsWhere({ key: "plot_deck", op: "overlap", value: p.id }),
    }));
  const loose: NodePickerRef = {
    id: LOOSE_CARDS_REF_ID,
    kind: "plot",
    title: "Loose cards",
    entry_type: "plot:card",
    selector: cardsWhere({ key: "plotline", op: "unset" }, { key: "plot_deck", op: "unset" }),
  };
  return [...plotlines, ...decks, loose];
}
