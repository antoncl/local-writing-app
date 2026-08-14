"""Render a `PlotContext` packet into a prompt-facing text block (ADR-0048 S8b).

The board's plot state (8a's `read_plot_context`) becomes a compact, readable
block a brainstorm prompt drops in so the model can reason about the plot: the
plotlines with their full beat rosters (the requirements — including beats no card
fulfils yet, the gaps), the cards with their synopses / fulfilled beats / causal
edges (the implementation), and the spoiler-gate framing (how many cards are
withheld ahead). A plotline is a plot-template instance (ADR-0053 §1), so one
plotline set carries both the thread and its beat structure.

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


def _plot_context_header(packet: PlotContext) -> str:
    header = f"<plot_context completeness={quoteattr(packet.completeness)}"
    if packet.as_of_scene_id:
        header += f" as_of_scene={quoteattr(packet.as_of_scene_id)}"
    if packet.omitted_cards:
        # Named for what it MEANS to the model: more cards exist past the reading
        # point but are withheld (the spoiler gate) — it should not invent them.
        header += f" cards_withheld_ahead={quoteattr(str(packet.omitted_cards))}"
    return header + ">"


def _render_plotline(plotline) -> list[str]:
    """One `<plotline>` element: its structural guidance then its beat roster
    (ADR-0053 §1). `<use_guidance>` (how to use the structure as a diagnostic lens)
    and `<diagnostic_questions>` (what to ask of the draft) are the template's
    guidance, snapshotted at instantiate — so the model measures cards against the
    structure's intent, not just per-beat one-liners. A plotline with no guidance and
    no beats (ad-hoc / empty) self-closes; otherwise each beat is a `<beat>` element,
    with guidance as element text when present, self-closing when not."""
    attrs = f"title={quoteattr(plotline.title)}"
    if plotline.source_template_name:
        attrs += f" structure={quoteattr(plotline.source_template_name)}"
    body: list[str] = []
    if plotline.ai_guidance.strip():
        body.append(f"      <use_guidance>{escape(plotline.ai_guidance.strip())}</use_guidance>")
    if plotline.diagnostic_questions:
        body.append("      <diagnostic_questions>")
        body.extend(f"        <question>{escape(q)}</question>" for q in plotline.diagnostic_questions)
        body.append("      </diagnostic_questions>")
    for beat in plotline.beats:
        battrs = f"title={quoteattr(beat.title)}"
        if beat.function:
            battrs += f" function={quoteattr(beat.function)}"
        if beat.guidance.strip():
            body.append(f"      <beat {battrs}>{escape(beat.guidance.strip())}</beat>")
        else:
            body.append(f"      <beat {battrs} />")
    if not body:
        return [f"    <plotline {attrs} />"]
    return [f"    <plotline {attrs}>", *body, "    </plotline>"]


def _render_card(card, card_titles: dict[str, str]) -> list[str]:
    """One `<card>` element: its attrs (plotline / reading order / page status), the
    synopsis, the beats it fulfils, and the cards it leads to (titles over ids)."""
    attrs = f"title={quoteattr(card.title)}"
    if card.plotline_title:
        attrs += f" plotline={quoteattr(card.plotline_title)}"
    if card.sequence is not None:
        attrs += f" reading_order={quoteattr(str(card.sequence))}"
    if card.page_status:
        attrs += f" page_status={quoteattr(card.page_status)}"
    lines = [f"    <card {attrs}>"]
    if card.synopsis.strip():
        lines.append(f"      <synopsis>{escape(card.synopsis.strip())}</synopsis>")
    for beat in card.beats:
        lines.append(
            f"      <fulfils beat={quoteattr(beat.title)} plotline={quoteattr(beat.plotline_title)} />"
        )
    for target in card.causal_out:
        lines.append(f"      <leads_to card={quoteattr(card_titles.get(target, target))} />")
    lines.append("    </card>")
    return lines


def render_plot_context(packet: PlotContext | None) -> str:
    if packet is None:
        return ""
    card_titles = {card.id: card.title for card in packet.cards}
    lines: list[str] = [_plot_context_header(packet)]

    if packet.plotlines:
        lines.append("  <plotlines>")
        for plotline in packet.plotlines:
            lines.extend(_render_plotline(plotline))
        lines.append("  </plotlines>")

    if packet.cards:
        lines.append("  <cards>")
        for card in packet.cards:
            lines.extend(_render_card(card, card_titles))
        lines.append("  </cards>")

    lines.append("</plot_context>")
    return "\n".join(lines)
