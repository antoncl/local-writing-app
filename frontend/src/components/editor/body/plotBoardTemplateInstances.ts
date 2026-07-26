import { api } from "@/lib/api";
import type { PlotNode, PlotTemplateInstancePoint } from "@/lib/types";

export async function saveTemplateInstancePoint(
  instance: PlotNode,
  plotPointId: string,
  patch: Partial<PlotTemplateInstancePoint>,
): Promise<PlotNode | null> {
  const templateInstance = instance.template_instance;
  if (!templateInstance) return null;
  const nextPoints = (templateInstance.plot_points ?? []).map((point) =>
    point.plot_point_id === plotPointId
      ? { ...point, ...patch, metadata: point.metadata ?? {} }
      : point,
  );
  const nextPoint = nextPoints.find((point) => point.plot_point_id === plotPointId);
  if (!nextPoint) return null;
  const nextPointNotes = {
    ...(templateInstance.point_notes ?? {}),
    [plotPointId]: {
      ...(templateInstance.point_notes?.[plotPointId] ?? {}),
      local_label: nextPoint.local_label || nextPoint.title || "",
      notes: nextPoint.notes ?? "",
      author_intent: nextPoint.author_intent ?? "",
      expected_role: nextPoint.expected_role ?? "",
      open_questions: nextPoint.open_questions ?? [],
      status: nextPoint.status ?? "unplanned",
      metadata: nextPoint.metadata ?? {},
    },
  };

  return api.savePlotNode(instance.id, {
    title: instance.title,
    entry_type: instance.entry_type,
    body: instance.body ?? "",
    metadata: instance.metadata ?? {},
    template: instance.template ?? null,
    template_instance: {
      ...templateInstance,
      plot_points: nextPoints,
      point_notes: nextPointNotes,
      metadata: templateInstance.metadata ?? {},
    },
    board: instance.board ?? null,
    layout: instance.layout ?? null,
    base_revision: instance.revision,
  });
}
