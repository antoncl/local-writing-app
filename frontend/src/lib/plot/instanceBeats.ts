// Shared reader for a plot arc's specialized beats (ADR-0048 S7). Both the arc rail
// (5a, PlotArcRail) and the card's beat picker (5b, PlotBeatPicker) list an
// instance's `instance_beats`, so the metadata-shape read lives here in one place —
// a change (a renamed member, a stricter guard) is made once, and the two surfaces
// can't drift on what a beat row looks like.

import type { TemplateInstanceSummary } from "@/lib/types";

// A specialized beat as it rides in an instance's metadata. Only the id + title are
// read on the board surfaces; the arc editor owns the rest of the group's members.
export type InstanceBeatRow = { id?: string; title?: string };

export function instanceBeats(arc: TemplateInstanceSummary): InstanceBeatRow[] {
  const value = arc.metadata?.instance_beats;
  return Array.isArray(value) ? (value as InstanceBeatRow[]) : [];
}
