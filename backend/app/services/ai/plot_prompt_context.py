"""Render a `PlotContext` packet into a prompt-facing text block (ADR-0048 S8b).

The board's plot state (8a's `read_plot_context`) becomes a compact, readable
block a brainstorm prompt drops in so the model can reason about the plot: the
arcs with their full beat rosters (the requirements — including beats no card
fulfils yet, the gaps), the cards with their synopses / fulfilled beats / causal
edges (the implementation), and the spoiler-gate framing (how many cards are
withheld ahead).

This is context INPUT. It carries none of the quarry's claims/evidence apparatus
(migration principle 2), and it is NOT the `<plot_suggestions>` output transport
(principle 1) — the AI writes back through the JSON node-patch loop (the same
commit shape as `revise-entry`), never by emitting this block.

The shape is an XML-ish envelope, matching how the app already hands the model
lore/context (`_format_lore_block`); titles are used over ids wherever one exists
so the model reasons in the writer's own vocabulary.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from app.models import PlotContext


def render_plot_context(packet: PlotContext | None) -> str:
    if packet is None:
        return ""
    card_titles = {card.id: card.title for card in packet.cards}
    lines: list[str] = []

    header = f"<plot_context completeness={quoteattr(packet.completeness)}"
    if packet.as_of_scene_id:
        header += f" as_of_scene={quoteattr(packet.as_of_scene_id)}"
    if packet.omitted_cards:
        # Named for what it MEANS to the model: more cards exist past the reading
        # point but are withheld (the spoiler gate) — it should not invent them.
        header += f" cards_withheld_ahead={quoteattr(str(packet.omitted_cards))}"
    header += ">"
    lines.append(header)

    if packet.plotlines:
        lines.append("  <plotlines>")
        for plotline in packet.plotlines:
            lines.append(f"    <plotline title={quoteattr(plotline.title)} />")
        lines.append("  </plotlines>")

    if packet.arcs:
        lines.append("  <arcs>")
        for arc in packet.arcs:
            attrs = f"title={quoteattr(arc.title)}"
            if arc.source_template_name:
                attrs += f" structure={quoteattr(arc.source_template_name)}"
            lines.append(f"    <arc {attrs}>")
            for beat in arc.beats:
                battrs = f"title={quoteattr(beat.title)}"
                if beat.function:
                    battrs += f" function={quoteattr(beat.function)}"
                if beat.guidance.strip():
                    lines.append(f"      <beat {battrs}>{escape(beat.guidance.strip())}</beat>")
                else:
                    lines.append(f"      <beat {battrs} />")
            lines.append("    </arc>")
        lines.append("  </arcs>")

    if packet.cards:
        lines.append("  <cards>")
        for card in packet.cards:
            attrs = f"title={quoteattr(card.title)}"
            if card.plotline_title:
                attrs += f" plotline={quoteattr(card.plotline_title)}"
            if card.sequence is not None:
                attrs += f" reading_order={quoteattr(str(card.sequence))}"
            if card.page_status:
                attrs += f" page_status={quoteattr(card.page_status)}"
            lines.append(f"    <card {attrs}>")
            if card.synopsis.strip():
                lines.append(f"      <synopsis>{escape(card.synopsis.strip())}</synopsis>")
            for beat in card.beats:
                lines.append(
                    f"      <fulfils beat={quoteattr(beat.title)} arc={quoteattr(beat.instance_title)} />"
                )
            for target in card.causal_out:
                lines.append(f"      <leads_to card={quoteattr(card_titles.get(target, target))} />")
            lines.append("    </card>")
        lines.append("  </cards>")

    lines.append("</plot_context>")
    return "\n".join(lines)
