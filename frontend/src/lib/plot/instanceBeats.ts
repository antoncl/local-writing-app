// Shared reader for a plot arc's specialized beats (ADR-0048 S7). The arc rail
// (5a/#824, PlotArcRail) lists an instance's `instance_beats` as the drag palette, so
// the metadata-shape read lives here in one place — a change (a renamed member, a
// stricter guard) is made once, and every surface reads a beat row the same way.

import type { TemplateInstanceSummary } from "@/lib/types";

// A specialized beat as it rides in an instance's metadata. Only the id + title are
// read on the board surfaces; the arc editor owns the rest of the group's members.
export type InstanceBeatRow = { id?: string; title?: string };

export function instanceBeats(arc: TemplateInstanceSummary): InstanceBeatRow[] {
  const value = arc.metadata?.instance_beats;
  return Array.isArray(value) ? (value as InstanceBeatRow[]) : [];
}
